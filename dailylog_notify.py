import os
import subprocess
import sys
import time

import requests
from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from notify_history import NotificationHistory
from notify_receiver import CentralNotifyReceiver
from notify_updates import fetch_update, prepare_update
from workers import run_async


APP_VERSION = "1.5.3"
DEVELOPER_CREDIT = "Developed by 王纯真"
ORG = "MiniDailyLog"
APP = "DailyLogNotify"
DEFAULT_RECEIVER_EMAIL = "daily123@gmail.com"

NOTIFY_RELEASES_API = (
    "https://api.github.com/repos/Pnck15/dailylogs/releases?per_page=20"
)


FALLBACK_SOURCE_OPTIONS = [
    {
        "key": "sale_sathorn",
        "label": "Sale Deli Sathorn",
        "aliases": {"Sale Deli Sathorn"},
    },
    {
        "key": "sale_srinakarin",
        "label": "Sale Deli Srinakarin",
        "aliases": {"Sale Deli Srinakarin"},
    },
    {
        "key": "sa_sathorn",
        "label": "SA Sathorn",
        # Backward compatibility with events already published as SA Notify.
        "aliases": {"SA Sathorn", "SA Notify"},
    },
    {
        "key": "sa_srinakarin",
        "label": "SA Srinakarin",
        "aliases": {"SA Srinakarin"},
    },
]


def make_tray_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor("#DC2626"))

    painter = QPainter(pixmap)
    painter.setPen(QColor("white"))

    font = painter.font()
    font.setBold(True)
    font.setPointSize(28)
    painter.setFont(font)

    painter.drawText(
        pixmap.rect(),
        0x84,
        "D",
    )
    painter.end()

    return QIcon(pixmap)


class HistoryDialog(QDialog):
    def __init__(self, history, parent=None):
        super().__init__(parent)

        self.history = history

        self.setWindowTitle(
            "DailyLogNotify - ประวัติแจ้งเตือนทั้งหมด"
        )
        self.resize(620, 420)

        layout = QVBoxLayout(self)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button)

        self.reload()

    def reload(self):
        self.list_widget.clear()

        for item in self.history.all():
            created_at = item.get("created_at", "")
            source = item.get("source", "")
            title = item.get("title", "")
            message = item.get("message", "")

            self.list_widget.addItem(
                f"{created_at}  [{source}]\n"
                f"{title}\n"
                f"{message}"
            )


