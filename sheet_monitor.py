import sys
import requests
from datetime import datetime

from PySide6.QtCore import (
    QObject,
    Signal,
    QThread,
    Qt,
)

from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QTextEdit,
    QDialog,
    QFrame,
)


# =========================================================
# CONFIG
# =========================================================

GAS_API_URL = (
    "https://script.google.com/macros/s/AKfycbzV9DSxfz_5rrlmPWqNuplLhFQB-KTuaGUJ4w4xbeX5ud2WUgvEU9evnr6UioEFvz9y-w/exec"
)

POLL_INTERVAL_SECONDS = 30

REQUEST_TIMEOUT = 20


# =========================================================
# Notification Data
# =========================================================

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

        self.title = title

        self.message = message

        self.notification_type = notification_type

        self.sheet = sheet

        self.row = row

        self.column = column

        self.timestamp = (
            timestamp
            or datetime.now()
        )


# =========================================================
# POPUP
# =========================================================

class NotificationPopup(QDialog):

    def __init__(
        self,
        notification,
        parent=None,
    ):

        super().__init__(parent)

        self.notification = notification

        self.setWindowTitle(
            "Daily Log Notification"
        )

        self.setMinimumWidth(500)

        self.setMinimumHeight(260)

        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowStaysOnTopHint
        )

        self.build_ui()


    # =====================================================
    # UI
    # =====================================================

    def build_ui(self):

        layout = QVBoxLayout(self)


        # -------------------------------------------------
        # Title
        # -------------------------------------------------

        title = QLabel(
            self.notification.title
        )

        title.setStyleSheet(
            """
            QLabel {
                font-size: 18px;
                font-weight: bold;
            }
            """
        )


        layout.addWidget(title)


        # -------------------------------------------------
        # Time
        # -------------------------------------------------

        time_text = (
            self.notification.timestamp
            .strftime("%H:%M:%S")
        )

        time_label = QLabel(
            time_text
        )

        time_label.setStyleSheet(
            """
            QLabel {
                color: gray;
                font-size: 12px;
            }
            """
        )


        layout.addWidget(
            time_label
        )


        # -------------------------------------------------
        # Message
        # -------------------------------------------------

        message = QTextEdit()

        message.setReadOnly(True)

        message.setText(
            self.notification.message
        )

        message.setMinimumHeight(
            120
        )


        layout.addWidget(
            message
        )


        # -------------------------------------------------
        # Detail
        # -------------------------------------------------

        detail_parts = []


        if self.notification.sheet:

            detail_parts.append(
                f"Sheet: "
                f"{self.notification.sheet}"
            )


        if self.notification.row:

            detail_parts.append(
                f"Row: "
                f"{self.notification.row}"
            )


        if self.notification.column:

            detail_parts.append(
                f"Column: "
                f"{self.notification.column}"
            )


        if detail_parts:

            detail_label = QLabel(
                " | ".join(
                    detail_parts
                )
            )

            detail_label.setStyleSheet(
                """
                QLabel {
                    color: gray;
                    font-size: 11px;
                }
                """
            )


            layout.addWidget(
                detail_label
            )


        # -------------------------------------------------
        # Close
        # -------------------------------------------------

        button_layout = QHBoxLayout()

        button_layout.addStretch()


        close_button = QPushButton(
            "Close"
        )

        close_button.clicked.connect(
            self.close
        )


        button_layout.addWidget(
            close_button
        )


        layout.addLayout(
            button_layout
        )


# =========================================================
# NOTIFICATION MANAGER
# =========================================================

