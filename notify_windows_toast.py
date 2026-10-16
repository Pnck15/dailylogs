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


class NativeToastDispatcher(QObject):
    """FIFO worker; a failing native toast is reported for popup fallback."""

    succeeded = Signal(str)
    failed = Signal(str, str, str)

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

    @Slot(object)
    def _on_done(self, _result):
        job = self._jobs.pop(self.sender(), None)
        if job is not None:
            self.succeeded.emit(job.title)

    @Slot(str)
    def _on_error(self, message):
        job = self._jobs.pop(self.sender(), None)
        if job is not None:
            self.failed.emit(job.title, job.message, str(message)[:600])
