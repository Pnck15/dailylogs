"""Offline resilience tests: Supabase is never contacted and no real settings change."""
import os
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from PySide6.QtNetwork import QLocalServer

from dailylog_notify import claim_single_notify_instance
from notify_receiver import (
    CentralNotifyReceiver, LOGIN_RETRY_INITIAL_MS,
    LOGIN_RETRY_MAX_MS,
)


def run_receiver_tests():
    with tempfile.TemporaryDirectory() as folder:
        settings = QSettings(str(Path(folder) / "notify-tests.ini"), QSettings.Format.IniFormat)
        settings.setValue("central/email", "receiver@example.test")
        settings.setValue("central/password", "test-only-in-memory")
        settings.sync()
        with patch("notify_receiver.load_notify_config",
                   return_value=("https://example.invalid", "test-publishable-key")):
            receiver = CentralNotifyReceiver(settings, app_version="1.5.6")
        status = []
        login_errors = []
        receiver.status_changed.connect(status.append)
        receiver.login_failed.connect(login_errors.append)

        # Simulate the callback from a saved-credentials startup Login that
        # failed temporarily; the real network is never contacted here.
        receiver._login_busy = True
        receiver._login_was_automatic = True
        receiver._login_error("Connection timed out")
        assert receiver.login_retry_timer.isActive()
        assert receiver.login_retry_timer.interval() == LOGIN_RETRY_INITIAL_MS
        assert not login_errors
        assert settings.value("central/password") == "test-only-in-memory"
        assert any("ลองใหม่" in text for text in status)

        receiver.login_retry_timer.stop()
        receiver._login_busy = True
        receiver._login_was_automatic = True
        receiver._login_error("ConnectTimeout")
        assert receiver.login_retry_timer.isActive()
        assert receiver.login_retry_timer.interval() == LOGIN_RETRY_INITIAL_MS * 2
        assert receiver.login_retry_timer.interval() <= LOGIN_RETRY_MAX_MS

        # Invalid credentials must not be retried (avoid auth rate limiting).
        receiver.login_retry_timer.stop()
        receiver._login_busy = True
        receiver._login_was_automatic = True
        receiver._login_error("Invalid login credentials")
        assert not receiver.login_retry_timer.isActive()
        assert login_errors, "Permanent login errors must be shown to users"

        receiver.client = object()
        receiver.workspace_id = "test-workspace"
        receiver.timer.start()
        status.clear()
        for _ in range(2):
            receiver._poll_error("Network timeout")
        assert receiver.timer.isActive(), "Transient polling errors must retry"
        assert receiver._poll_failures == 2
        assert status[-1].startswith("🟡")
        receiver._poll_error("Network timeout")
        assert receiver._poll_failures == 3
        assert status[-1].startswith("🔴")
        # Test direct recovery to a healthy state without real events.
        receiver._poll_done([])
        assert receiver._poll_failures == 0
        assert status[-1].startswith("🟢")

        # Invalid or revoked access is not silently replaced by a new
        # password session; a real user/admin must resolve the session.
        receiver._poll_error("401 Unauthorized")
        assert not receiver.timer.isActive()
        assert "Session" in status[-1]
        assert not receiver.login_retry_timer.isActive()

        # An explicit Admin revoke must stop retries and clear the saved
        # password as the old security policy requires.
        receiver.client = None
        receiver.workspace_id = ""
        receiver.login_retry_timer.stop()
        receiver._handle_session_revoked()
        assert not receiver.login_retry_timer.isActive()
        assert receiver._session_revoked is True
        assert not receiver.has_saved_credentials()
        settings.sync()


def run_single_instance_tests():
    name = "DailyLogNotify-test-" + str(uuid.uuid4())
    server = claim_single_notify_instance(instance_name=name)
    assert server is not None and server.isListening()
    try:
        startup = claim_single_notify_instance(startup=True, instance_name=name)
        assert startup is None, "Windows startup must not create a duplicate process"
        manual = claim_single_notify_instance(startup=False, instance_name=name)
        assert manual is None, "Double click must reuse the already-running tray process"
        assert server.hasPendingConnections() or server.waitForNewConnection(500)
    finally:
        server.close()
        server._notify_owner_lock.unlock()
        QLocalServer.removeServer(name)


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    run_receiver_tests()
    run_single_instance_tests()
    print("PASS: saved login retry, poll recovery, admin revoke, one tray instance.")