class NotificationManager(
    QObject
):

    notification_received = Signal(
        object
    )


    def __init__(
        self,
        parent=None,
    ):

        super().__init__(
            parent
        )

        self.parent_widget = parent

        self.notifications = []

        self.popup_queue = []

        self.current_popup = None

        self.central_list = None


    # =====================================================
    # Attach Main Central Noti
    # =====================================================

    def set_central_list(
        self,
        list_widget,
    ):

        self.central_list = (
            list_widget
        )


    # =====================================================
    # Send Notification
    # =====================================================

    def notify(
        self,
        title,
        message,
        notification_type="info",
        sheet="",
        row=None,
        column="",
    ):

        notification = Notification(

            title=title,

            message=message,

            notification_type=
                notification_type,

            sheet=sheet,

            row=row,

            column=column,

        )


        self.notifications.append(
            notification
        )


        # -------------------------------------------------
        # Main Central Noti
        # -------------------------------------------------

        self.add_to_central_feed(
            notification
        )


        # -------------------------------------------------
        # Popup
        # -------------------------------------------------

        self.show_popup(
            notification
        )


        self.notification_received.emit(
            notification
        )


    # =====================================================
    # Add to Central Feed
    # =====================================================

    def add_to_central_feed(
        self,
        notification,
    ):

        if not self.central_list:

            return


        time_text = (
            notification.timestamp
            .strftime("%H:%M:%S")
        )


        item = QListWidgetItem(

            f"[{time_text}] "
            f"{notification.message}"

        )


        item.setData(
            Qt.UserRole,
            notification
        )


        self.central_list.insertItem(
            0,
            item
        )


    # =====================================================
    # Popup
    # =====================================================

    def show_popup(
        self,
        notification,
    ):

        # -------------------------------------------------
        # ถ้ามี Popup อยู่
        # ให้ต่อคิว
        # -------------------------------------------------

        if self.current_popup:

            self.popup_queue.append(
                notification
            )

            return


        self.open_popup(
            notification
        )


    # =====================================================
    # Open Popup
    # =====================================================

    def open_popup(
        self,
        notification,
    ):

        popup = NotificationPopup(

            notification,

            self.parent_widget

        )


        self.current_popup = popup


        popup.finished.connect(
            self.popup_closed
        )


        popup.show()


        popup.raise_()

        popup.activateWindow()


    # =====================================================
    # Popup Closed
    # =====================================================

    def popup_closed(
        self,
    ):

        self.current_popup = None


        if self.popup_queue:

            next_notification = (
                self.popup_queue.pop(0)
            )


            self.open_popup(
                next_notification
            )


# =========================================================
# GOOGLE SHEET CHANGE MONITOR
# =========================================================

class GoogleSheetChangeMonitor(
    QObject
):

    changes_detected = Signal(
        list
    )

    monitor_error = Signal(
        str
    )

    status_changed = Signal(
        str
    )


    def __init__(
        self,
        api_url,
        poll_interval=30,
        parent=None,
    ):

        super().__init__(
            parent
        )

        self.api_url = api_url

        self.poll_interval = (
            poll_interval
        )

        self.running = False

        self.session = requests.Session()


    # =====================================================
    # Start
    # =====================================================

    def start(self):

        self.running = True

        self.status_changed.emit(
            "Google Sheets Monitor: Running"
        )


        # -------------------------------------------------
        # Timer
        # -------------------------------------------------

        from PySide6.QtCore import QTimer


        self.timer = QTimer(
            self
        )


        self.timer.timeout.connect(
            self.check
        )


        self.timer.start(
            self.poll_interval * 1000
        )


        # -------------------------------------------------
        # Check immediately
        # -------------------------------------------------

        self.check()


    # =====================================================
    # Stop
    # =====================================================

    def stop(self):

        self.running = False


        if hasattr(
            self,
            "timer"
        ):

            self.timer.stop()


        self.status_changed.emit(
            "Google Sheets Monitor: Stopped"
        )


    # =====================================================
    # Check API
    # =====================================================

    def check(self):

        if not self.running:

            return


        try:

            response = (
                self.session.get(

                    self.api_url,

                    params={
                        "action":
                            "changes"
                    },

                    timeout=
                        REQUEST_TIMEOUT,

                )
            )


            response.raise_for_status()


            data = (
                response.json()
            )


            # ------------------------------------------------
            # API Error
            # ------------------------------------------------

            if not data.get(
                "success",
                False
            ):

                error = data.get(
                    "error",
                    "Unknown GAS error"
                )


                self.monitor_error.emit(
                    error
                )

                return


            # ------------------------------------------------
            # Changes
            # ------------------------------------------------

            changes = data.get(
                "changes",
                []
            )


            if changes:

                self.changes_detected.emit(
                    changes
                )


            self.status_changed.emit(

                "Google Sheets Monitor: "
                f"OK "
                f"({len(changes)} changes)"

            )


        except requests.RequestException as error:

            self.monitor_error.emit(

                "Google Sheets API error: "
                + str(error)

            )


        except Exception as error:

            self.monitor_error.emit(

                "Google Sheets Monitor error: "
                + str(error)

            )


