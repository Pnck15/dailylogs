"""Offline cross-PC purge and source-copy safety regression.

Test only synthetic Qt events / temporary SQLite. Never purge Supabase.
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from dailylog_notify import clean_sa_notification_message, popup_content_html
from notify_history import NotificationHistory
from notify_receiver import CentralNotifyReceiver


def verify_purge(app):
    bangkok = timezone(timedelta(hours=7))
    with tempfile.TemporaryDirectory() as folder:
        with patch("notify_history.app_data_dir", return_value=folder):
            history = NotificationHistory()
            rows = [
                ("Yesterday", "2026-10-11T17:30:00+07:00"),
                ("Four days old", "2026-10-08T09:30:00+07:00"),
                ("Today", "2026-10-12T12:00:00+07:00"),
                ("UTC old", "2026-10-02T02:00:00Z"),
            ]
            for title, stamp in rows:
                history.add(
                    "SA Sathorn", title, "example",
                    source_key="sa_sathorn", event_created_at=stamp
                )
            yesterday = datetime(2026, 10, 11, tzinfo=bangkok)
            today = datetime(2026, 10, 12, tzinfo=bangkok)
            count = history.clear_period(
                yesterday.isoformat(), today.isoformat()
            )
            assert count == 1
            assert {row["title"] for row in history.all()} == {
                "Four days old", "Today", "UTC old"
            }
            week_start = today - timedelta(days=7)
            assert history.clear_period(
                week_start.isoformat(), today.isoformat()
            ) == 1
            assert {row["title"] for row in history.all()} == {
                "Today", "UTC old"
            }
            assert history.clear_period(None, datetime(
                2026, 10, 13, tzinfo=bangkok
            ).isoformat()) == 2
            assert history.all() == []

        settings = QSettings(
            str(Path(folder) / "qt.ini"), QSettings.Format.IniFormat
        )
        with patch(
            "notify_receiver.load_notify_config",
            return_value=("https://example.invalid", "test-key"),
        ):
            receiver = CentralNotifyReceiver(settings)
        receiver.workspace_id = "offline-workspace"
        receiver.last_id = 15
        markers = []
        normal = []
        receiver.history_purge.connect(markers.append)
        receiver.event.connect(lambda *args: normal.append(args))
        data = {
            "version": 1, "scope": "all", "start": None,
            "end": "2026-10-12T10:00:00Z", "deleted_events": 123,
        }
        receiver._poll_done([{
            "id": 16, "source": "DailyLog Central",
            "source_key": "__central_history_purge__",
            "notification_type": "history_purge",
            "title": "Central History Purged",
            "created_at": "2026-10-12T10:00:01Z",
            "message": json.dumps(data),
        }])
        assert len(markers) == 1
        assert markers[0]["scope"] == "all"
        assert normal == [], "Never show cleanup marker as a popup"
        assert receiver.last_id == 16, "Continue cursor after cleanup"
        assert settings.value(
            "central/offline-workspace/last_event_id"
        ) == 16
        # Global deletion must be denied to Member accounts even if they
        # know the RPC name, and be queued only for an Admin.
        receiver.client = object()
        receiver.role = "member"
        failures = []
        receiver.global_purge_error.connect(failures.append)
        assert receiver.purge_notification_history("all") is False
        assert "Admin" in failures[-1]
        receiver.role = "admin"
        tasks = []
        with patch.object(receiver, "_start_job", side_effect=tasks.append):
            assert receiver.purge_notification_history("last_7_days") is True
        assert len(tasks) == 1
        assert tasks[0].scope == "last_7_days"

        receiver.timer.stop()
        receiver.source_timer.stop()
        receiver.heartbeat_timer.stop()
        receiver.login_retry_timer.stop()

    msg = clean_sa_notification_message(
        "วันที่นัดหมาย (Column D): 2026-10-12\n"
        "เวลานัดหมาย: 13:30\n"
        "E - ชื่อลูกค้า: ตัวอย่าง\n"
        "Merged D: D89:D97\nC - ลำดับ: 5"
    )
    assert "(Column D)" not in msg
    assert "วันที่นัดหมาย: 2026-10-12    เวลานัดหมาย: 13:30" in msg
    assert "Merged D:" not in msg
    rendered = popup_content_html(msg)
    assert "color:#FFFFFF" in rendered
    assert "background-color:#30343A" in rendered
    assert rendered.count('<span style="color:#D1D5DB;">') >= 2, (
        "Date and time column labels must both be light gray"
    )
    assert rendered.count('<span style="color:#FFFFFF;font-weight:600;">') >= 2, (
        "Date and time values must both be white"
    )
    assert "ตัวอย่าง" in rendered
    assert "<script>" not in popup_content_html("<script>do not execute</script>")
    sql = Path(__file__).resolve().parents[1] / "supabase/central_notification_retention.sql"
    source = sql.read_text(encoding="utf-8")
    assert "Active Admin session required" in source
    assert "Admin only" in source
    assert "IF v_scope NOT IN" in source
    assert "REVOKE ALL ON FUNCTION" in source


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    verify_purge(app)
    print("PASS: date-scoped local purge, Central marker sync, no popup, date label and white cell values.")
