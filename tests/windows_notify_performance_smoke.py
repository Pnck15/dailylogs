"""Qt history paging and popup scroll/copy must stay responsive under bursts.

Uses temporary SQLite and no network. Never touches live notification history.
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication

from dailylog_notify import HistoryDialog, NotifyPopup
from notify_history import NotificationHistory


def run(app):
    with tempfile.TemporaryDirectory() as directory:
        with patch("notify_history.app_data_dir", return_value=directory):
            history = NotificationHistory()
            records = [
                {
                    "source": "SA Sathorn",
                    "title": f"Changed {i}",
                    "message": f"วันที่นัดหมาย: 2026-10-14    เวลานัดหมาย: 10.00\nVIN: FAKE{i:05d}",
                    "source_key": "sa_sathorn",
                    "event_created_at": "2026-10-14T03:00:00Z",
                }
                for i in range(950)
            ]
            assert history.add_many(records) == 950
            assert len(history.recent(300)) == 300
            dialog = HistoryDialog(history, source_allowed=lambda *_: True)
            try:
                dialog.show()
                app.processEvents()
                assert len(dialog.visible_rows) == 300
                assert dialog.load_more_button.isEnabled()
                dialog.load_more_button.click()
                app.processEvents()
                assert len(dialog.visible_rows) == 600
                dialog.load_more_button.click()
                app.processEvents()
                assert len(dialog.visible_rows) == 900
                assert dialog.text_area.isReadOnly()
                assert dialog.text_area.verticalScrollBar().maximum() > 0
                assert not hasattr(dialog, "central_button")
                dialog.load_more_button.click()
                app.processEvents()
                assert len(dialog.visible_rows) == 950
                assert not dialog.load_more_button.isEnabled()
                assert len(history.all()) == 950, "Paging must never delete data"
            finally:
                dialog.close()

    message = "\n".join(f"E - ข้อมูลที่เปลี่ยน: ทดสอบ{i}" for i in range(90))
    popup = NotifyPopup("SA Sathorn", message)
    try:
        popup.show()
        app.processEvents()
        assert popup.message_box.verticalScrollBar().maximum() > 0, (
            "Popup must scroll when text exceeds its maximum height"
        )
        assert "background-color: #30343A" in popup.styleSheet(), (
            "Popup must have a dark charcoal background"
        )
        assert "color:#d1d5db" in popup.message_box.toHtml().lower(), (
            "Cell column labels must be light gray"
        )
        assert "color:#ffffff" in popup.message_box.toHtml().lower(), (
            "Cell values must be white"
        )
        assert popup._auto_close_timer.interval() == 22000
        viewport = popup.message_box.viewport()
        popup.eventFilter(viewport, QEvent(QEvent.Type.Enter))
        assert not popup._auto_close_timer.isActive(), (
            "Hover must prevent timeout while selecting or scrolling"
        )
        cursor = popup.message_box.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.movePosition(
            QTextCursor.MoveOperation.Right,
            QTextCursor.MoveMode.KeepAnchor,
            25,
        )
        popup.message_box.setTextCursor(cursor)
        popup.message_box.copy()
        assert app.clipboard().text(), "Copy must return selected popup text"
        popup.message_box.verticalScrollBar().setValue(
            popup.message_box.verticalScrollBar().maximum()
        )
        popup.eventFilter(viewport, QEvent(QEvent.Type.Leave))
        assert popup._auto_close_timer.isActive(), (
            "22-second timeout must resume after pointer leaves"
        )
        assert popup.message_box.verticalScrollBar().value() > 0
    finally:
        popup.dismiss()
        app.processEvents()


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    run(app)
    print("PASS: 950-row history pagination, native scroll and Copy, popup hover pause/resume.")
