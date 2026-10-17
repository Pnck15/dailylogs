import base64
import json
import os
import platform
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSettings, QThreadPool, QTimer, Signal, Slot
from supabase import create_client


POLL_INTERVAL_MS = 15000
SOURCE_REFRESH_INTERVAL_MS = 60 * 1000
DEVICE_HEARTBEAT_INTERVAL_MS = 60 * 1000

# When Windows starts before networking is ready, retry automatically.
# Back off on sustained outages to avoid hammering Supabase Auth.
LOGIN_RETRY_INITIAL_MS = 8 * 1000
LOGIN_RETRY_MAX_MS = 5 * 60 * 1000

# Credentials and authorization failures need deliberate user intervention;
# retrying them can lock the account or silently defeat admin session control.
_NON_RETRYABLE_LOGIN_MARKERS = (
    "invalid login credentials",
    "email not confirmed",
    "email_not_confirmed",
    "invalid_grant",
    "workspace member",
    "dailylog workspace",
    "not authorized",
    "permission denied",
    "access denied",
    "บัญชีนี้ยังไม่ได้",
)
_AUTH_POLL_ERROR_MARKERS = (
    "jwt expired",
    "invalid jwt",
    "invalid token",
    "token has expired",
    "not authenticated",
    "session not found",
    "401 unauthorized",
    "pgrst301",
)



def _session_id_from_access_token(access_token):
    token = str(access_token or "").strip()

    if not token:
        return ""

    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(
            payload.encode("ascii")
        )
        data = json.loads(
            decoded.decode("utf-8")
        )
        return str(
            data.get("session_id") or ""
        ).strip()
    except Exception:
        return ""


def _read_env_file(path):
    values = {}
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return values


def load_notify_config():
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()

    candidates = []

    if getattr(sys, "frozen", False):
        bundle_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        candidates.append(bundle_dir / "notify.env")
        candidates.append(Path(sys.executable).resolve().parent / "notify.env")
    else:
        app_dir = Path(__file__).resolve().parent
        candidates.append(app_dir / "notify.env")
        candidates.append(app_dir / ".env")

    for path in candidates:
        values = _read_env_file(path)
        if not url:
            url = str(values.get("SUPABASE_URL", "") or "").strip()
        if not key:
            key = str(values.get("SUPABASE_PUBLISHABLE_KEY", "") or "").strip()
        if url and key:
            break

    if not url or not key:
        raise RuntimeError(
            "ไม่พบการตั้งค่า Central Notification "
            "(SUPABASE_URL / SUPABASE_PUBLISHABLE_KEY)"
        )

    return url, key


class _Signals(QObject):
    done = Signal(object)
    error = Signal(str)


