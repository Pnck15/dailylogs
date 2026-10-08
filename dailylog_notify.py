import os
import subprocess
import sys

import requests
from PySide6.QtCore import QSettings, QTimer
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
    QVBoxLayout,
    QWidget,
)

from notify_history import NotificationHistory
from notify_receiver import CentralNotifyReceiver
from update_checker import UpdateChecker
from workers import run_async


APP_VERSION = "1.2.0"
ORG = "MiniDailyLog"
APP = "DailyLogNotify"
DEFAULT_RECEIVER_EMAIL = "daily123@gmail.com"

NOTIFY_RELEASES_API = (
    "https://api.github.com/repos/Pnck15/dailylogs/releases?per_page=20"
)


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
            "DailyLog Notification History"
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

        for item in self.history.recent(200):
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


class NotifyApp(QWidget):
    def __init__(self):
        super().__init__()

        self.settings = QSettings(
            ORG,
            APP,
        )
        self.history = NotificationHistory()
        self.receiver = None

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
            "ไม่ต้องตั้งค่า GAS หรือ LINE ในเครื่องนี้"
        )
        self.info.setWordWrap(True)

        buttons = QHBoxLayout()

        history_button = QPushButton(
            "Notification History"
        )
        login_button = QPushButton(
            "Login / Change account"
        )

        buttons.addWidget(
            history_button
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
        layout.addLayout(
            buttons
        )

        self.startup_label = QLabel(
            "✅ Start with Windows"
        )
        layout.addWidget(
            self.startup_label
        )

        history_button.clicked.connect(
            self.open_history
        )
        login_button.clicked.connect(
            self.open_login
        )

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
        login_action = QAction(
            "Login / Change account",
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
            login_action
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
        login_action.triggered.connect(
            self.open_login
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
            )

            self.receiver.event.connect(
                self.notify
            )
            self.receiver.status_changed.connect(
                self.status.setText
            )
            self.receiver.login_failed.connect(
                self._background_login_failed
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
            6 * 60 * 60 * 1000
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
    ):
        # Always keep the event in local history.
        self.history.add(
            source,
            title,
            message,
        )

        # Only current-day events may create a Windows popup.
        if show_popup:
            self.tray.showMessage(
                title,
                message,
                QSystemTrayIcon.MessageIcon.Information,
                10000,
            )

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
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "DailyLogNotify-Updater/1.2",
            "Cache-Control": "no-cache",
        }

        response = requests.get(
            NOTIFY_RELEASES_API,
            timeout=(5, 12),
            headers=headers,
        )
        response.raise_for_status()

        releases = response.json()

        if not isinstance(
            releases,
            list,
        ):
            return {
                "available": False,
            }

        release = next(
            (
                item
                for item in releases
                if isinstance(
                    item,
                    dict,
                )
                and str(
                    item.get(
                        "tag_name",
                        "",
                    )
                ).startswith(
                    "notify-v"
                )
                and not item.get(
                    "draft"
                )
            ),
            None,
        )

        if not release:
            return {
                "available": False,
            }

        asset = next(
            (
                item
                for item in release.get(
                    "assets",
                    [],
                )
                if isinstance(
                    item,
                    dict,
                )
                and item.get(
                    "name"
                )
                == "notify-version.json"
            ),
            None,
        )

        if not asset:
            return {
                "available": False,
            }

        manifest_url = str(
            asset.get(
                "browser_download_url",
                "",
            )
            or ""
        ).strip()

        if not manifest_url:
            return {
                "available": False,
            }

        manifest_response = requests.get(
            manifest_url,
            timeout=(5, 12),
            headers={
                "User-Agent":
                    "DailyLogNotify-Updater/1.2",
                "Cache-Control":
                    "no-cache",
            },
        )
        manifest_response.raise_for_status()

        data = manifest_response.json()

        latest = str(
            data.get(
                "version",
                "",
            )
            or ""
        ).strip()

        if (
            not latest
            or UpdateChecker._version_tuple(
                latest
            )
            <= UpdateChecker._version_tuple(
                APP_VERSION
            )
        ):
            return {
                "available": False,
                "latest": latest,
            }

        url = str(
            data.get(
                "download_url",
                "",
            )
            or ""
        ).strip()

        sha = str(
            data.get(
                "sha256",
                "",
            )
            or ""
        ).strip()

        if not url:
            return {
                "available": False,
            }

        return {
            "available": True,
            "latest": latest,
            "download_url": url,
            "sha256": sha,
        }

    def check_for_updates(
        self,
        manual=False,
    ):
        """Check in the background and install Notify updates automatically."""

        if self._update_check_running:
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
                            f"Version: {APP_VERSION}"
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
                            "DailyLogNotify.exe ที่ Build แล้ว"
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
                    result.get(
                        "download_url",
                        "",
                    )
                ),
                str(
                    result.get(
                        "sha256",
                        "",
                    )
                ),
            ]

            # Keep startup launches silent after updater restarts the app.
            if "--startup" in sys.argv:
                args.append(
                    "--startup"
                )

            self.status.setText(
                (
                    "🟡 DailyLog Notify: "
                    f"กำลังอัปเดตเป็น {result.get('latest', '')}"
                )
            )

            try:
                subprocess.Popen(
                    args
                )
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
                        f"{message}"
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
