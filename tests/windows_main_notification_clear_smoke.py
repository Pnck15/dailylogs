"""Windows GUI + persistence tests for per-PC Main Notification cleanup.

No database network calls, no destructive SQL and no user settings changes.
Tests the exact UI handler and the paginated Central history display.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QListWidget, QMessageBox, QSpinBox, QWidget,
)
from dailylog_notification_visibility import (
    LocalNotificationVisibility, to_utc, window_for,
)
from dailylog_notification_history import NotificationLogsDialog
from main import DailyLog
from sheet_monitor import Notification, NotificationPresenter


def test_retention_math_and_reload():
    fixed = datetime(2026, 10, 15, 10, 30, tzinfo=timezone.utc)
    start, end = window_for("recent", 7, fixed)
    assert start == fixed - timedelta(days=7)
    assert end == fixed
    assert window_for("older", 30, fixed) == (
        None, fixed - timedelta(days=30)
    )
    assert window_for("all", now=fixed) == (None, fixed)
    for days in (-1, 0, 3651, "abc"):
        try:
            window_for("recent", days, fixed)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid retention was allowed")

    with tempfile.TemporaryDirectory() as folder:
        config = str(Path(folder) / "local.ini")
        settings = QSettings(config, QSettings.Format.IniFormat)
        model = LocalNotificationVisibility(settings)
        assert model.visible(fixed - timedelta(days=9))
        assert model.visible(fixed - timedelta(days=2))
        model.hide("recent", 7, now=fixed)
        assert not model.visible(fixed - timedelta(days=2))
        assert model.visible(fixed - timedelta(days=9))
        assert model.visible(fixed + timedelta(seconds=1))

        reloaded = LocalNotificationVisibility(
            QSettings(config, QSettings.Format.IniFormat)
        )
        assert not reloaded.visible(fixed - timedelta(days=2))
        assert reloaded.visible(fixed + timedelta(seconds=1))
        reloaded.hide("older", 7, now=fixed)
        assert not reloaded.visible(fixed - timedelta(days=9))
        assert reloaded.visible(fixed + timedelta(seconds=1))
        assert to_utc("2026-10-15T17:30:00+07:00") == fixed


def test_viewer_filters_without_cloud_deletion(app):
    now = datetime(2026, 10, 15, 10, 30, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as folder:
        model = LocalNotificationVisibility(QSettings(
            str(Path(folder) / "history.ini"), QSettings.Format.IniFormat
        ))
        requests = []
        viewer = NotificationLogsDialog(
            page_loader=lambda dialog, page, size: requests.append((dialog, page, size)),
            visibility_filter=model.visible,
            recent_notifications=[],
        )
        try:
            viewer.show()
            app.processEvents()
            assert requests and requests[0][1] == 0
            assert viewer.local_clear_button.objectName() == "clearMainNotificationHistoryButton"
            rows = [
                {"id": 1, "created_at": (now - timedelta(days=2)).isoformat(),
                 "title": "Old alert", "source": "SA"},
                {"id": 2, "created_at": (now + timedelta(seconds=2)).isoformat(),
                 "title": "New alert", "source": "SA"},
            ]
            viewer.set_rows(rows)
            assert viewer.items.count() == 2
            model.hide("recent", 7, now=now)
            viewer.refresh_local_visibility()
            assert viewer.items.count() == 1
            assert viewer.items.item(0).text().endswith("New alert")
            viewer.open_page(0)
            viewer.set_rows(rows)
            assert viewer.items.count() == 1, (
                "Refresh from Central must not resurrect hidden notifications"
            )
        finally:
            viewer.close()


class OfflineCloud:
    def __init__(self):
        self.calls = []

    def call(self, name, *args):
        self.calls.append((name, *args))
        raise AssertionError("Local notification clear must never touch CloudDB")


def test_main_clear_handler_and_future_event(app):
    now = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory() as folder:
        settings = QSettings(
            str(Path(folder) / "main.ini"), QSettings.Format.IniFormat
        )
        owner = DailyLog.__new__(DailyLog)
        QWidget.__init__(owner)
        owner.settings = settings
        owner.local_notification_visibility = LocalNotificationVisibility(settings)
        owner._notification_history_dialog = None
        owner.notification_list = QListWidget(owner)
        owner.notification_presenter = NotificationPresenter(owner)
        owner.notification_presenter.set_central_list(owner.notification_list)
        owner.sale_notifications = []
        owner.cloud = OfflineCloud()
        owner._main_event_last_id = 0

        old = Notification(
            "Old event", "Prior alert", "edit",
            timestamp=(now - timedelta(days=3)).astimezone()
        )
        current = Notification(
            "Fresh event", "Current alert", "new",
            timestamp=now.astimezone()
        )
        owner.notification_presenter.notifications = [old, current]
        for item in (old, current):
            owner.notification_presenter.add_to_central_feed(item)

        def choose_recent(dialog):
            mode = dialog.findChild(QComboBox, "localNotificationClearMode")
            days = dialog.findChild(QSpinBox, "localNotificationClearDays")
            assert mode is not None and days is not None
            assert {mode.itemData(i) for i in range(mode.count())} == {
                "recent", "older", "all"
            }
            mode.setCurrentIndex(0)
            days.setValue(7)
            return QDialog.DialogCode.Accepted

        # Declined confirmation must not change any local/Central state.
        with patch("main.QDialog.exec", choose_recent), patch(
            "main.QMessageBox.question",
            return_value=QMessageBox.StandardButton.No
        ), patch("main.QMessageBox.information"):
            owner.clear_local_notification_history()
        assert len(owner.notification_presenter.notifications) == 2
        assert owner.local_notification_visibility.windows == []

        with patch("main.QDialog.exec", choose_recent), patch(
            "main.QMessageBox.question",
            return_value=QMessageBox.StandardButton.Yes
        ), patch("main.QMessageBox.information"):
            owner.clear_local_notification_history()
        assert owner.notification_presenter.notifications == []
        assert owner.notification_list.count() == 0
        assert owner.cloud.calls == []

        # Receiving an old event after clear never shows it again.
        owner._process_main_notification_events([{
            "id": 1, "source": "SA",
            "title": "Already cleared event",
            "message": "hidden", "created_at": (
                now - timedelta(days=1)
            ).isoformat(), "notification_type": "edit",
        }])
        assert owner._main_event_last_id == 1
        assert owner.notification_list.count() == 0
        assert not owner.cloud.calls

        # New incoming events remain eligible after cleanup.
        fresh = (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat()
        seen = []
        owner.add_sale_notification = lambda *a, **kw: seen.append((a, kw))
        owner._process_main_notification_events([{
            "id": 2, "source": "SA", "title": "Future",
            "message": "visible", "created_at": fresh,
            "notification_type": "new",
        }])
        assert len(seen) == 1
        assert seen[0][1]["event_created_at"] == fresh
        assert owner._main_event_last_id == 2
        assert owner.cloud.calls == []
        owner.hide()
        owner.deleteLater()


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    test_retention_math_and_reload()
    test_viewer_filters_without_cloud_deletion(app)
    test_main_clear_handler_and_future_event(app)
    print("PASS: custom day-count, confirmation, local persistence, paginated filtering and no CloudDB writes.")