class _LoginJob(QRunnable):
    def __init__(self, url, key, email, password):
        super().__init__()
        self.url = url
        self.key = key
        self.email = email
        self.password = password
        self.signals = _Signals()

    @staticmethod
    def _retry_authenticated_query(task):
        # Reuse the signed-in client/session, never send a second password
        # login merely because a workspace or cursor request timed out.
        last_error = None
        for attempt in range(3):
            try:
                return task()
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(0.4 * (attempt + 1))
        raise last_error

    @Slot()
    def run(self):
        stage = "Supabase Authentication"
        try:
            client = create_client(self.url, self.key)
            response = client.auth.sign_in_with_password(
                {"email": self.email, "password": self.password}
            )

            if not response.user or not response.session:
                raise RuntimeError("Login ไม่สำเร็จ: ไม่พบ user/session")

            stage = "Workspace membership"
            membership = self._retry_authenticated_query(
                lambda: (
                    client.table("workspace_members")
                    .select("workspace_id, role")
                    .eq("user_id", response.user.id)
                    .limit(1)
                    .execute()
                )
            )

            if not membership.data:
                raise RuntimeError(
                    "บัญชีนี้ยังไม่ได้อยู่ใน DailyLog Workspace"
                )

            workspace_id = str(membership.data[0]["workspace_id"])
            role = str(membership.data[0].get("role") or "")

            stage = "Notification event cursor"
            latest = self._retry_authenticated_query(
                lambda: (
                    client.table("notification_events")
                    .select("id")
                    .eq("workspace_id", workspace_id)
                    .order("id", desc=True)
                    .limit(1)
                    .execute()
                )
            )

            latest_id = 0
            if latest.data:
                latest_id = int(latest.data[0].get("id") or 0)

            notify_sources = []

            try:
                source_response = (
                    client.rpc(
                        "get_notify_sources"
                    ).execute()
                )
                notify_sources = (
                    source_response.data
                    or []
                )
            except Exception:
                # Login must still succeed even if source discovery
                # is temporarily unavailable. The periodic source
                # refresh will try again.
                notify_sources = []

            self.signals.done.emit(
                {
                    "client": client,
                    "user_id": str(response.user.id),
                    "workspace_id": workspace_id,
                    "role": role,
                    "email": self.email,
                    "latest_id": latest_id,
                    "notify_sources": notify_sources,
                    "session_id": _session_id_from_access_token(
                        response.session.access_token
                    ),
                }
            )
        except Exception as exc:
            # The stage identifies whether password auth actually failed
            # or a subsequent network/RLS query failed after sign-in.
            self.signals.error.emit(f"{stage}: {type(exc).__name__}: {exc}")


class _SourceJob(QRunnable):
    def __init__(self, client):
        super().__init__()
        self.client = client
        self.signals = _Signals()

    @Slot()
    def run(self):
        try:
            response = (
                self.client.rpc(
                    "get_notify_sources"
                ).execute()
            )

            self.signals.done.emit(
                response.data or []
            )
        except Exception as exc:
            self.signals.error.emit(
                str(exc)
            )


class _HeartbeatJob(QRunnable):
    def __init__(
        self,
        client,
        device_id,
        device_name,
        app_version,
        selected_sources,
        startup_enabled,
        updater_ready,
    ):
        super().__init__()
        self.client = client
        self.device_id = device_id
        self.device_name = device_name
        self.app_version = app_version
        self.selected_sources = selected_sources
        self.startup_enabled = startup_enabled
        self.updater_ready = updater_ready
        self.signals = _Signals()

    @Slot()
    def run(self):
        try:
            response = (
                self.client.rpc(
                    "register_notify_device",
                    {
                        "p_device_id": self.device_id,
                        "p_device_name": self.device_name,
                        "p_app_version": self.app_version,
                        "p_selected_sources": self.selected_sources,
                        "p_startup_enabled": self.startup_enabled,
                        "p_updater_ready": self.updater_ready,
                    },
                ).execute()
            )

            data = response.data or {}
            if isinstance(data, dict) and data.get("active") is True:
                try:
                    command = self.client.rpc(
                        "claim_notify_force_update"
                    ).execute().data or {}
                    if isinstance(command, dict) and command.get("request_id"):
                        data = dict(data)
                        data["force_update_request"] = command
                except Exception as error:
                    # Heartbeat success must not be downgraded by a temporary
                    # command queue failure. No secrets in the log.
                    print("[Notify Force Update] claim retry:",
                          type(error).__name__)
            self.signals.done.emit(data)
        except Exception as exc:
            self.signals.error.emit(str(exc))


class _UpdateResultJob(QRunnable):
    def __init__(self, client, request_id, status, detail):
        super().__init__()
        self.client = client
        self.request_id = int(request_id)
        self.status = str(status)
        self.detail = str(detail or "")[:300]
        self.signals = _Signals()

    @Slot()
    def run(self):
        try:
            result = self.client.rpc("report_notify_force_update", {
                "p_request_id": self.request_id,
                "p_status": self.status,
                "p_detail": self.detail,
            }).execute()
            self.signals.done.emit(bool(result.data))
        except Exception as error:
            self.signals.error.emit(type(error).__name__)


