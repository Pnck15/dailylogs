"""Modeless, paginated Notification Logs viewer for DailyLog.exe.

Shows live Central notification history (100 records/page). During an Internet
outage, the existing in-process notification feed remains readable. No history
deletion, credential storage or Daily Logs mutations happen here.
"""
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QTextEdit, QVBoxLayout, QWidget,
)

PAGE_SIZE = 100


def display_event_time(raw):
    """Render Central timestamps in the Windows user's local timezone."""
    source = str(raw or "").strip()
    if not source:
        return "-"
    try:
        stamp = datetime.fromisoformat(source.replace("Z", "+00:00"))
        if stamp.tzinfo is not None:
            stamp = stamp.astimezone()
        return stamp.strftime("%d/%m/%Y %H:%M:%S")
    except (TypeError, ValueError):
        return source


class NotificationLogsDialog(QDialog):
    def __init__(self, page_loader, recent_notifications=(), parent=None):
        super().__init__(parent)
        self.page_loader = page_loader
        self.recent_notifications = list(recent_notifications or [])
        self.page = 0
        self.pending = False
        self.central_rows = []
        self.setWindowTitle("DailyLog — Notification Logs ทั้งหมด")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setModal(False)
        self.resize(780, 550)
        layout = QVBoxLayout(self)

        note = QLabel(
            "รายการแจ้งเตือนจาก Central • คลิกรายการเพื่ออ่านรายละเอียด "
            "เลือกข้อความ/คลิกขวาเพื่อ Copy ได้ "
            "• ประวัติ Daily Logs ของปฏิทินเป็นข้อมูลคนละส่วน"
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        panels = QHBoxLayout()
        self.items = QListWidget(self)
        self.items.setObjectName("allNotificationLogsItems")
        self.items.setWordWrap(True)
        self.items.currentItemChanged.connect(self._selected)
        panels.addWidget(self.items, 2)
        self.detail = QTextEdit(self)
        self.detail.setObjectName("allNotificationLogsDetails")
        self.detail.setReadOnly(True)
        self.detail.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.detail.setContextMenuPolicy(
            Qt.ContextMenuPolicy.DefaultContextMenu
        )
        panels.addWidget(self.detail, 3)
        layout.addLayout(panels, 1)

        self.status = QLabel("กำลังโหลดประวัติแจ้งเตือน...")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.previous = QPushButton("◀ ก่อนหน้า")
        self.previous.setObjectName("notificationHistoryPrevious")
        self.next = QPushButton("ถัดไป ▶")
        self.next.setObjectName("notificationHistoryNext")
        self.refresh = QPushButton("Refresh")
        close = QPushButton("Close")
        self.previous.clicked.connect(lambda: self.open_page(self.page - 1))
        self.next.clicked.connect(lambda: self.open_page(self.page + 1))
        self.refresh.clicked.connect(lambda: self.open_page(self.page))
        close.clicked.connect(self.close)
        for button in (self.previous, self.next, self.refresh):
            buttons.addWidget(button)
        buttons.addStretch()
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.show_recent_cache()
        self.open_page(0)

    def show_recent_cache(self):
        """Readable fallback after a failed Central fetch, not a full history."""
        rows = []
        for entry in reversed(self.recent_notifications[-50:]):
            stamp = getattr(entry, "timestamp", None)
            rows.append({
                "source": str(getattr(entry, "sheet", "") or "DailyLog"),
                "title": str(getattr(entry, "title", "") or ""),
                "message": str(getattr(entry, "message", "") or ""),
                "notification_type": str(getattr(entry, "notification_type", "") or ""),
                "created_at": stamp.isoformat() if hasattr(stamp, "isoformat") else "",
            })
        self._render_rows(rows)
        if rows:
            self.status.setText(
                f"แสดง {len(rows)} รายการล่าสุดในหน่วยความจำของโปรแกรม "
                "(ถ้าไม่มีอินเทอร์เน็ต ยังเปิดอ่านและ Copy ได้)"
            )

    def open_page(self, page):
        if page < 0 or self.pending:
            return
        self.pending = True
        self._requested_page = int(page)
        self.status.setText(
            f"กำลังโหลด Notification Logs หน้า {page + 1} จาก Central..."
        )
        self.previous.setEnabled(False)
        self.next.setEnabled(False)
        self.refresh.setEnabled(False)
        try:
            self.page_loader(self, int(page), PAGE_SIZE)
        except Exception as error:
            self.set_error(str(error))

    def set_rows(self, rows):
        self.pending = False
        self.page = self._requested_page
        self.central_rows = [
            row for row in (rows or [])
            if isinstance(row, dict)
            and row.get("notification_type") != "history_purge"
        ]
        self._render_rows(self.central_rows)
        self.previous.setEnabled(self.page > 0)
        self.next.setEnabled(len(rows or []) == PAGE_SIZE)
        self.refresh.setEnabled(True)
        self.status.setText(
            f"Central Notification Logs หน้า {self.page + 1} — "
            f"{len(self.central_rows)} รายการ "
            "• กดหน้าถัดไปเพื่อดูรายการเก่ากว่า"
        )

    def set_error(self, message):
        self.pending = False
        self.previous.setEnabled(self.page > 0)
        self.next.setEnabled(False)
        self.refresh.setEnabled(True)
        # Leave whatever the user already sees on screen intact.
        self.status.setText(
            "เชื่อมต่อ Central ไม่สำเร็จ / อินเทอร์เน็ตขาด: "
            + str(message)[:200]
            + " • รายการที่โหลดก่อนหน้านี้ยังเลือกอ่านและ Copy ได้"
        )

    def _render_rows(self, rows):
        self.items.clear()
        self.detail.clear()
        for row in rows:
            title = str(row.get("title") or "Notification")
            source = str(row.get("source") or "Central")
            stamp = display_event_time(row.get("created_at"))
            item = QListWidgetItem(f"{stamp}\n[{source}] {title}")
            item.setData(Qt.ItemDataRole.UserRole, row)
            self.items.addItem(item)
        if self.items.count():
            self.items.setCurrentRow(0)
        else:
            self.detail.setPlainText("ไม่มีประวัติในหน้านี้")

    def _selected(self, current, _previous=None):
        if current is None:
            return
        row = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(row, dict):
            return
        self.detail.setPlainText(
            f"วันเวลา: {display_event_time(row.get('created_at'))}\n"
            f"Source: {row.get('source') or '-'}\n"
            f"ประเภท: {row.get('notification_type') or '-'}\n"
            f"หัวข้อ: {row.get('title') or '-'}\n\n"
            f"{row.get('message') or ''}"
        )
