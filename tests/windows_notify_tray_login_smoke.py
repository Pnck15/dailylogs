"""Real Qt lifecycle and mocked-auth smoke tests; never contact Supabase."""
import os
import sys
import tempfile
import time
import threading
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QSettings, QRunnable, Signal
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from dailylog_notify import LoginDialog, NotifyApp
from notify_receiver import CentralNotifyReceiver, _LoginJob, _Signals


class FakeHistory:
    def all(self):
        return []


class FakeReceiver(QObject):
    event = Signal(str, str, str, bool, str)
    source_list_changed = Signal(object)
    status_changed = Signal(str)
    login_success = Signal(str)
    login_failed = Signal(str)
    session_revoked = Signal(str)

    def __init__(self, settings, parent=None, app_version=""):
        super().__init__(parent)
        self.client = None
        self.email = ""
        self.workspace_id = ""
        self.device_name = "Offline Test"
        self.device_id = "test-id"

    def has_saved_credentials(self):
        return True

    def login_saved(self):
        pass

    def login(self, email, password, remember=True):
        # Simulates clicking manual Login while saved-credentials login is
        # still in progress; it must NOT leave the button disabled forever.
        return False


def check_main_window_x(app, settings):
    with patch("dailylog_notify.NotificationHistory", FakeHistory), patch(
        "dailylog_notify.CentralNotifyReceiver", FakeReceiver
    ), patch("dailylog_notify.QSettings", return_value=settings):
        window = NotifyApp()
    try:
        assert window.tray_menu.parent() is window, (
            "Tray menu must be parented for full process lifetime"
        )
        assert window.tray.contextMenu() is window.tray_menu
        assert not app.quitOnLastWindowClosed()
        window.showNormal()
        app.processEvents()

        # Simulate Windows tray present: the application's X hides only
        # the main window; existing process/tray and reopen remain active.
        with patch.object(window, "_tray_available", return_value=True):
            window.close()
            app.processEvents()
            assert window.isHidden(), "X with tray should hide main window"
            assert window.tray is not None
            window._tray_activated(QSystemTrayIcon.ActivationReason.DoubleClick)
            app.processEvents()
            assert window.isVisible(), "Tray double-click must restore UI"

        # Simulate Windows Explorer tray unavailable: never disappear.
        with patch.object(window, "_tray_available", return_value=False):
            window.showNormal()
            app.processEvents()
            window.close()
            app.processEvents()
            assert window.isVisible(), "Missing tray must leave taskbar window"
            assert window.isMinimized(), "Missing tray should minimize window"
    finally:
        window.hide()
        window.deleteLater()


def check_busy_login_dialog(app, settings):
    receiver = FakeReceiver(settings)
    dialog = LoginDialog(receiver, settings)
    dialog.email.setText("fake@example.test")
    dialog.password.setText("not-a-real-password")
    dialog.show()
    app.processEvents()
    try:
        dialog.do_login()
        assert dialog.login_button.isEnabled(), (
            "Concurrent startup login must NOT leave manual Login disabled"
        )
        assert "กำลังทำ Login รอบก่อน" in dialog.error_label.text()
    finally:
        dialog.reject()


def check_authenticated_queries():
    class Builder:
        def __init__(self, data):
            self.data = data
        def select(self, *_): return self
        def eq(self, *_): return self
        def order(self, *_ , **kw): return self
        def limit(self, *_): return self
        def execute(self): return SimpleNamespace(data=self.data)

    class Client:
        def __init__(self):
            self.sign_in_calls = 0
        def table(self, name):
            if name == "workspace_members":
                return Builder([{"workspace_id": "offline-workspace", "role": "viewer"}])
            if name == "notification_events":
                return Builder([{"id": 42}])
            raise AssertionError("Unexpected query")
        def rpc(self, name):
            assert name == "get_notify_sources"
            return Builder([{"source_key":"sa_sathorn","source_name":"SA Sathorn"}])
        @property
        def auth(self):
            return self
        def sign_in_with_password(self, creds):
            self.sign_in_calls += 1
            assert creds["email"] == "fake@example.test"
            return SimpleNamespace(
                user=SimpleNamespace(id="offline-user"),
                session=SimpleNamespace(access_token="no-secrets-test-token"),
            )
    client = Client()
    job = _LoginJob("https://example.invalid", "test-key",
                    "fake@example.test", "not-a-password")
    completed = []
    failures = []
    job.signals.done.connect(completed.append)
    job.signals.error.connect(failures.append)
    with patch("notify_receiver.create_client", return_value=client):
        job.run()
    assert not failures, failures
    assert len(completed) == 1, "Password auth AND workspace must yield one result"
    assert completed[0]["workspace_id"] == "offline-workspace"
    assert completed[0]["latest_id"] == 42
    assert client.sign_in_calls == 1, "Never reauthenticate for subsequent queries"


def check_signal_lifetime(app, settings):
    with patch("notify_receiver.load_notify_config",
               return_value=("https://example.invalid", "test-publishable-key")):
        receiver = CentralNotifyReceiver(settings)
    assert receiver.pool.maxThreadCount() == 1, "Shared client must not race refresh"

    class CompletedJob(QRunnable):
        def __init__(self, gate):
            super().__init__()
            self.signals = _Signals()
            self.gate = gate
        def run(self):
            self.gate.wait(2)
            self.signals.done.emit({"message": "delivered"})

    gate = threading.Event()
    job = CompletedJob(gate)
    received = []
    job.signals.done.connect(received.append)
    receiver._start_job(job)
    assert job in receiver._active_jobs, "Job must stay alive until Qt delivers done"
    assert not job.autoDelete(), "Qt must not delete signals before GUI gets them"
    gate.set()
    limit = time.monotonic() + 4
    while time.monotonic() < limit and (not received or receiver._active_jobs):
        app.processEvents()
        time.sleep(0.01)
    assert received == [{"message": "delivered"}], received
    assert not receiver._active_jobs, "Finished jobs must not leak"
    receiver.pool.waitForDone(1500)
    receiver.deleteLater()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    with tempfile.TemporaryDirectory() as folder:
        settings = QSettings(
            str(Path(folder) / "user-settings.ini"), QSettings.Format.IniFormat
        )
        check_main_window_x(app, settings)
        check_busy_login_dialog(app, settings)
        check_authenticated_queries()
        check_signal_lifetime(app, settings)
        settings.sync()
    print("PASS: main X to tray, no-tray minimize, manual Login unblocks, "
          "Supabase post-auth stage and retained worker signals.")


if __name__ == "__main__":
    main()
