"""Presentation-only notification UI for DailyLog.

Important architecture rule:
    sheet_monitor.py never calls Google Apps Script.
    sale_api_monitor.py is the only GAS client used by main.py.

This module only renders notification history/list items and popups.
"""
from datetime import datetime

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


class Notification:
    def __init__(
        self,
        title,
        message,
        notification_type="info",
        sheet="",
        row=None,
        column="",
        timestamp=None,
    ):
        self.title = str(title or "")
        self.message = str(message or "")
        self.notification_type = str(notification_type or "info")
        self.sheet = str(sheet or "")
        self.row = row
        self.column = str(column or "")
        self.timestamp = timestamp or datetime.now()


class NotificationPopup(QDialog):
    """Display a single notification. No network access lives here."""

    def __init__(self, notification, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.notification = notification
        self.setWindowTitle(notification.title or "DailyLog Notification")
        self.setModal(False)
        self.setAttribute(
            Qt.WidgetAttribute.WA_DeleteOnClose,
            True,
        )
        self.setMinimumWidth(260)
        self._build_ui()

    def _build_ui(self):
        icons = {
            "new": "🟢",
            "edit": "🟡",
            "delete": "🔴",
            "due": "🚗",
            "info": "🔔",
        }
        icon = icons.get(
            self.notification.notification_type,
            "🔔",
        )

        layout = QVBoxLayout(self)

        title = QLabel(
            f"{icon} <b>{self.notification.title}</b>"
        )
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setWordWrap(True)
        layout.addWidget(title)

        time_label = QLabel(
            self.notification.timestamp.strftime("%H:%M:%S")
        )
        time_label.setStyleSheet(
            "color: #6B7280; font-size: 11px;"
        )
        layout.addWidget(time_label)

        message = QLabel(
            self.notification.message
        )
        message.setWordWrap(True)
        message.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        layout.addWidget(message)

        details = []
        if self.notification.sheet:
            details.append(f"Sheet: {self.notification.sheet}")
        if self.notification.row not in (None, ""):
            details.append(f"Row: {self.notification.row}")
        if self.notification.column:
            details.append(f"Column: {self.notification.column}")

        if details:
            detail_label = QLabel(" | ".join(details))
            detail_label.setStyleSheet(
                "color: #6B7280; font-size: 10px;"
            )
            detail_label.setWordWrap(True)
            layout.addWidget(detail_label)

        buttons = QHBoxLayout()
        buttons.addStretch()
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)


class NotificationPresenter(QObject):
    """Own only the visual notification layer.

    Data acquisition must be performed elsewhere. main.py feeds already-parsed
    events here after SaleAPIMonitor returns.
    """

    notification_received = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_widget = parent
        self.central_list = None
        self.notifications = []
        self.popup_queue = []
        self.current_popup = None

    def set_central_list(self, list_widget):
        self.central_list = list_widget

    def present(
        self,
        title,
        message,
        notification_type="info",
        show_popup=True,
        sheet="",
        row=None,
        column="",
        max_items=50,
    ):
        notification = Notification(
            title=title,
            message=message,
            notification_type=notification_type,
            sheet=sheet,
            row=row,
            column=column,
        )

        self.notifications.append(notification)
        if len(self.notifications) > max_items:
            self.notifications = self.notifications[-max_items:]

        self.add_to_central_feed(
            notification,
            max_items=max_items,
        )

        if show_popup:
            self.show_popup(notification)

        self.notification_received.emit(notification)
        return notification

    def add_to_central_feed(
        self,
        notification,
        max_items=50,
    ):
        if self.central_list is None:
            return

        icons = {
            "new": "🟢",
            "edit": "🟡",
            "delete": "🔴",
            "due": "🚗",
            "info": "🔔",
        }
        icon = icons.get(
            notification.notification_type,
            "🔔",
        )
        time_text = notification.timestamp.strftime("%H:%M:%S")

        item = QListWidgetItem(
            f"{icon} {time_text}  {notification.title}\n"
            f"    {notification.message}"
        )
        item.setData(
            Qt.ItemDataRole.UserRole,
            notification,
        )
        self.central_list.insertItem(0, item)

        while self.central_list.count() > max_items:
            self.central_list.takeItem(
                self.central_list.count() - 1
            )

    def show_popup(self, notification):
        if self.current_popup is not None:
            self.popup_queue.append(notification)
            return

        popup = NotificationPopup(
            notification,
            self.parent_widget,
        )
        self.current_popup = popup

        popup.finished.connect(
            lambda _result=0: self._popup_closed()
        )

        popup.adjustSize()

        parent = self.parent_widget
        if parent is not None:
            try:
                pos = parent.mapToGlobal(
                    parent.rect().topRight()
                )
                popup.move(
                    pos.x() - popup.width() - 12,
                    pos.y() + 45,
                )
            except Exception:
                pass

        popup.show()
        popup.raise_()

    def _popup_closed(self):
        self.current_popup = None

        if self.popup_queue:
            self.show_popup(
                self.popup_queue.pop(0)
            )


# Backward-compatible name for code that imported NotificationManager.
NotificationManager = NotificationPresenter


class MainCentralNoti(QFrame):
    """Reusable notification list widget. Still presentation-only."""

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)

        title = QLabel("Main Central Noti")
        title.setStyleSheet(
            "font-size: 18px; font-weight: bold;"
        )
        layout.addWidget(title)

        self.notification_list = QListWidget()
        self.notification_list.setSelectionMode(
            QListWidget.SelectionMode.SingleSelection
        )
        layout.addWidget(self.notification_list)

        buttons = QHBoxLayout()
        clear_button = QPushButton("Clear")
        clear_button.clicked.connect(
            self.notification_list.clear
        )
        buttons.addWidget(clear_button)
        buttons.addStretch()
        layout.addLayout(buttons)
