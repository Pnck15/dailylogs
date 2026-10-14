"""Real Windows Qt history copy/export/confirm-delete with temporary SQLite."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QTextEdit
from dailylog_notify import HistoryDialog
from notify_history import NotificationHistory


def run_history_smoke(app):
    with tempfile.TemporaryDirectory() as folder:
        with patch("notify_history.app_data_dir", return_value=folder):
            history = NotificationHistory()
            history.add(
                "SA Sathorn", "Edit", "วันที่นัดหมาย: 2026-10-12\nเวลา: 13:30",
                source_key="sa_sathorn",
            )
            history.add(
                "Sale Deli Sathorn", "Hidden", "must stay hidden from export",
                source_key="sale_sathorn",
            )
            window = HistoryDialog(
                history,
                source_allowed=lambda source, key: key == "sa_sathorn",
            )
            try:
                window.show()
                app.processEvents()
                assert len(window.visible_rows) == 1
                assert not hasattr(window, "central_button"), (
                    "History must not include a global purge button"
                )
                assert isinstance(window.text_area, QTextEdit)
                assert window.text_area.isReadOnly()
                cursor = window.text_area.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.Start)
                cursor.movePosition(
                    QTextCursor.MoveOperation.Right,
                    QTextCursor.MoveMode.KeepAnchor, 11,
                )
                window.text_area.setTextCursor(cursor)
                window.text_area.copy()
                assert app.clipboard().text(), "Text selection and Copy must work"
                menu = window.text_area.createStandardContextMenu()
                assert menu is not None
                menu.deleteLater()

                exported = Path(folder) / "history.xlsx"
                with patch(
                    "dailylog_notify.QFileDialog.getSaveFileName",
                    return_value=(str(exported), "Excel Workbook (*.xlsx)")
                ), patch("dailylog_notify.QMessageBox.information"):
                    window.export_excel()
                assert exported.exists()
                with ZipFile(exported) as zip_file:
                    sheet = zip_file.read("xl/worksheets/sheet1.xml").decode()
                    assert "SA Sathorn" in sheet
                    assert "must stay hidden from export" not in sheet

                # Cancel must preserve everything, including hidden sources.
                with patch(
                    "dailylog_notify.QInputDialog.getItem",
                    return_value=("ล้างทั้งหมด", True),
                ), patch("dailylog_notify.QMessageBox.question",
                         return_value=QMessageBox.StandardButton.No):
                    window.clear_history()
                assert len(history.all()) == 2
                assert len(window.visible_rows) == 1

                # Yes deletes only this PC's SQLite rows, preserving schema.
                with patch(
                    "dailylog_notify.QInputDialog.getItem",
                    return_value=("ล้างทั้งหมด", True),
                ), patch("dailylog_notify.QMessageBox.question",
                         return_value=QMessageBox.StandardButton.Yes):
                    window.clear_history()
                assert history.all() == []
                assert window.visible_rows == []
                assert exported.exists(), "Export file must not be deleted"
                with patch("notify_history.app_data_dir", return_value=folder):
                    assert NotificationHistory().all() == []

                assert not hasattr(window, "central_button")
                assert "ต้องการให้ทุกเครื่องหายพร้อมกัน" not in (
                    " ".join(
                        label.text() for label in window.findChildren(QLabel)
                    )
                )
            finally:
                window.close()


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    run_history_smoke(app)
    print("PASS: selectable/copyable history, Excel export, confirmed local clear and Source filtering.")