# =========================================================
# SHEET MONITOR MANAGER
# =========================================================

class SheetMonitorManager(
    QObject
):

    def __init__(
        self,
        notification_manager,
        parent=None,
    ):

        super().__init__(
            parent
        )

        self.notification_manager = (
            notification_manager
        )

        self.monitors = {}


    # =====================================================
    # Add Monitor
    # =====================================================

    def add_monitor(
        self,
        name,
        api_url,
        poll_interval=30,
    ):

        if name in self.monitors:

            return


        monitor = (
            GoogleSheetChangeMonitor(

                api_url=api_url,

                poll_interval=
                    poll_interval,

                parent=self,

            )
        )


        monitor.changes_detected.connect(
            self.handle_changes
        )


        monitor.monitor_error.connect(
            self.handle_error
        )


        monitor.status_changed.connect(
            self.handle_status
        )


        self.monitors[name] = monitor


    # =====================================================
    # Start All
    # =====================================================

    def start_all(self):

        for monitor in (
            self.monitors.values()
        ):

            monitor.start()


    # =====================================================
    # Stop All
    # =====================================================

    def stop_all(self):

        for monitor in (
            self.monitors.values()
        ):

            monitor.stop()


    # =====================================================
    # Handle Changes
    # =====================================================

    def handle_changes(
        self,
        changes,
    ):

        for change in changes:

            self.send_change_notification(
                change
            )


    # =====================================================
    # Convert GAS Change → Notification
    # =====================================================

    def send_change_notification(
        self,
        change,
    ):

        change_type = change.get(
            "type",
            "updated"
        )


        sheet = change.get(
            "sheet",
            ""
        )


        row = change.get(
            "row",
            None
        )


        column = change.get(
            "column",
            ""
        )


        message = change.get(
            "message",
            ""
        )


        header = change.get(
            "header",
            ""
        )


        # -------------------------------------------------
        # Title
        # -------------------------------------------------

        if change_type == "created":

            title = (
                "Google Sheets - "
                "New Data"
            )


        elif change_type == "updated":

            title = (
                "Google Sheets - "
                "Data Updated"
            )


        elif change_type == "deleted":

            title = (
                "Google Sheets - "
                "Data Deleted"
            )


        else:

            title = (
                "Google Sheets "
                "Notification"
            )


        # -------------------------------------------------
        # Message
        # -------------------------------------------------

        final_message = (
            f"{message}\n\n"
            f"Sheet: {sheet}\n"
            f"Row: {row}\n"
            f"Column: {column}\n"
            f"Field: {header}"
        )


        # -------------------------------------------------
        # Send
        # -------------------------------------------------

        self.notification_manager.notify(

            title=title,

            message=final_message,

            notification_type=
                change_type,

            sheet=sheet,

            row=row,

            column=column,

        )


    # =====================================================
    # Error
    # =====================================================

    def handle_error(
        self,
        error,
    ):

        print(
            "[GoogleSheetMonitor]",
            error
        )


    # =====================================================
    # Status
    # =====================================================

    def handle_status(
        self,
        status,
    ):

        print(
            "[GoogleSheetMonitor]",
            status
        )


