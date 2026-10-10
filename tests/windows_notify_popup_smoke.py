"""Exercise real Qt clicks, timer, source filtering and popup cleanup."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from dailylog_notify import (
    HistoryDialog, NotifyApp, NotifyPopup, clean_sa_notification_message,
)


class SpyHistory:
    def __init__(self):
        self.items = []

    def add(self, source, title, message, source_key=""):
        self.items.append(dict(
            source=source, title=title, message=message,
            source_key=source_key,
        ))

    def all(self):
        return list(self.items)


class FakeNotifyApp:
    # Reuse the real production source eligibility and notify methods.
    _source_allowed = NotifyApp._source_allowed
    notify = NotifyApp.notify

    def __init__(self):
        self.selected = {"sa_sathorn"}
        self.history = SpyHistory()
        self.popups = []
        self.source_options = [
            {
                "key": "sa_sathorn", "label": "SA Sathorn",
                "aliases": {"SA Sathorn", "SA Notify"},
            },
            {
                "key": "sale_sathorn", "label": "Sale Deli Sathorn",
                "aliases": {"Sale Deli Sathorn"},
            },
        ]

    def _source_filter_configured(self):
        return True

    def _selected_source_keys(self):
        return set(self.selected)

    def _available_source_keys(self):
        return {"sa_sathorn", "sale_sathorn"}

    def _show_notify_popup(self, title, message):
        self.popups.append((title, message))


def test_popup(app):
    popup = NotifyPopup(
        "SA Sathorn - นัดหมายอีก 10 นาที",
        (
            "เวลานัดหมาย: 13:30\n"
            "Merged D: D89:D97\n"
            "C - ลำดับ 序号: 7\n"
            "E - ลูกค้า: ตัวอย่าง"
        ),
    )
    timers = popup.findChildren(QTimer)
    assert len(timers) == 1
    timer = timers[0]
    assert timer.interval() == 20000, timer.interval()
    assert timer.isSingleShot() and timer.isActive()

    red_x = popup.findChild(QPushButton, "notifyPopupCloseButton")
    assert red_x is not None
    assert red_x.text() == "✕"
    assert "background-color: #DC2626" in red_x.styleSheet()

    labels = [label.text() for label in popup.findChildren(QLabel)]
    assert any("ปิดอัตโนมัติใน 20 วินาที" in text for text in labels)
    assert not any("Ctrl+C" in text for text in labels)
    assert not any("3 นาที" in text for text in labels)

    visible = clean_sa_notification_message(
        popup.message_box.toPlainText()
    )
    assert "Merged D:" not in visible
    assert "ลำดับ 序号:" not in visible
    assert "ลูกค้า: ตัวอย่าง" in visible

    assert any(b.text() == "Copy All" for b in popup.findChildren(QPushButton))
    assert any("ประวัติแจ้งเตือน" in b.text()
               for b in popup.findChildren(QPushButton))

    closed = []
    popup.finished.connect(lambda code: closed.append(code))
    popup.show()
    app.processEvents()
    assert red_x.isVisible() and red_x.isEnabled()
    # Real mouse click, not a direct call to popup.close().
    QTest.mouseClick(red_x, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert len(closed) == 1, "X click must emit finished immediately"

    auto = NotifyPopup("Timer test", "test data")
    auto_closed = []
    auto.finished.connect(lambda code: auto_closed.append(code))
    auto.show()
    app.processEvents()
    auto._auto_close_timer.timeout.emit()
    app.processEvents()
    assert len(auto_closed) == 1, "Timer timeout must dismiss popup"


def test_source_only_history():
    client = FakeNotifyApp()
    client.notify(
        "Sale Deli Sathorn", "Sale event", "Hidden data",
        source_key="sale_sathorn",
    )
    assert len(client.history.items) == 0
    assert not client.popups, "Unselected sources cannot create a popup"

    client.notify(
        "SA Sathorn", "SA event",
        "Merged D: D89:D97\nC - ลำดับ 序号: 7\nE - ลูกค้า: Test",
        show_popup=False,
        source_key="sa_sathorn",
    )
    assert len(client.history.items) == 1
    assert client.history.items[0]["source_key"] == "sa_sathorn"
    assert "Merged D:" not in client.history.items[0]["message"]
    assert not client.popups

    client.history.items.append({
        "source": "Sale Deli Sathorn",
        "source_key": "sale_sathorn",
        "title": "Old sale event",
        "message": "Prior saved entry",
    })
    client.history.items.append({
        "source": "SA Notify",
        "source_key": "",
        "title": "Old SA event",
        "message": "Legacy source key",
    })
    window = HistoryDialog(
        client.history, source_allowed=client._source_allowed
    )
    assert window.list_widget.count() == 2, (
        "SA selection includes SA legacy events, not Sale"
    )

    client.selected = {"sale_sathorn"}
    window.reload()
    assert window.list_widget.count() == 1, (
        "History must reflect the currently checked source"
    )
    client.selected.clear()
    window.reload()
    assert window.list_widget.count() == 0
    # Records remain unchanged: source toggles must never erase old history.
    assert len(client.history.items) == 3
    window.close()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    test_popup(app)
    test_source_only_history()
    print(
        "PASS: real X click, 20-sec auto-dismiss, "
        "checked-source-only history and non-destructive filtering"
    )


if __name__ == "__main__":
    main()
