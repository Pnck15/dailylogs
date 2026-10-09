import os
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot
from supabase import create_client


POLL_INTERVAL_MS = 15000
SOURCE_REFRESH_INTERVAL_MS = 5 * 60 * 1000


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

    @Slot()
    def run(self):
        try:
            client = create_client(self.url, self.key)
            response = client.auth.sign_in_with_password(
                {"email": self.email, "password": self.password}
            )

            if not response.user or not response.session:
                raise RuntimeError("Login ไม่สำเร็จ: ไม่พบ user/session")

            membership = (
                client.table("workspace_members")
                .select("workspace_id, role")
                .eq("user_id", response.user.id)
                .limit(1)
                .execute()
            )

            if not membership.data:
                raise RuntimeError(
                    "บัญชีนี้ยังไม่ได้อยู่ใน DailyLog Workspace"
                )

            workspace_id = str(membership.data[0]["workspace_id"])
            role = str(membership.data[0].get("role") or "")

            latest = (
                client.table("notification_events")
                .select("id")
                .eq("workspace_id", workspace_id)
                .order("id", desc=True)
                .limit(1)
                .execute()
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
                }
            )
        except Exception as exc:
            self.signals.error.emit(str(exc))


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


class CentralNotifyReceiver(QObject):
    event = Signal(
        str,
        str,
        str,
        bool,
        str,
    )
    source_list_changed = Signal(object)
    status_changed = Signal(str)
    login_success = Signal(str)
    login_failed = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.pool = QThreadPool.globalInstance()

        self.client = None
        self.workspace_id = ""
        self.role = ""
        self.email = ""
        self.last_id = 0
        self._busy = False
        self._login_busy = False
        self._paused = False

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

        self.url, self.key = load_notify_config()

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
        self.login(email, password, remember=True)

    def login(self, email, password, remember=True):
        if self._login_busy:
            return

        email = str(email or "").strip()
        password = str(password or "")

        if not email or not password:
            self.login_failed.emit("กรุณากรอก Email และ Password")
            return

        self._login_busy = True
        self.status_changed.emit("กำลังเชื่อมต่อ Central Notification...")

        job = _LoginJob(
            self.url,
            self.key,
            email,
            password,
        )
        job.signals.done.connect(
            lambda result: self._login_done(
                result,
                password,
                remember,
            )
        )
        job.signals.error.connect(self._login_error)
        self.pool.start(job)

    def _login_done(self, result, password, remember):
        self._login_busy = False
        self.client = result["client"]
        self.workspace_id = result["workspace_id"]
        self.role = result.get("role", "")
        self.email = result.get("email", "")

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

        self._sources_done(
            result.get(
                "notify_sources",
                [],
            )
        )

        if not self.timer.isActive():
            self.timer.start()

        if not self.source_timer.isActive():
            self.source_timer.start()

        self.refresh_sources()

        self.status_changed.emit(
            f"🟢 Central Notification: {self.email}"
        )
        self.login_success.emit(self.email)
        self.poll()

    def _login_error(self, message):
        self._login_busy = False
        self.client = None
        self.workspace_id = ""
        self.timer.stop()
        self.source_timer.stop()
        self.status_changed.emit(
            "🔴 Central Notification: Login ไม่สำเร็จ"
        )
        self.login_failed.emit(message)

    def refresh_sources(self):
        if self.client is None:
            return

        job = _SourceJob(
            self.client
        )
        job.signals.done.connect(
            self._sources_done
        )
        job.signals.error.connect(
            self._sources_error
        )
        self.pool.start(job)

    def _sources_done(
        self,
        rows,
    ):
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

    def _sources_error(
        self,
        message,
    ):
        print(
            "[Central Notify Sources]",
            message,
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
        self.pool.start(job)

    def _poll_done(self, rows):
        self._busy = False

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
            )

            if event_id > self.last_id:
                self.last_id = event_id

        if self.workspace_id:
            self.settings.setValue(
                f"central/{self.workspace_id}/last_event_id",
                self.last_id,
            )
            self.settings.sync()

        self.status_changed.emit(
            f"🟢 Central Notification: {self.email}"
        )

    def _poll_error(self, message):
        self._busy = False
        self.status_changed.emit(
            "🔴 Central Notification: เชื่อมต่อไม่ได้"
        )
        print("[Central Notify]", message)

    def logout(self):
        self.timer.stop()
        self.source_timer.stop()
        self._busy = False

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
        self._paused = False

        self.settings.remove("central/password")
        self.settings.sync()

        self.status_changed.emit(
            "⚪ Central Notification: ยังไม่ได้ Login"
        )