class LoginDialog(QDialog):
    def __init__(self, receiver, settings, parent=None):
        super().__init__(parent)

        self.receiver = receiver
        self.settings = settings

        self.setWindowTitle(
            "DailyLog Notify Login"
        )
        self.resize(380, 250)
        self.setModal(True)

        layout = QVBoxLayout(self)

        info = QLabel(
            "Login ด้วยบัญชี DailyLog ของเครื่องผู้รับ\n"
            "ครั้งแรกเพียงครั้งเดียว จากนั้นโปรแกรมจะ Start with Windows เอง"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(
            "color: #DC2626;"
        )
        layout.addWidget(self.error_label)

        layout.addWidget(
            QLabel("Email")
        )

        saved_email = str(
            settings.value(
                "central/email",
                DEFAULT_RECEIVER_EMAIL,
            )
            or DEFAULT_RECEIVER_EMAIL
        ).strip()

        self.email = QLineEdit(
            saved_email
        )
        self.email.setPlaceholderText(
            "employee@email.com"
        )
        layout.addWidget(self.email)

        layout.addWidget(
            QLabel("Password")
        )

        self.password = QLineEdit()
        self.password.setEchoMode(
            QLineEdit.EchoMode.Password
        )
        self.password.setPlaceholderText(
            "Password"
        )
        layout.addWidget(self.password)

        self.remember = QCheckBox(
            "จำบัญชีนี้เพื่อรับแจ้งเตือนอัตโนมัติเมื่อเปิด Windows"
        )
        self.remember.setChecked(True)
        layout.addWidget(self.remember)

        buttons = QHBoxLayout()
        buttons.addStretch()

        cancel = QPushButton("Cancel")
        self.login_button = QPushButton("Login")

        buttons.addWidget(cancel)
        buttons.addWidget(self.login_button)
        layout.addLayout(buttons)

        cancel.clicked.connect(self.reject)
        self.login_button.clicked.connect(
            self.do_login
        )
        self.password.returnPressed.connect(
            self.do_login
        )

        self.receiver.login_success.connect(
            self._login_success
        )
        self.receiver.login_failed.connect(
            self._login_failed
        )

    def do_login(self):
        email = self.email.text().strip()
        password = self.password.text()

        if not email or not password:
            self.error_label.setText(
                "กรุณากรอก Email และ Password"
            )
            return

        self.error_label.setText(
            "กำลัง Login..."
        )
        self.login_button.setEnabled(False)

        self.receiver.login(
            email,
            password,
            remember=self.remember.isChecked(),
        )

    def _login_success(self, _email):
        if self.isVisible():
            self.accept()

    def _login_failed(self, message):
        if not self.isVisible():
            return

        self.login_button.setEnabled(True)
        self.error_label.setText(
            f"Login ไม่สำเร็จ: {message}"
        )

    def done(self, result):
        try:
            self.receiver.login_success.disconnect(
                self._login_success
            )
        except Exception:
            pass

        try:
            self.receiver.login_failed.disconnect(
                self._login_failed
            )
        except Exception:
            pass

        super().done(result)


class SourceSelectionDialog(QDialog):
    def __init__(
        self,
        settings,
        source_options,
        first_run=False,
        parent=None,
    ):
        super().__init__(parent)

        self.settings = settings
        self.source_options = list(
            source_options or []
        )
        self.first_run = first_run
        self.checkboxes = {}

        self.setWindowTitle(
            "DailyLog Notify - Notification Sources"
        )
        self.resize(
            430,
            330,
        )
        self.setModal(True)

        layout = QVBoxLayout(self)

        title = QLabel(
            "เลือกแหล่งข้อมูลที่เครื่องนี้ต้องการรับแจ้งเตือน"
        )
        title.setWordWrap(True)
        layout.addWidget(title)

        note = QLabel(
            "ตั้งค่าครั้งแรกเพียงครั้งเดียว "
            "จากนั้น DailyLogNotify จะจำรายการนี้และทำงานอัตโนมัติเมื่อเปิด Windows"
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        saved = set()

        raw = str(
            settings.value(
                "sources/selected",
                "",
            )
            or ""
        ).strip()

        if raw:
            saved = {
                item.strip()
                for item in raw.split(",")
                if item.strip()
            }

        for option in self.source_options:
            checkbox = QCheckBox(
                option["label"]
            )
            checkbox.setChecked(
                option["key"] in saved
            )
            checkbox.stateChanged.connect(
                self._update_save_button
            )
            self.checkboxes[
                option["key"]
            ] = checkbox
            layout.addWidget(
                checkbox
            )

        central_note = QLabel(
            "รายการนี้มาจาก Central อัตโนมัติ "
            "Admin สามารถเปิด/ปิด Source ที่อนุญาตให้ DailyLogNotify รับได้"
        )
        central_note.setWordWrap(True)
        layout.addWidget(
            central_note
        )

        if not self.source_options:
            empty = QLabel(
                "ยังไม่มี Notification Source ที่ Admin เปิดให้รับ"
            )
            empty.setWordWrap(True)
            layout.addWidget(
                empty
            )

        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()

        cancel = QPushButton(
            "Cancel"
        )
        self.save_button = QPushButton(
            "Save"
        )

        buttons.addWidget(
            cancel
        )
        buttons.addWidget(
            self.save_button
        )
        layout.addLayout(
            buttons
        )

        cancel.clicked.connect(
            self.reject
        )
        self.save_button.clicked.connect(
            self._save
        )

        self._update_save_button()

    def selected_keys(self):
        return [
            key
            for key, checkbox
            in self.checkboxes.items()
            if checkbox.isChecked()
        ]

    def _update_save_button(self):
        # At least one source must be selected.
        self.save_button.setEnabled(
            bool(
                self.selected_keys()
            )
        )

    def _save(self):
        selected = self.selected_keys()

        if not selected:
            QMessageBox.warning(
                self,
                "Notification Sources",
                "กรุณาเลือกอย่างน้อย 1 แหล่งข้อมูล",
            )
            return

        self.settings.setValue(
            "sources/selected",
            ",".join(
                selected
            ),
        )
        self.settings.setValue(
            "sources/configured",
            True,
        )
        self.settings.sync()
        self.accept()



class NotifyPopup(QDialog):
    """Independent DailyLogNotify popup.

    This popup does not depend on Windows Notification settings.
    Text can be selected/copied, the user can close it with X,
    and each popup closes automatically after 10 minutes.
    """

    def __init__(
        self,
        title,
        message,
        history_callback=None,
        parent=None,
    ):
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )

        self.setAttribute(
            Qt.WidgetAttribute.WA_DeleteOnClose,
            True,
        )

        self.setModal(False)

        self.history_callback = (
            history_callback
        )

        self.setMinimumWidth(315)
        self.setMaximumWidth(375)

        self.setStyleSheet(
            """
            QDialog {
                background: #FFFFFF;
                border: 1px solid #D1D5DB;
                border-radius: 10px;
            }
            QLabel {
                color: #111827;
            }
            QTextEdit {
                background: #F9FAFB;
                border: 1px solid #E5E7EB;
                border-radius: 6px;
                padding: 6px;
                color: #111827;
            }
            QPushButton {
                min-height: 24px;
            }
            """
        )

        root = QVBoxLayout(
            self
        )
        root.setContentsMargins(
            9,
            8,
            9,
            8,
        )
        root.setSpacing(6)

        header = QHBoxLayout()

        title_label = QLabel(
            f"🔔 {title}"
        )
        title_label.setWordWrap(
            True
        )
        title_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )

        title_font = (
            title_label.font()
        )
        title_font.setBold(
            True
        )
        title_label.setFont(
            title_font
        )

        close_button = QPushButton(
            "✕"
        )
        close_button.setFixedSize(
            28,
            28,
        )
        close_button.setToolTip(
            "Close"
        )
        close_button.clicked.connect(
            self.close
        )

        header.addWidget(
            title_label,
            1,
        )
        header.addWidget(
            close_button,
            0,
        )
        root.addLayout(
            header
        )

        detail_label = QLabel(
            "รายละเอียดแจ้ง:"
        )
        detail_font = (
            detail_label.font()
        )
        detail_font.setBold(
            True
        )
        detail_label.setFont(
            detail_font
        )
        root.addWidget(
            detail_label
        )

        self.message_box = QTextEdit()
        self.message_box.setReadOnly(
            True
        )
        self.message_box.setPlainText(
            str(message or "")
        )
        self.message_box.setMinimumHeight(
            75
        )
        self.message_box.setMaximumHeight(
            150
        )
        self.message_box.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        root.addWidget(
            self.message_box
        )

        footer = QHBoxLayout()

        hint = QLabel(
            "เลือกข้อความแล้ว Ctrl+C ได้ • ปิดอัตโนมัติใน 10 นาที"
        )
        hint.setStyleSheet(
            "color: #6B7280; font-size: 10px;"
        )

        copy_button = QPushButton(
            "Copy All"
        )
        copy_button.clicked.connect(
            self.copy_all
        )

        footer.addWidget(
            hint
        )
        footer.addStretch()
        footer.addWidget(
            copy_button
        )

        root.addLayout(
            footer
        )

        history_button = QPushButton(
            "ดูประวัติแจ้งเตือนทั้งหมด"
        )
        history_button.setToolTip(
            "เปิด All Notification Logs ใน DailyLogNotify"
        )
        history_button.clicked.connect(
            self.open_history
        )
        root.addWidget(
            history_button
        )

        self.resize(
            400,
            255,
        )

        self._auto_close_timer = QTimer(
            self
        )
        self._auto_close_timer.setSingleShot(
            True
        )
        self._auto_close_timer.setInterval(
            10 * 60 * 1000
        )
        self._auto_close_timer.timeout.connect(
            self.close
        )
        self._auto_close_timer.start()

    def open_history(self):
        if callable(
            self.history_callback
        ):
            self.history_callback()

    def copy_all(self):
        QApplication.clipboard().setText(
            self.message_box.toPlainText()
        )