# =========================================================
# MAIN CENTRAL NOTI WIDGET
# =========================================================

class MainCentralNoti(
    QFrame
):

    def __init__(
        self,
        parent=None,
    ):

        super().__init__(
            parent
        )

        self.build_ui()


    # =====================================================
    # UI
    # =====================================================

    def build_ui(self):

        layout = QVBoxLayout(
            self
        )


        # -------------------------------------------------
        # Header
        # -------------------------------------------------

        title = QLabel(
            "Main Central Noti"
        )


        title.setStyleSheet(
            """
            QLabel {
                font-size: 18px;
                font-weight: bold;
            }
            """
        )


        layout.addWidget(
            title
        )


        # -------------------------------------------------
        # List
        # -------------------------------------------------

        self.notification_list = (
            QListWidget()
        )


        self.notification_list.setSelectionMode(
            QListWidget.SingleSelection
        )


        layout.addWidget(
            self.notification_list
        )


        # -------------------------------------------------
        # Clear
        # -------------------------------------------------

        button_layout = QHBoxLayout()


        clear_button = QPushButton(
            "Clear"
        )


        clear_button.clicked.connect(
            self.notification_list.clear
        )


        button_layout.addWidget(
            clear_button
        )


        button_layout.addStretch()


        layout.addLayout(
            button_layout
        )


# =========================================================
# DAILY LOG INTEGRATION
# =========================================================

class GoogleSheetMonitorSystem(
    QObject
):

    def __init__(
        self,
        parent=None,
    ):

        super().__init__(
            parent
        )


        # =================================================
        # Notification Manager
        # =================================================

        self.notification_manager = (
            NotificationManager(
                parent
            )
        )


        # =================================================
        # Sheet Monitor Manager
        # =================================================

        self.sheet_manager = (
            SheetMonitorManager(

                notification_manager=
                    self.notification_manager,

                parent=self,

            )
        )


        # =================================================
        # Add Spreadsheet
        # =================================================

        self.sheet_manager.add_monitor(

            name=
                "Main Google Sheet",

            api_url=
                GAS_API_URL,

            poll_interval=
                POLL_INTERVAL_SECONDS,

        )


    # =====================================================
    # Connect Central Noti
    # =====================================================

    def connect_central_noti(
        self,
        list_widget,
    ):

        self.notification_manager.set_central_list(
            list_widget
        )


    # =====================================================
    # Start
    # =====================================================

    def start(self):

        self.sheet_manager.start_all()


    # =====================================================
    # Stop
    # =====================================================

    def stop(self):

        self.sheet_manager.stop_all()


# =========================================================
# TEST PROGRAM
# =========================================================

class TestWindow(
    QWidget
):

    def __init__(self):

        super().__init__()

        self.setWindowTitle(
            "Daily Log - Test"
        )

        self.resize(
            700,
            600
        )


        layout = QVBoxLayout(
            self
        )


        # -------------------------------------------------
        # Main Central Noti
        # -------------------------------------------------

        self.central_noti = (
            MainCentralNoti(
                self
            )
        )


        layout.addWidget(
            self.central_noti
        )


        # -------------------------------------------------
        # Google Sheet System
        # -------------------------------------------------

        self.sheet_system = (
            GoogleSheetMonitorSystem(
                self
            )
        )


        self.sheet_system.connect_central_noti(

            self.central_noti
            .notification_list

        )


        # -------------------------------------------------
        # Start
        # -------------------------------------------------

        self.sheet_system.start()


    # =====================================================
    # Close
    # =====================================================

    def closeEvent(
        self,
        event,
    ):

        self.sheet_system.stop()

        event.accept()


# =========================================================
# RUN TEST
# =========================================================

if __name__ == "__main__":

    app = QApplication(
        sys.argv
    )


    window = TestWindow()

    window.show()


    sys.exit(
        app.exec()
    )