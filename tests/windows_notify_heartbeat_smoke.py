"""Regression: Windows startup heartbeat must work after Supabase Auth.

This test exercises the REAL _login_done -> send_heartbeat path, including
the QSettings Windows Run-key inspection, with all network jobs intercepted.
No Supabase requests, credentials, settings, or registry writes are made.
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from notify_receiver import CentralNotifyReceiver, _HeartbeatJob


def test_first_heartbeat_on_windows(app):
    with tempfile.TemporaryDirectory() as folder:
        settings = QSettings(
            str(Path(folder) / "notify-heartbeat.ini"),
            QSettings.Format.IniFormat,
        )
        with patch(
            "notify_receiver.load_notify_config",
            return_value=("https://example.invalid", "test-publishable-key"),
        ):
            receiver = CentralNotifyReceiver(
                settings, app_version="1.5.8"
            )

        queued = []
        states = []
        receiver.status_changed.connect(states.append)

        fake_auth_result = {
            "client": object(),
            "workspace_id": "offline-workspace-id",
            "role": "member",
            "email": "test@example.invalid",
            "session_id": "offline-session-id",
            "latest_id": 0,
            "notify_sources": [],
        }

        # Simulate the frozen EXE state where the original NameError occurred.
        # Reading the Run key is safe and never changes Windows Registry.
        with patch.object(sys, "frozen", True, create=True), patch.object(
            receiver, "_start_job", side_effect=lambda job: queued.append(job)
        ):
            receiver._login_done(
                fake_auth_result,
                password="offline-test-password",
                remember=False,
            )

        try:
            heartbeats = [
                job for job in queued if isinstance(job, _HeartbeatJob)
            ]
            assert len(heartbeats) == 1, (
                "Successful Auth MUST queue the initial device heartbeat"
            )
            first = heartbeats[0]
            assert first.app_version == "1.5.8"
            assert isinstance(first.startup_enabled, bool)
            assert isinstance(first.updater_ready, bool)
            assert receiver._heartbeat_busy
            assert receiver.device_registration_state == "pending"
            assert any("รอ" in text or "ยืนยัน" in text for text in states)

            receiver._heartbeat_done({"active": True})
            assert receiver.device_registration_state == "active"
            assert receiver.last_heartbeat_at
            assert states[-1].startswith("🟢"), states[-1]
        finally:
            receiver.timer.stop()
            receiver.source_timer.stop()
            receiver.heartbeat_timer.stop()
            receiver.login_retry_timer.stop()


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    test_first_heartbeat_on_windows(app)
    print(
        "PASS: frozen Windows QSettings import, "
        "post-Auth first heartbeat queue and confirmed device state."
    )