class NotifyApp(QWidget):
    def __init__(self):
        super().__init__()

        self.settings = QSettings(
            ORG,
            APP,
        )
        self.history = NotificationHistory()
        self.receiver = None
        self._notify_popups = []
        self.source_options = [
            dict(option)
            for option in FALLBACK_SOURCE_OPTIONS
        ]

        self.setWindowTitle(
            "DailyLog Notify"
        )
        self.setWindowIcon(
            make_tray_icon()
        )
        self.setFixedSize(
            430,
            200,
        )

        layout = QVBoxLayout(self)

        self.status = QLabel(
            "กำลังเริ่ม DailyLog Notify..."
        )
        self.status.setWordWrap(True)

        self.info = QLabel(
            "รับ Notification จาก DailyLog Central\n"
            "แสดง Popup ของ DailyLogNotify เอง ไม่ใช้ Windows Notification"
        )
        self.info.setWordWrap(True)

        buttons = QHBoxLayout()

        history_button = QPushButton(
            "Notification History"
        )
        sources_button = QPushButton(
            "Notification Sources"
        )
        login_button = QPushButton(
            "Login / Change account"
        )

        buttons.addWidget(
            history_button
        )
        buttons.addWidget(
            sources_button
        )
        buttons.addWidget(
            login_button
        )

        layout.addWidget(
            self.status
        )
        layout.addWidget(
            self.info
        )

        self.sources_label = QLabel("")
        self.sources_label.setWordWrap(True)
        layout.addWidget(
            self.sources_label
        )

        layout.addLayout(
            buttons
        )

        self.startup_label = QLabel(
            "✅ Start with Windows"
        )
        layout.addWidget(
            self.startup_label
        )

        self.version_label = QLabel(
            f"Version {APP_VERSION} • {DEVELOPER_CREDIT}"
        )
        self.version_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.version_label.setStyleSheet(
            "color: #6B7280; font-size: 10px;"
        )
        layout.addWidget(
            self.version_label
        )

        history_button.clicked.connect(
            self.open_history
        )
        sources_button.clicked.connect(
            self.open_source_selection
        )
        login_button.clicked.connect(
            self.open_login
        )

        self.update_sources_label()

        # -----------------------------------------
        # Tray
        # -----------------------------------------

        self.tray = QSystemTrayIcon(
            self
        )
        self.tray.setIcon(
            make_tray_icon()
        )
        self.tray.setToolTip(
            "DailyLog Notify"
        )

        tray_menu = QMenu()

        show_action = QAction(
            "Open DailyLog Notify",
            self,
        )
        history_action = QAction(
            "Notification History",
            self,
        )
        sources_action = QAction(
            "Notification Sources",
            self,
        )
        login_action = QAction(
            "Login / Change account",
            self,
        )
        status_action = QAction(
            "System Status",
            self,
        )
        test_popup_action = QAction(
            "Test Notification Popup",
            self,
        )
        update_action = QAction(
            "Check for updates",
            self,
        )
        exit_action = QAction(
            "Exit",
            self,
        )

        tray_menu.addAction(
            show_action
        )
        tray_menu.addAction(
            history_action
        )
        tray_menu.addAction(
            sources_action
        )
        tray_menu.addAction(
            login_action
        )
        tray_menu.addAction(
            status_action
        )
        tray_menu.addAction(
            test_popup_action
        )
        tray_menu.addAction(
            update_action
        )
        tray_menu.addSeparator()
        tray_menu.addAction(
            exit_action
        )

        self.tray.setContextMenu(
            tray_menu
        )

        show_action.triggered.connect(
            self.showNormal
        )
        history_action.triggered.connect(
            self.open_history
        )
        sources_action.triggered.connect(
            self.open_source_selection
        )
        login_action.triggered.connect(
            self.open_login
        )
        status_action.triggered.connect(
            self.open_system_status
        )
        test_popup_action.triggered.connect(
            self.show_test_popup
        )
        update_action.triggered.connect(
            lambda: self.check_for_updates(
                manual=True
            )
        )
        exit_action.triggered.connect(
            QApplication.quit
        )

        self.tray.show()

        # -----------------------------------------
        # Start with Windows
        # -----------------------------------------

        self.enable_startup()

        # -----------------------------------------
        # Central receiver
        # -----------------------------------------

        try:
            self.receiver = CentralNotifyReceiver(
                self.settings,
                self,
                app_version=APP_VERSION,
            )

            self.receiver.event.connect(
                self.notify
            )
            self.receiver.source_list_changed.connect(
                self._source_list_changed
            )
            self.receiver.status_changed.connect(
                self.status.setText
            )
            self.receiver.login_failed.connect(
                self._background_login_failed
            )
            self.receiver.login_success.connect(
                self._receiver_login_success
            )
            self.receiver.session_revoked.connect(
                self._receiver_session_revoked
            )

            if self.receiver.has_saved_credentials():
                self.receiver.login_saved()
            else:
                self.status.setText(
                    "⚪ Central Notification: ต้อง Login ครั้งแรก"
                )

                QTimer.singleShot(
                    300,
                    self._show_login_if_needed,
                )

        except Exception as error:
            self.status.setText(
                f"🔴 Central Notification: {error}"
            )
            login_button.setEnabled(False)
            login_action.setEnabled(False)

        # -----------------------------------------
        # Automatic update
        # -----------------------------------------

        self._update_check_running = False

        # Check shortly after startup without blocking the receiver.
        QTimer.singleShot(
            5000,
            self.check_for_updates,
        )

        # Keep long-running tray clients current as well.
        self.update_timer = QTimer(
            self
        )
        self.update_timer.setInterval(
            15 * 60 * 1000
        )
        self.update_timer.timeout.connect(
            self.check_for_updates
        )
        self.update_timer.start()

    def _show_login_if_needed(self):
        if (
            self.receiver is not None
            and not self.receiver.has_saved_credentials()
        ):
            self.showNormal()
            self.open_login()

    def _background_login_failed(self, message):
        # Startup can fail because a password changed or membership was removed.
        # Show the window so the user is not left with a silent tray process.
        if "--startup" in sys.argv:
            self.showNormal()

        self.status.setToolTip(
            str(message)
        )

    def _receiver_session_revoked(
        self,
        message,
    ):
        self.showNormal()
        self.raise_()
        self.activateWindow()

        QMessageBox.warning(
            self,
            "DailyLogNotify Session",
            str(message),
        )

    def _source_filter_configured(self):
        return self.settings.value(
            "sources/configured",
            False,
            type=bool,
        )

    def _selected_source_keys(self):
        raw = str(
            self.settings.value(
                "sources/selected",
                "",
            )
            or ""
        ).strip()

        if not raw:
            return set()

        return {
            item.strip()
            for item in raw.split(",")
            if item.strip()
        }

    def _available_source_keys(self):
        return {
            str(
                option.get(
                    "key",
                    "",
                )
                or ""
            ).strip()
            for option in self.source_options
            if str(
                option.get(
                    "key",
                    "",
                )
                or ""
            ).strip()
        }

    def _source_allowed(
        self,
        source,
        source_key="",
    ):
        if not self._source_filter_configured():
            return False

        selected = self._selected_source_keys()
        available = self._available_source_keys()

        key = str(
            source_key or ""
        ).strip()

        if key:
            return (
                key in selected
                and key in available
            )

        # Backward compatibility for older notification_events
        # created before source_key was stored.
        source_text = str(
            source or ""
        ).strip()

        for option in self.source_options:
            option_key = str(
                option.get(
                    "key",
                    "",
                )
                or ""
            ).strip()

            if (
                option_key not in selected
                or option_key not in available
            ):
                continue

            aliases = set(
                option.get(
                    "aliases",
                    [],
                )
                or []
            )
            aliases.add(
                str(
                    option.get(
                        "label",
                        "",
                    )
                    or ""
                ).strip()
            )

            if source_text in aliases:
                return True

        return False

    def _source_list_changed(
        self,
        options,
    ):
        normalized = []

        for option in options or []:
            if not isinstance(
                option,
                dict,
            ):
                continue

            key = str(
                option.get(
                    "key",
                    "",
                )
                or ""
            ).strip()

            label = str(
                option.get(
                    "label",
                    "",
                )
                or ""
            ).strip()

            if not key or not label:
                continue

            normalized.append({
                "key": key,
                "label": label,
                "source_type": str(
                    option.get(
                        "source_type",
                        "",
                    )
                    or ""
                ).strip(),
                "display_order": int(
                    option.get(
                        "display_order",
                        100,
                    )
                    or 100
                ),
                "aliases": {label},
            })

        if normalized:
            self.source_options = normalized
        else:
            # Keep the last good catalog during a temporary Central
            # source-list failure.
            if not self.source_options:
                self.source_options = [
                    dict(option)
                    for option in FALLBACK_SOURCE_OPTIONS
                ]

        self.update_sources_label()

    def update_sources_label(self):
        selected = self._selected_source_keys()

        labels = [
            str(
                option.get(
                    "label",
                    "",
                )
                or ""
            ).strip()
            for option in self.source_options
            if str(
                option.get(
                    "key",
                    "",
                )
                or ""
            ).strip()
            in selected
        ]

        labels = [
            label
            for label in labels
            if label
        ]

        if labels:
            self.sources_label.setText(
                "รับแจ้งเตือน: "
                + ", ".join(
                    labels
                )
            )
        else:
            self.sources_label.setText(
                "รับแจ้งเตือน: ยังไม่ได้เลือกแหล่งข้อมูล"
            )

    def _receiver_login_success(
        self,
        _email,
    ):
        if self._source_filter_configured():
            self.update_sources_label()
            return

        # Pause before the first event poll. The source catalog has
        # already been loaded during login, so the first-run choices
        # always reflect what Admin currently allows.
        if self.receiver is not None:
            self.receiver.pause()

        self.showNormal()

        QTimer.singleShot(
            0,
            lambda:
            self.open_source_selection(
                first_run=True
            ),
        )

    def open_source_selection(
        self,
        first_run=False,
    ):
        if (
            self.receiver is not None
            and self.receiver.client is not None
        ):
            self.receiver.refresh_sources()

        dialog = SourceSelectionDialog(
            self.settings,
            self.source_options,
            first_run=first_run,
            parent=self,
        )

        result = dialog.exec()

        if (
            result
            == QDialog.DialogCode.Accepted
        ):
            self.update_sources_label()

            if (
                self.receiver is not None
                and self.receiver.client is not None
            ):
                self.receiver.resume()
                self.receiver.send_heartbeat()

            if (
                first_run
                and "--startup" in sys.argv
            ):
                self.hide()

        elif first_run:
            self.status.setText(
                "🟡 Central Notification: รอเลือกแหล่งข้อมูล"
            )

    def open_system_status(self):
        dialog = QDialog(
            self
        )
        dialog.setWindowTitle(
            "DailyLogNotify - System Status"
        )
        dialog.resize(
            470,
            390,
        )

        layout = QVBoxLayout(
            dialog
        )

        login_ok = bool(
            self.receiver is not None
            and self.receiver.client is not None
            and self.receiver.workspace_id
        )

        email = (
            str(
                self.receiver.email
                or ""
            ).strip()
            if self.receiver is not None
            else ""
        )

        selected = (
            self._selected_source_keys()
        )

        selected_labels = [
            str(
                option.get(
                    "label",
                    "",
                )
                or ""
            ).strip()
            for option in self.source_options
            if str(
                option.get(
                    "key",
                    "",
                )
                or ""
            ).strip()
            in selected
        ]

        selected_labels = [
            label
            for label in selected_labels
            if label
        ]

        updater_path = os.path.join(
            os.path.dirname(
                sys.executable
            ),
            "DailyLogUpdater.exe",
        )

        updater_ok = bool(
            getattr(
                sys,
                "frozen",
                False,
            )
            and os.path.isfile(
                updater_path
            )
        )

        startup_ok = False

        if getattr(
            sys,
            "frozen",
            False,
        ):
            run = QSettings(
                (
                    r"HKEY_CURRENT_USER\Software\Microsoft\Windows"
                    r"\CurrentVersion\Run"
                ),
                QSettings.Format.NativeFormat,
            )

            startup_value = str(
                run.value(
                    "DailyLogNotify",
                    "",
                )
                or ""
            )

            startup_ok = (
                os.path.normcase(
                    os.path.abspath(
                        sys.executable
                    )
                )
                in os.path.normcase(
                    startup_value
                )
            )

        status_box = QTextEdit()
        status_box.setReadOnly(
            True
        )
        status_box.setPlainText(
            "\n".join(
                [
                    f"Version: {APP_VERSION}",
                    DEVELOPER_CREDIT,
                    "",
                    (
                        "Central Login: ✅ Connected"
                        if login_ok
                        else "Central Login: ❌ Not connected"
                    ),
                    (
                        f"User: {email}"
                        if email
                        else "User: -"
                    ),
                    (
                        "Device: "
                        + str(
                            getattr(
                                self.receiver,
                                "device_name",
                                "",
                            )
                            or "-"
                        )
                    ),
                    (
                        "Device ID: "
                        + str(
                            getattr(
                                self.receiver,
                                "device_id",
                                "",
                            )
                            or "-"
                        )
                    ),
                    (
                        "Windows Startup: ✅ Enabled"
                        if startup_ok
                        else (
                            "Windows Startup: ⚠️ Not confirmed"
                            if getattr(
                                sys,
                                "frozen",
                                False,
                            )
                            else "Windows Startup: Source mode"
                        )
                    ),
                    (
                        "Updater: ✅ Ready"
                        if updater_ok
                        else (
                            "Updater: ❌ DailyLogUpdater.exe not found"
                            if getattr(
                                sys,
                                "frozen",
                                False,
                            )
                            else "Updater: Source mode"
                        )
                    ),
                    "",
                    "Notification Sources:",
                    (
                        "\n".join(
                            f"• {label}"
                            for label in selected_labels
                        )
                        if selected_labels
                        else "• ยังไม่ได้เลือก Source"
                    ),
                ]
            )
        )
        status_box.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        layout.addWidget(
            status_box
        )

        buttons = QHBoxLayout()

        central_button = QPushButton(
            "Test Central Now"
        )
        update_button = QPushButton(
            "Check Update Now"
        )
        close_button = QPushButton(
            "Close"
        )

        buttons.addWidget(
            central_button
        )
        buttons.addWidget(
            update_button
        )
        buttons.addStretch()
        buttons.addWidget(
            close_button
        )

        layout.addLayout(
            buttons
        )

        def test_central():
            if (
                self.receiver is None
                or self.receiver.client is None
            ):
                QMessageBox.warning(
                    dialog,
                    "Central Notification",
                    "ยังไม่ได้ Login หรือ Central ยังไม่เชื่อมต่อ",
                )
                return

            self.receiver.poll()

            QMessageBox.information(
                dialog,
                "Central Notification",
                (
                    "ส่งคำขอตรวจ Central แล้ว\n\n"
                    "ถ้าสถานะหน้า DailyLogNotify ยังคงเป็นสีเขียว "
                    "แสดงว่า receiver ทำงานปกติ"
                ),
            )

        central_button.clicked.connect(
            test_central
        )
        update_button.clicked.connect(
            lambda:
            self.check_for_updates(
                manual=True
            )
        )
        close_button.clicked.connect(
            dialog.close
        )

        dialog.exec()

    def open_login(self):
        if self.receiver is None:
            QMessageBox.warning(
                self,
                "DailyLog Notify",
                "Central Notification ยังไม่พร้อมใช้งาน",
            )
            return

        LoginDialog(
            self.receiver,
            self.settings,
            self,
        ).exec()

    def open_history(self):
        HistoryDialog(
            self.history,
            self,
        ).exec()

    def notify(
        self,
        source,
        title,
        message,
        show_popup=True,
        source_key="",
    ):
        # This PC receives only sources selected locally AND currently
        # published by Admin through Central.
        if not self._source_allowed(
            source,
            source_key,
        ):
            return

        self.history.add(
            source,
            title,
            message,
        )

        # Only current-day events create a popup, but the popup is
        # owned by DailyLogNotify itself and therefore does not depend on
        # Windows Notification being enabled.
        if show_popup:
            self._show_notify_popup(
                title,
                message,
            )

    def show_test_popup(self):
        self._show_notify_popup(
            "DailyLogNotify - Test",
            (
                "ทดสอบ Popup ของ DailyLogNotify\n"
                "หน้าต่างนี้ไม่ใช้ Windows Notification\n"
                "สามารถเลือกข้อความเพื่อ Copy ได้ และจะปิดอัตโนมัติใน 10 นาที"
            ),
        )

    def _show_notify_popup(
        self,
        title,
        message,
    ):
        popup = NotifyPopup(
            title,
            message,
            history_callback=self.open_history,
            parent=None,
        )

        self._notify_popups.append(
            popup
        )

        popup.finished.connect(
            lambda _result=0, p=popup:
            self._notify_popup_closed(
                p
            )
        )

        popup.show()
        popup.raise_()

        self._position_notify_popups()

    def _notify_popup_closed(
        self,
        popup,
    ):
        self._notify_popups = [
            item
            for item in self._notify_popups
            if item is not popup
        ]

        QTimer.singleShot(
            0,
            self._position_notify_popups,
        )

    def _position_notify_popups(
        self,
    ):
        if not self._notify_popups:
            return

        screen = QApplication.primaryScreen()

        if screen is None:
            return

        area = screen.availableGeometry()

        margin = 16
        spacing = 10
        y = (
            area.bottom()
            - margin
        )

        # Newest popup stays closest to the lower-right corner.
        for popup in reversed(
            self._notify_popups
        ):
            if popup is None:
                continue

            popup.adjustSize()

            width = popup.width()
            height = popup.height()
            x = (
                area.right()
                - width
                - margin
                + 1
            )
            y = (
                y
                - height
            )

            popup.move(
                x,
                y,
            )

            y -= spacing

    def enable_startup(self):
        if not getattr(
            sys,
            "frozen",
            False,
        ):
            self.startup_label.setText(
                "Start with Windows: ใช้งานเมื่อ Build เป็น .exe"
            )
            return

        run = QSettings(
            (
                r"HKEY_CURRENT_USER\Software\Microsoft\Windows"
                r"\CurrentVersion\Run"
            ),
            QSettings.Format.NativeFormat,
        )

        run.setValue(
            "DailyLogNotify",
            f'"{sys.executable}" --startup',
        )
        run.sync()

        self.startup_label.setText(
            "✅ Start with Windows"
        )

    def _fetch_update_info(self):
        data = fetch_update(APP_VERSION)
        if getattr(sys, "frozen", False):
            data = prepare_update(data, os.path.dirname(sys.executable))
        return data

    def check_for_updates(
        self,
        manual=False,
    ):
        """Check in the background and install Notify updates automatically."""

        if self._update_check_running:
            return
        last_attempt = float(self.settings.value("update/last_attempt", 0) or 0)
        if not manual and time.time() - last_attempt < 15 * 60:
            return

        self._update_check_running = True

        def finished(result):
            self._update_check_running = False

            if not result.get(
                "available",
                False,
            ):
                if manual:
                    QMessageBox.information(
                        self,
                        "DailyLog Notify Update",
                        (
                            "ใช้เวอร์ชันล่าสุดแล้ว\n"
                            f"Version: {APP_VERSION}\n\n"
                            f"{DEVELOPER_CREDIT}"
                        ),
                    )
                return

            if not getattr(
                sys,
                "frozen",
                False,
            ):
                if manual:
                    QMessageBox.information(
                        self,
                        "DailyLog Notify Update",
                        (
                            "พบเวอร์ชันใหม่ "
                            f"{result.get('latest', '')}\n"
                            "Auto Update จะติดตั้งเมื่อรัน "
                            "DailyLogNotify.exe ที่ Build แล้ว\n\n"
                            f"{DEVELOPER_CREDIT}"
                        ),
                    )
                return

            updater = os.path.join(
                os.path.dirname(
                    sys.executable
                ),
                "DailyLogUpdater.exe",
            )

            if not os.path.isfile(
                updater
            ):
                message = (
                    "พบเวอร์ชันใหม่ แต่ไม่พบ "
                    "DailyLogUpdater.exe"
                )
                self.status.setToolTip(
                    message
                )
                print(
                    "[Notify Update]",
                    message,
                )
                if manual:
                    QMessageBox.warning(
                        self,
                        "DailyLog Notify Update",
                        message,
                    )
                return

            args = [
                updater,
                str(
                    os.getpid()
                ),
                sys.executable,
                str(
                    result.get("prepared_file") or result.get("download_url", "")
                ),
                str(
                    result.get(
                        "sha256",
                        "",
                    )
                ),
            ]

            # Preserve the saved account/source choices and restart into the tray.
            args.append("--startup")

            self.status.setText(
                (
                    "🟡 DailyLog Notify: "
                    f"กำลังอัปเดตเป็น {result.get('latest', '')}"
                )
            )

            try:
                self.settings.setValue("update/last_attempt", time.time())
                self.settings.sync()
                subprocess.Popen(args, close_fds=True)
            except Exception as error:
                self.status.setText(
                    "🔴 DailyLog Notify: เริ่ม Updater ไม่สำเร็จ"
                )
                self.status.setToolTip(
                    str(error)
                )
                if manual:
                    QMessageBox.warning(
                        self,
                        "DailyLog Notify Update",
                        str(error),
                    )
                return

            QApplication.quit()

        def failed(message):
            self._update_check_running = False

            print(
                "[Notify Update]",
                message,
            )

            if manual:
                QMessageBox.warning(
                    self,
                    "DailyLog Notify Update",
                    (
                        "ตรวจสอบ Update ไม่สำเร็จ\n\n"
                        f"{message}\n\n"
                        f"{DEVELOPER_CREDIT}"
                    ),
                )

        run_async(
            self,
            self._fetch_update_info,
            finished,
            failed,
        )

    def closeEvent(self, event):
        event.ignore()
        self.hide()


if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        from notify_receiver import load_notify_config
        from supabase import create_client
        create_client(*load_notify_config())
        smoke_app = QApplication(sys.argv)
        make_tray_icon()
        raise SystemExit(0)

    app = QApplication(
        sys.argv
    )
    app.setQuitOnLastWindowClosed(
        False
    )
    app.setWindowIcon(
        make_tray_icon()
    )

    window = NotifyApp()

    if "--startup" not in sys.argv:
        window.show()

    sys.exit(
        app.exec()
    )

