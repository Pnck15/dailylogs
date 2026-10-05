import os
import sys
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QMenu, QMessageBox, QPushButton, QSystemTrayIcon,
    QVBoxLayout, QWidget
)
from notify_channels import NotificationChannels
from notify_history import NotificationHistory

APP_VERSION = "1.0.0"
ORG = "MiniDailyLog"
APP = "DailyLogNotify"

class ConnectionsDialog(QDialog):
    def __init__(self, channels, parent=None):
        super().__init__(parent)
        self.channels = channels
        self.setWindowTitle("Notification Connections")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("LINE Messaging API"))
        form = QFormLayout()
        self.enabled = QCheckBox("เปิดส่งแจ้งเตือนไป LINE")
        self.enabled.setChecked(channels.line_enabled())
        self.token = QLineEdit(channels.line_token())
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.target = QLineEdit(channels.line_target())
        form.addRow("", self.enabled)
        form.addRow("Channel access token", self.token)
        form.addRow("User / Group ID", self.target)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        test = QPushButton("Test LINE")
        save = QPushButton("Save")
        close = QPushButton("Close")
        buttons.addWidget(test); buttons.addStretch(); buttons.addWidget(save); buttons.addWidget(close)
        layout.addLayout(buttons)
        save.clicked.connect(self.save)
        close.clicked.connect(self.close)
        test.clicked.connect(self.test_line)

    def save(self):
        self.channels.save_line(self.enabled.isChecked(), self.token.text(), self.target.text())
        QMessageBox.information(self, "Connections", "บันทึกการตั้งค่าแล้ว")

    def test_line(self):
        self.channels.save_line(self.enabled.isChecked(), self.token.text(), self.target.text())
        ok, msg = self.channels.send_line("DailyLog Notify: LINE test message")
        (QMessageBox.information if ok else QMessageBox.warning)(self, "LINE", msg)

class HistoryDialog(QDialog):
    def __init__(self, history, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Notification History")
        self.resize(620, 420)
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        layout.addWidget(self.list)
        for dt, source, title, message in history.recent():
            self.list.addItem(f"{dt} | {source or '-'} | {title}\n{message}")

class NotifyApp(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = QSettings(ORG, APP)
        self.channels = NotificationChannels()
        self.history = NotificationHistory()
        self.setWindowTitle("DailyLog Notify")
        self.setFixedSize(420, 190)
        layout = QVBoxLayout(self)
        self.status = QLabel("DailyLog Notify กำลังทำงาน")
        self.summary = QLabel("Today's Delivery Summary: รอข้อมูลจาก Monitor")
        connections = QPushButton("Notification Connections")
        history = QPushButton("Notification History")
        layout.addWidget(self.status); layout.addWidget(self.summary)
        layout.addWidget(connections); layout.addWidget(history); layout.addStretch()
        connections.clicked.connect(self.open_connections)
        history.clicked.connect(self.open_history)
        self.tray = QSystemTrayIcon(self)
        self.tray.setToolTip("DailyLog Notify")
        menu = QMenu()
        show_action = QAction("Open DailyLog Notify", self)
        conn_action = QAction("Notification Connections", self)
        hist_action = QAction("Notification History", self)
        quit_action = QAction("Exit", self)
        menu.addAction(show_action); menu.addAction(conn_action); menu.addAction(hist_action)
        menu.addSeparator(); menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        show_action.triggered.connect(self.showNormal)
        conn_action.triggered.connect(self.open_connections)
        hist_action.triggered.connect(self.open_history)
        quit_action.triggered.connect(QApplication.quit)
        self.tray.show()
        self.enable_startup()
        QTimer.singleShot(500, self.hide)

    def enable_startup(self):
        if not getattr(sys, "frozen", False):
            return
        run = QSettings(r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run", QSettings.Format.NativeFormat)
        run.setValue("DailyLogNotify", f'"{sys.executable}" --startup')

    def open_connections(self):
        ConnectionsDialog(self.channels, self).exec()

    def open_history(self):
        HistoryDialog(self.history, self).exec()

    def notify(self, source, title, message):
        self.history.add(source, title, message)
        self.tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 10000)
        if self.channels.line_enabled():
            self.channels.send_line(f"{title}\n{message}")

    def closeEvent(self, event):
        event.ignore()
        self.hide()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    w = NotifyApp()
    if "--startup" not in sys.argv:
        w.show()
    sys.exit(app.exec())