class _PollJob(QRunnable):
    def __init__(self, client, workspace_id, last_id):
        super().__init__()
        self.client = client
        self.workspace_id = workspace_id
        self.last_id = int(last_id or 0)
        self.signals = _Signals()

    @Slot()
    def run(self):
        try:
            response = (
                self.client.table("notification_events")
                .select(
                    "id, source_key, source, title, message, notification_type, created_at"
                )
                .eq("workspace_id", self.workspace_id)
                .gt("id", self.last_id)
                .order("id", desc=False)
                .limit(100)
                .execute()
            )
            self.signals.done.emit(response.data or [])
        except Exception as exc:
            self.signals.error.emit(str(exc))


class _CentralHistoryPurgeJob(QRunnable):
    """Admin cleanup on the receiver's serial network thread."""
    def __init__(self, client, scope):
        super().__init__()
        self.client = client
        self.scope = scope
        self.signals = _Signals()

    @Slot()
    def run(self):
        try:
            reply = self.client.rpc(
                "purge_notification_history", {"p_scope": self.scope}
            ).execute()
            self.signals.done.emit(reply.data or {})
        except Exception as error:
            self.signals.error.emit(str(error))


class CentralNotifyReceiver(QObject):
    event = Signal(
        str,
        str,
        str,
        bool,
        str,
        str,  # Original Central event created_at, for global retention
    )
    history_purge = Signal(object)
    global_purge_success = Signal(object)
    global_purge_error = Signal(str)
    source_list_changed = Signal(object)
    status_changed = Signal(str)
    login_success = Signal(str)
    login_failed = Signal(str)
    session_revoked = Signal(str)
    force_update_requested = Signal(object)

    def __init__(
        self,
        settings,
        parent=None,
        app_version="",
    ):
        super().__init__(parent)
        self.settings = settings
        # Supabase Auth refresh-token rotation is not safe across
        # simultaneous polling, source and heartbeat requests sharing
        # one client. Serialize network jobs for this receiver instance.
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        # Keep QRunnables and their _Signals alive until all queued Qt
        # signal handlers have finished; auto-delete used to race the GUI.
        self._active_jobs = set()
        self._job_by_signals = {}

        self.client = None
        self.workspace_id = ""
        self.role = ""
        self.email = ""
        self.session_id = ""
        self.app_version = str(
            app_version or ""
        ).strip()
        self.device_name = (
            os.environ.get("COMPUTERNAME")
            or platform.node()
            or "Windows PC"
        )

        saved_device_id = str(
            self.settings.value(
                "device/id",
                "",
            )
            or ""
        ).strip()

        try:
            self.device_id = str(
                uuid.UUID(
                    saved_device_id
                )
            )
        except Exception:
            self.device_id = str(
                uuid.uuid4()
            )
            self.settings.setValue(
                "device/id",
                self.device_id,
            )
            self.settings.sync()

        self.last_id = 0
        self._busy = False
        self._heartbeat_busy = False
        self._source_busy = False
        self._login_busy = False
        self._login_context = None
        self._paused = False
        self._login_was_automatic = False
        self._session_revoked = False
        self.device_registration_state = "not_connected"
        self.last_heartbeat_at = ""
        self.last_heartbeat_error = ""
        self._login_retry_attempt = 0
        self._poll_failures = 0

        self.login_retry_timer = QTimer(self)
        self.login_retry_timer.setSingleShot(True)
        self.login_retry_timer.timeout.connect(self.login_saved)

        self.timer = QTimer(self)
        self.timer.setInterval(POLL_INTERVAL_MS)
        self.timer.timeout.connect(self.poll)

        self.source_timer = QTimer(self)
        self.source_timer.setInterval(
            SOURCE_REFRESH_INTERVAL_MS
        )
        self.source_timer.timeout.connect(
            self.refresh_sources
        )

        self.heartbeat_timer = QTimer(
            self
        )
        self.heartbeat_timer.setInterval(
            DEVICE_HEARTBEAT_INTERVAL_MS
        )
        self.heartbeat_timer.timeout.connect(
            self.send_heartbeat
        )

        self.url, self.key = load_notify_config()

    def _start_job(self, job):
        # Keep each QRunnable and Qt signal sender alive until the GUI thread
        # has processed its result. A lambda without QObject context can run
        # immediately on the network thread, before UI signal handlers.
        job.setAutoDelete(False)
        self._active_jobs.add(job)
        self._job_by_signals[job.signals] = job
        job.signals.done.connect(self._job_finished)
        job.signals.error.connect(self._job_failed)
        try:
            self.pool.start(job)
        except Exception:
            self._job_by_signals.pop(job.signals, None)
            self._active_jobs.discard(job)
            raise

    @Slot(object)
    def _job_finished(self, _result):
        self._release_job_on_gui_thread()

    @Slot(str)
    def _job_failed(self, _error):
        self._release_job_on_gui_thread()

    def _release_job_on_gui_thread(self):
        sender = self.sender()
        job = self._job_by_signals.pop(sender, None)
        if job is not None:
            self._active_jobs.discard(job)

    def has_saved_credentials(self):
        email = str(
            self.settings.value("central/email", "") or ""
        ).strip()
        password = str(
            self.settings.value("central/password", "") or ""
        )
        return bool(email and password)

    def login_saved(self):
        email = str(
            self.settings.value("central/email", "") or ""
        ).strip()
        password = str(
            self.settings.value("central/password", "") or ""
        )
        if not email or not password:
            self.login_failed.emit("ยังไม่ได้ตั้งค่าบัญชีรับ Notification")
            return
        if self._session_revoked:
            return
        self.login(email, password, remember=True, automatic=True)

    def login(self, email, password, remember=True, automatic=False):
        if self._login_busy:
            return False

        # A manual login can recover a previously admin-revoked session,
        # but automatic background retries must never undo such a revoke.
        if self._session_revoked and automatic:
            return False
        self.login_retry_timer.stop()
        email = str(email or "").strip()
        password = str(password or "")

        if not email or not password:
            self.login_failed.emit("กรุณากรอก Email และ Password")
            return False

        self._login_busy = True
        self._login_context = (password, bool(remember))
        self._login_was_automatic = bool(automatic)
        self.status_changed.emit("🟡 Central Notification: กำลัง Login...")

        job = _LoginJob(
            self.url,
            self.key,
            email,
            password,
        )
        # A bound QObject slot guarantees state/timers are updated on
        # the Qt GUI thread, not from a Python lambda in the worker.
        job.signals.done.connect(self._on_login_job_done)
        job.signals.error.connect(self._login_error)
        self._start_job(job)
        return True

    @Slot(object)
    def _on_login_job_done(self, result):
        context = self._login_context
        self._login_context = None
        if context is None:
            return
        password, remember = context
        try:
            self._login_done(result, password, remember)
        except Exception as error:
            # Do not strand a signed-in client silently before heartbeat.
            self._login_error(
                "Notify setup after Auth: "
                f"{type(error).__name__}: {str(error)[:160]}"
            )

    def _login_done(self, result, password, remember):
        self._login_busy = False
        self._login_was_automatic = False
        self.device_registration_state = "pending"
        self.last_heartbeat_error = ""
        self._session_revoked = False
        self.login_retry_timer.stop()
        self._login_retry_attempt = 0
        self._poll_failures = 0
        self.client = result["client"]
        self.workspace_id = result["workspace_id"]
        self.role = result.get("role", "")
        self.email = result.get("email", "")
        self.session_id = str(
            result.get(
                "session_id",
                "",
            )
            or ""
        ).strip()

        cursor_key = (
            f"central/{self.workspace_id}/last_event_id"
        )
        saved_cursor = self.settings.value(
            cursor_key,
            None,
        )

        if saved_cursor is None:
            # First installation: do not replay the entire old history.
            self.last_id = int(result.get("latest_id") or 0)
            self.settings.setValue(
                cursor_key,
                self.last_id,
            )
        else:
            try:
                self.last_id = int(saved_cursor)
            except (TypeError, ValueError):
                self.last_id = int(result.get("latest_id") or 0)

        if remember:
            self.settings.setValue(
                "central/email",
                self.email,
            )
            self.settings.setValue(
                "central/password",
                password,
            )
        else:
            self.settings.remove("central/password")

        self.settings.sync()

        try:
            self._sources_done(
                result.get(
                    "notify_sources",
                    [],
                )
            )
        except (ValueError, TypeError, KeyError) as error:
            # Never lose an authenticated session or skip registration
            # because a source-catalog entry has unexpected data.
            print(
                "[Notify Sources] source catalog unavailable",
                type(error).__name__,
            )

        if not self.timer.isActive():
            self.timer.start()

        if not self.source_timer.isActive():
            self.source_timer.start()

        if not self.heartbeat_timer.isActive():
            self.heartbeat_timer.start()

        self.refresh_sources()
        self.send_heartbeat()

        self.status_changed.emit(
            "🟡 Central Login สำเร็จ — กำลังยืนยันอุปกรณ์รับแจ้งเตือน"
        )
        self.login_success.emit(self.email)
        self.poll()

    @staticmethod
    def _login_error_requires_manual_action(message):
        text = str(message or "").casefold()
        return any(marker in text for marker in _NON_RETRYABLE_LOGIN_MARKERS)

    def _schedule_saved_login_retry(self, reason=""):
        if (
            self._session_revoked
            or self._login_busy
            or self.client is not None
            or not self.has_saved_credentials()
            or self.login_retry_timer.isActive()
        ):
            return False

        delay_ms = min(
            LOGIN_RETRY_INITIAL_MS * (2 ** min(self._login_retry_attempt, 6)),
            LOGIN_RETRY_MAX_MS,
        )
        self._login_retry_attempt = min(self._login_retry_attempt + 1, 7)
        seconds = max(1, (delay_ms + 999) // 1000)
        self.status_changed.emit(
            f"🟡 Central Notification: เชื่อมต่อสะดุด — ลองใหม่ใน {seconds} วินาที"
        )
        # Never print credentials or raw authentication errors to shared logs.
        print("[Notify Auto Reconnect]", "retry scheduled", seconds, "seconds")
        self.login_retry_timer.start(delay_ms)
        return True

    @Slot(str)
    def _login_error(self, message):
        self._login_context = None
        automatic = self._login_was_automatic
        self._login_was_automatic = False
        self._login_busy = False
        self.client = None
        self.workspace_id = ""
        self.timer.stop()
        self.source_timer.stop()
        self.heartbeat_timer.stop()
        self.session_id = ""
        self.device_registration_state = "login_failed"
        self.last_heartbeat_error = str(message or "")[:250]

        # Only the login initiated from locally remembered credentials
        # gets an unattended retry; invalid credentials or revoked access
        # should never be retried indefinitely.
        if (
            automatic
            and not self._login_error_requires_manual_action(message)
            and self._schedule_saved_login_retry(message)
        ):
            return

        self.status_changed.emit(
            "🔴 Central Notification: Login ไม่สำเร็จ"
        )
        self.login_failed.emit(str(message))

    def refresh_sources(self):
        if self.client is None or self._source_busy:
            return
        self._source_busy = True

        job = _SourceJob(
            self.client
        )
        job.signals.done.connect(
            self._sources_done
        )
        job.signals.error.connect(
            self._sources_error
        )
        self._start_job(job)

    @Slot(object)
    def _sources_done(
        self,
        rows,
    ):
        self._source_busy = False
        normalized = []

        for item in rows or []:
            if not isinstance(
                item,
                dict,
            ):
                continue

            key = str(
                item.get(
                    "source_key",
                    "",
                )
                or ""
            ).strip()

            name = str(
                item.get(
                    "source_name",
                    "",
                )
                or ""
            ).strip()

            if not key or not name:
                continue

            normalized.append({
                "key": key,
                "label": name,
                "source_type": str(
                    item.get(
                        "source_type",
                        "",
                    )
                    or ""
                ).strip(),
                "display_order": int(
                    item.get(
                        "display_order",
                        100,
                    )
                    or 100
                ),
            })

        self.source_list_changed.emit(
            normalized
        )

    @Slot(str)
    def _sources_error(
        self,
        message,
    ):
        self._source_busy = False
        print(
            "[Central Notify Sources]",
            message,
        )

    def _selected_source_keys_for_device(self):
        raw = str(
            self.settings.value(
                "sources/selected",
                "",
            )
            or ""
        ).strip()

        if not raw:
            return []

        return [
            item.strip()
            for item in raw.split(",")
            if item.strip()
        ]

    def _startup_enabled_for_device(self):
        if not getattr(
            sys,
            "frozen",
            False,
        ):
            return False

        run = QSettings(
            (
                r"HKEY_CURRENT_USER\Software\Microsoft\Windows"
                r"\CurrentVersion\Run"
            ),
            QSettings.Format.NativeFormat,
        )

        value = str(
            run.value(
                "DailyLogNotify",
                "",
            )
            or ""
        )

        return (
            os.path.normcase(
                os.path.abspath(
                    sys.executable
                )
            )
            in os.path.normcase(
                value
            )
        )

    def _updater_ready_for_device(self):
        if not getattr(
            sys,
            "frozen",
            False,
        ):
            return False

        return os.path.isfile(
            os.path.join(
                os.path.dirname(
                    sys.executable
                ),
                "DailyLogUpdater.exe",
            )
        )

    def report_force_update(self, request_id, status, detail="", on_done=None):
        """Record the targeted update attempt without blocking the Qt UI."""
        if self.client is None or not request_id:
            if callable(on_done):
                on_done()
            return
        job = _UpdateResultJob(self.client, request_id, status, detail)
        if callable(on_done):
            job.signals.done.connect(lambda _result: on_done())
            job.signals.error.connect(lambda _error: on_done())
        self._start_job(job)

    def send_heartbeat(self):
        if (
            self._heartbeat_busy
            or self.client is None
            or not self.workspace_id
        ):
            return

        self._heartbeat_busy = True

        job = _HeartbeatJob(
            self.client,
            self.device_id,
            self.device_name,
            self.app_version,
            self._selected_source_keys_for_device(),
            self._startup_enabled_for_device(),
            self._updater_ready_for_device(),
        )
        job.signals.done.connect(
            self._heartbeat_done
        )
        job.signals.error.connect(
            self._heartbeat_error
        )
        self._start_job(job)

    @Slot(object)
    def _heartbeat_done(
        self,
        result,
    ):
        self._heartbeat_busy = False

        data = result

        if (
            isinstance(
                data,
                list,
            )
            and data
        ):
            data = data[0]

        if not isinstance(
            data,
            dict,
        ):
            return

        if data.get(
            "active",
            True,
        ) is not False:
            self.device_registration_state = "active"
            self.last_heartbeat_at = datetime.now().astimezone().isoformat(
                timespec="seconds"
            )
            self.last_heartbeat_error = ""
            self.status_changed.emit(
                f"🟢 Central Notification: {self.email}"
            )
            command = data.get("force_update_request") or {}
            if isinstance(command, dict) and command.get("request_id"):
                self.force_update_requested.emit(command)

        if data.get(
            "active",
            True,
        ) is False:
            # The server currently returns active=false when the JWT's
            # session_id is absent from auth.sessions; this is NOT proof
            # that an Admin explicitly revoked a device. Do not mislabel it.
            self._handle_session_revoked(
                "Central ไม่ยืนยัน Session ปัจจุบัน "
                "(อาจหมดอายุ ถูกเพิกถอน หรือมีปัญหาการซิงก์) "
                "กรุณา Login ใหม่และตรวจสิทธิ์หากเกิดซ้ำ"
            )

    @Slot(str)
    def _heartbeat_error(
        self,
        message,
    ):
        self._heartbeat_busy = False
        self.device_registration_state = "retrying"
        # Keep a bounded diagnostic message; never log credentials or JWTs.
        self.last_heartbeat_error = str(message or "")[:200]
        self.status_changed.emit(
            "🟡 Central Notification: Login แล้ว แต่ลงทะเบียนเครื่องยังไม่สำเร็จ"
        )
        print("[Notify Device Heartbeat] registration failed")

    def _handle_session_revoked(self, reason=None):
        self._session_revoked = True
        self.device_registration_state = "rejected"
        self.last_heartbeat_error = str(reason or "")[:200]
        self.login_retry_timer.stop()
        self.timer.stop()
        self.source_timer.stop()
        self.heartbeat_timer.stop()
        self._busy = False
        self._heartbeat_busy = False

        self.client = None
        self.workspace_id = ""
        self.role = ""
        self.email = ""
        self.session_id = ""
        self._paused = False

        # Do not auto-login again after Admin explicitly removed
        # this device session.
        self.settings.remove(
            "central/password"
        )
        self.settings.sync()

        message = str(reason or (
            "Central ปิดการใช้งาน Session นี้ "
            "กรุณา Login ใหม่หรือให้ผู้ดูแลตรวจสอบสิทธิ์"
        ))

        self.status_changed.emit(
            "🔴 Central Notification: Session ต้องตรวจสอบอีกครั้ง"
        )
        self.session_revoked.emit(
            message
        )

    def pause(self):
        self._paused = True
        self.timer.stop()

    def resume(self):
        self._paused = False

        if (
            self.client is not None
            and self.workspace_id
        ):
            if not self.timer.isActive():
                self.timer.start()
            self.poll()

    def poll(self):
        if (
            self._paused
            or self._busy
            or not self.client
            or not self.workspace_id
        ):
            return

        self._busy = True

        job = _PollJob(
            self.client,
            self.workspace_id,
            self.last_id,
        )
        job.signals.done.connect(self._poll_done)
        job.signals.error.connect(self._poll_error)
        self._start_job(job)

    @Slot(object)
    def _on_global_purge_done(self, value):
        self.global_purge_success.emit(value if isinstance(value, dict) else {})
        # Fetch the Central marker now instead of waiting for next poll.
        self.poll()

    @Slot(str)
    def _on_global_purge_error(self, message):
        self.global_purge_error.emit(str(message))

    def purge_notification_history(self, scope):
        if scope not in ("yesterday", "last_7_days", "older_than_7_days", "older_than_30_days", "all"):
            self.global_purge_error.emit("ช่วงเวลาล้างประวัติไม่ถูกต้อง")
            return False
        if (
            self.client is None
            or not self.workspace_id
            or str(self.role or "").strip().lower() != "admin"
        ):
            self.global_purge_error.emit(
                "ต้อง Login ด้วยบัญชี Admin ของ Workspace ก่อน"
            )
            return False
        job = _CentralHistoryPurgeJob(self.client, scope)
        job.signals.done.connect(self._on_global_purge_done)
        job.signals.error.connect(self._on_global_purge_error)
        self._start_job(job)
        return True

    @Slot(object)
    def _poll_done(self, rows):
        self._busy = False
        self._poll_failures = 0

        for row in rows:
            try:
                event_id = int(row.get("id") or 0)
            except (TypeError, ValueError):
                event_id = 0

            source = str(row.get("source") or "DailyLog")
            source_key = str(
                row.get("source_key")
                or ""
            ).strip()
            title = str(row.get("title") or "DailyLog Notification")
            message = str(row.get("message") or "")

            created_at = str(
                row.get("created_at") or ""
            ).strip()

            # Admin cleanup is a signed workspace event published by the
            # restricted RPC, never a normal source popup or local history.
            if (
                str(row.get("notification_type") or "") == "history_purge"
                and source_key == "__central_history_purge__"
            ):
                try:
                    payload = json.loads(message)
                    if (
                        isinstance(payload, dict)
                        and payload.get("scope") in ("yesterday", "last_7_days", "older_than_7_days", "older_than_30_days", "all")
                        and payload.get("end")
                    ):
                        self.history_purge.emit(payload)
                except (ValueError, TypeError):
                    print("[Notify Central Purge] Ignored malformed marker")
                if event_id > self.last_id:
                    self.last_id = event_id
                continue

            show_popup = True
            if created_at:
                try:
                    parsed = datetime.fromisoformat(
                        created_at.replace("Z", "+00:00")
                    )
                    local_created = parsed.astimezone()
                    local_today = datetime.now().astimezone().date()
                    show_popup = (
                        local_created.date() == local_today
                    )
                except ValueError:
                    show_popup = True

            self.event.emit(
                source,
                title,
                message,
                show_popup,
                source_key,
                created_at,
            )

            if event_id > self.last_id:
                self.last_id = event_id

        if self.workspace_id:
            self.settings.setValue(
                f"central/{self.workspace_id}/last_event_id",
                self.last_id,
            )
            self.settings.sync()

        if self.device_registration_state == "active":
            self.status_changed.emit(
                f"🟢 Central Notification: {self.email}"
            )
        else:
            self.status_changed.emit(
                "🟡 Central Login สำเร็จ — รอยืนยัน Heartbeat อุปกรณ์"
            )

    @Slot(str)
    def _poll_error(self, message):
        self._busy = False
        self._poll_failures += 1

        error_text = str(message or "").casefold()
        if any(marker in error_text for marker in _AUTH_POLL_ERROR_MARKERS):
            # Do not automatically sign in again with a password here:
            # a 401 may be a session explicitly revoked by Admin.
            # The saved event cursor is retained for manual recovery.
            self.timer.stop()
            self.source_timer.stop()
            self.heartbeat_timer.stop()
            self.status_changed.emit(
                "🔴 Central Notification: Session ต้อง Login ใหม่"
            )
            self.login_failed.emit(
                "Session ไม่สามารถใช้งานได้ กรุณาตรวจสิทธิ์และ Login ใหม่"
            )
            return

        # A brief Wi-Fi switch or transient timeout is recoverable by
        # the existing 15-second polling timer; do not mark the device
        # as permanently disconnected after a single failed poll.
        if self._poll_failures < 3:
            self.status_changed.emit(
                "🟡 Central Notification: เครือข่ายสะดุด — ลองใหม่อัตโนมัติ"
            )
        else:
            self.status_changed.emit(
                "🔴 Central Notification: เครือข่ายไม่พร้อม — กำลังลองใหม่"
            )
        print("[Central Notify]", "poll failed", self._poll_failures)

    def logout(self):
        # An in-flight login result must not silently reconnect a session
        # after the user requested an explicit logout.
        self._login_context = None
        self._login_busy = False
        self._login_was_automatic = False
        self.device_registration_state = "not_connected"
        self.last_heartbeat_error = ""
        self.login_retry_timer.stop()
        self._login_retry_attempt = 0
        self._session_revoked = False
        self.timer.stop()
        self.source_timer.stop()
        self.heartbeat_timer.stop()
        self._busy = False
        self._heartbeat_busy = False

        if self.client is not None:
            try:
                # Important for shared receiver accounts:
                # logging out on this PC must not revoke sessions
                # on other PCs.
                self.client.auth.sign_out(
                    {
                        "scope": "local",
                    }
                )
            except Exception as error:
                print(
                    "[Central Notify Local Logout]",
                    error,
                )

        self.client = None
        self.workspace_id = ""
        self.role = ""
        self.email = ""
        self.session_id = ""
        self._paused = False

        self.settings.remove("central/password")
        self.settings.sync()

        self.status_changed.emit(
            "⚪ Central Notification: ยังไม่ได้ Login"
        )
