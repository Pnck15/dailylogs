"""Real Windows 10/11 notifications for the unpackaged DailyLogNotify EXE.

Qt's QSystemTrayIcon.showMessage is a legacy balloon and may silently fail.
Use WinRT Toasts with a matching per-user Start-menu AUMID shortcut instead.
The PowerShell helper runs on a private Qt background thread, NEVER on the GUI
thread, and only accesses the per-user shortcut/registration marker.
"""
import base64
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

APP_USER_MODEL_ID = "MiniDailyLog.DailyLogNotify"
TOAST_SCRIPT = "notify_windows_toast.ps1"


def toast_script_path():
    bundle = getattr(sys, "_MEIPASS", None)
    return Path(bundle) / TOAST_SCRIPT if bundle else Path(__file__).resolve().with_name(TOAST_SCRIPT)


def native_windows_toast(title, message, *, exe_path=None, script_path=None,
                         system=None, timeout=20):
    """Return only after WinRT accepted the toast. May still be hidden by DND.

    No subprocess shell interpolation: Thai/Chinese and untrusted Sheet values
    are passed as Base64 UTF-8 data, never executable PowerShell code.
    """
    platform = sys.platform if system is None else system
    if platform != "win32":
        raise RuntimeError("Windows Notification is available only on Windows.")
    exe = Path(exe_path or sys.executable).resolve()
    script = Path(script_path or toast_script_path()).resolve()
    if not script.is_file():
        raise RuntimeError("Native Windows Notification helper is missing from this EXE.")
    if not exe.is_file():
        raise RuntimeError("DailyLogNotify executable could not be located.")

    encode = lambda value: base64.b64encode(
        str(value or "").encode("utf-8")
    ).decode("ascii")
    args = [
        "powershell.exe",
        "-NoLogo", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-File", str(script),
        "-ExePath", str(exe),
        "-AppId", APP_USER_MODEL_ID,
        "-TitleBase64", encode(str(title or "DailyLogNotify")[:140]),
        "-BodyBase64", encode(str(message or "")[:1500]),
    ]
    result = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    output = result.stdout.decode("utf-8", errors="replace")
    error = result.stderr.decode("utf-8", errors="replace").strip()
    if result.returncode != 0:
        raise RuntimeError(
            (error or output or "Windows rejected the notification.").strip()[:600]
        )
    if "TOAST_SUBMITTED" not in output:
        raise RuntimeError("Windows did not confirm that the toast was submitted.")
    return True


def check_windows_notification_registration(*, repair=False, exe_path=None,
                                            script_path=None, system=None,
                                            timeout=55):
    """Inspect WinRT permission and optionally repair ONLY our Start shortcut.

    Does not modify Notifications/Do Not Disturb/Group Policy registry values,
    and does not send or read any notification or user data.
    """
    platform = sys.platform if system is None else system
    if platform != "win32":
        raise RuntimeError("Windows Notification is available only on Windows.")
    exe = Path(exe_path or sys.executable).resolve()
    script = Path(script_path or toast_script_path()).resolve()
    if not exe.is_file() or not script.is_file():
        raise RuntimeError("Windows Toast executable/helper is missing.")
    command = [
        "powershell.exe",
        "-NoLogo", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-File", str(script),
        "-ExePath", str(exe),
        "-AppId", APP_USER_MODEL_ID,
        "-RepairShortcut" if repair else "-DiagnoseOnly",
    ]
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace").strip()
    if result.returncode != 0:
        raise RuntimeError(
            (stderr or stdout or "Windows Toast registration check failed").strip()[:600]
        )
    found = [
        line.strip().split(":", 1)[1].strip()
        for line in stdout.splitlines()
        if line.strip().startswith("TOAST_SETTING:")
    ]
    if len(found) != 1:
        raise RuntimeError("Unable to read Windows Notification setting.")
    return found[0]


class _DeliverySignals(QObject):
    done = Signal(object)
    error = Signal(str)


class _DeliveryJob(QRunnable):
    def __init__(self, title, message):
        super().__init__()
        self.title = str(title or "DailyLogNotify")
        self.message = str(message or "")
        self.signals = _DeliverySignals()
        # Keep signals alive until Qt delivers them on the UI thread.
        self.setAutoDelete(False)

    @Slot()
    def run(self):
        try:
            self.signals.done.emit(
                native_windows_toast(self.title, self.message)
            )
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            self.signals.error.emit(str(exc))


class _RegistrationJob(QRunnable):
    def __init__(self, repair=False):
        super().__init__()
        self.repair = bool(repair)
        self.signals = _DeliverySignals()
        self.setAutoDelete(False)

    @Slot()
    def run(self):
        try:
            setting = check_windows_notification_registration(
                repair=self.repair
            )
            self.signals.done.emit(setting)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            self.signals.error.emit(str(exc))


class NativeToastDispatcher(QObject):
    """FIFO worker; a failing native toast is reported for popup fallback."""

    succeeded = Signal(str)
    failed = Signal(str, str, str)
    registration_status = Signal(str, bool)
    registration_error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self._jobs = {}

    def send(self, title, message):
        title = str(title or "DailyLogNotify")
        message = str(message or "")
        if sys.platform != "win32":
            self.failed.emit(title, message, "Windows notifications require Windows.")
            return False
        if len(self._jobs) >= 10:
            self.failed.emit(
                title, message, "Windows notification queue is full."
            )
            return False
        job = _DeliveryJob(title, message)
        self._jobs[job.signals] = job
        job.signals.done.connect(self._on_done)
        job.signals.error.connect(self._on_error)
        self.pool.start(job)
        return True

    def repair_registration(self):
        """Re-register this app's existing Start shortcut asynchronously."""
        if sys.platform != "win32":
            self.registration_error.emit(
                "Windows Notification ใช้งานได้เฉพาะบน Windows"
            )
            return False
        if any(isinstance(x, _RegistrationJob) for x in self._jobs.values()):
            return False
        job = _RegistrationJob(repair=True)
        self._jobs[job.signals] = job
        job.signals.done.connect(self._on_done)
        job.signals.error.connect(self._on_error)
        self.pool.start(job)
        return True

    @Slot(object)
    def _on_done(self, _result):
        job = self._jobs.pop(self.sender(), None)
        if isinstance(job, _RegistrationJob):
            self.registration_status.emit(str(_result), job.repair)
        elif job is not None:
            self.succeeded.emit(job.title)

    @Slot(str)
    def _on_error(self, message):
        job = self._jobs.pop(self.sender(), None)
        if isinstance(job, _RegistrationJob):
            self.registration_error.emit(str(message)[:600])
        elif job is not None:
            self.failed.emit(job.title, job.message, str(message)[:600])
