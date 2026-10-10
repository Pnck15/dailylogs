"""Run with QT_QPA_PLATFORM=offscreen after Windows build installs PySide6."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from dailylog_notify import NotifyPopup, clean_sa_notification_message


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    popup = NotifyPopup(
        "SA Sathorn - นัดหมายอีก 10 นาที",
        (
            "เวลานัดหมาย: 13:30\n"
            "Merged D: D89:D97\n"
            "C - ลำดับ 序号: 7\n"
            "E - ลูกค้า: ตัวอย่าง"
        ),
    )
    try:
        timers = popup.findChildren(QTimer)
        assert len(timers) == 1, "Expected one auto-close timer"
        timer = timers[0]
        assert timer.interval() == 180000, timer.interval()
        assert timer.isSingleShot()
        assert timer.isActive()

        red_x = popup.findChild(QPushButton, "notifyPopupCloseButton")
        assert red_x is not None
        assert red_x.text() == "✕"
        assert "background-color: #DC2626" in red_x.styleSheet()

        label_text = [label.text() for label in popup.findChildren(QLabel)]
        assert any("ปิดอัตโนมัติใน 3 นาที" in text for text in label_text)
        assert not any("Ctrl+C" in text for text in label_text)

        visible = clean_sa_notification_message(popup.message_box.toPlainText())
        assert "Merged D:" not in visible
        assert "ลำดับ 序号:" not in visible
        assert "ลูกค้า: ตัวอย่าง" in visible

        assert any(b.text() == "Copy All" for b in popup.findChildren(QPushButton))
        assert any("ประวัติแจ้งเตือน" in b.text()
                   for b in popup.findChildren(QPushButton))
    finally:
        popup.close()
        app.processEvents()
    print("PASS: NotifyPopup real Qt close button, 180000 ms, labels and SA cleaner.")


if __name__ == "__main__":
    main()
