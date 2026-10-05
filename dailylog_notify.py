import sys
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,QCheckBox,QDialog,QFormLayout,QHBoxLayout,QLabel,QLineEdit,
    QListWidget,QMenu,QMessageBox,QPushButton,QSystemTrayIcon,QVBoxLayout,QWidget
)
from notify_channels import NotificationChannels
from notify_history import NotificationHistory
from notify_monitor import NotifyMonitorEngine

APP_VERSION="1.0.0"; ORG="MiniDailyLog"; APP="DailyLogNotify"

class ConnectionsDialog(QDialog):
    def __init__(self,channels,parent=None):
        super().__init__(parent); self.channels=channels; self.setWindowTitle("Notification Connections"); self.setMinimumWidth(460)
        l=QVBoxLayout(self); l.addWidget(QLabel("LINE Messaging API")); f=QFormLayout()
        self.enabled=QCheckBox("เปิดส่งแจ้งเตือนไป LINE"); self.enabled.setChecked(channels.line_enabled())
        self.token=QLineEdit(channels.line_token()); self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.target=QLineEdit(channels.line_target())
        f.addRow("",self.enabled); f.addRow("Channel access token",self.token); f.addRow("User / Group ID",self.target); l.addLayout(f)
        b=QHBoxLayout(); test=QPushButton("Test LINE"); save=QPushButton("Save"); close=QPushButton("Close")
        b.addWidget(test); b.addStretch(); b.addWidget(save); b.addWidget(close); l.addLayout(b)
        save.clicked.connect(self.save); close.clicked.connect(self.close); test.clicked.connect(self.test_line)
    def save(self):
        self.channels.save_line(self.enabled.isChecked(),self.token.text(),self.target.text()); QMessageBox.information(self,"Connections","บันทึกการตั้งค่าแล้ว")
    def test_line(self):
        self.channels.save_line(self.enabled.isChecked(),self.token.text(),self.target.text())
        ok,msg=self.channels.send_line("DailyLog Notify: LINE test message")
        (QMessageBox.information if ok else QMessageBox.warning)(self,"LINE",msg)

class MonitorSettingsDialog(QDialog):
    def __init__(self,settings,reload_callback,parent=None):
        super().__init__(parent); self.settings=settings; self.reload_callback=reload_callback
        self.setWindowTitle("Monitor Connections"); self.resize(620,300); l=QVBoxLayout(self)
        l.addWidget(QLabel("Google Apps Script Web App URLs — ตรวจทุก 5 นาที"))
        f=QFormLayout(); self.inputs={}
        for branch,key in (("Sale Deli Sathorn","sathorn_url"),("Sale Deli Srinakarin","srinakarin_url"),("SA Notify","sa_url"),("MainNoti","main_noti_url")):
            e=QLineEdit(str(settings.value(key,"") or "")); e.setPlaceholderText("https://script.google.com/macros/s/.../exec")
            self.inputs[key]=e; f.addRow(branch,e)
        l.addLayout(f); b=QHBoxLayout(); save=QPushButton("Save & Start"); close=QPushButton("Close")
        b.addStretch(); b.addWidget(save); b.addWidget(close); l.addLayout(b)
        save.clicked.connect(self.save); close.clicked.connect(self.close)
    def save(self):
        for key,e in self.inputs.items():
            value=e.text().strip()
            if value and "script.google.com" not in value:
                QMessageBox.warning(self,"URL","กรุณาใช้ Apps Script Web App URL"); return
            self.settings.setValue(key,value)
        self.settings.sync(); self.reload_callback(); QMessageBox.information(self,"Monitor","บันทึกแล้ว และเริ่มตรวจสอบ Monitor")

class HistoryDialog(QDialog):
    def __init__(self,history,parent=None):
        super().__init__(parent); self.setWindowTitle("Notification History"); self.resize(620,420)
        l=QVBoxLayout(self); self.list=QListWidget(); l.addWidget(self.list)
        for dt,source,title,message in history.recent(): self.list.addItem(f"{dt} | {source or '-'} | {title}\n{message}")

class NotifyApp(QWidget):
    def __init__(self):
        super().__init__(); self.settings=QSettings(ORG,APP); self.channels=NotificationChannels(); self.history=NotificationHistory()
        self.setWindowTitle("DailyLog Notify"); self.setFixedSize(420,190)
        l=QVBoxLayout(self); self.status=QLabel("DailyLog Notify กำลังทำงาน"); self.summary=QLabel("ส่งรถวันนี้: กำลังตรวจสอบ...")
        monitor_btn=QPushButton("Monitor Connections"); connections=QPushButton("Notification Connections"); history=QPushButton("Notification History")
        l.addWidget(self.status); l.addWidget(self.summary); l.addWidget(monitor_btn); l.addWidget(connections); l.addWidget(history)
        monitor_btn.clicked.connect(self.open_monitors); connections.clicked.connect(self.open_connections); history.clicked.connect(self.open_history)
        self.engine=NotifyMonitorEngine(self.settings,self); self.engine.event.connect(self.notify)
        self.engine.summary_changed.connect(self.update_summary); self.engine.status_changed.connect(self.status.setText); self.engine.start()
        self.tray=QSystemTrayIcon(self); self.tray.setToolTip("DailyLog Notify"); menu=QMenu()
        show=QAction("Open DailyLog Notify",self); monitors=QAction("Monitor Connections",self); conn=QAction("Notification Connections",self); hist=QAction("Notification History",self); quit_a=QAction("Exit",self)
        for a in (show,monitors,conn,hist): menu.addAction(a)
        menu.addSeparator(); menu.addAction(quit_a); self.tray.setContextMenu(menu)
        show.triggered.connect(self.showNormal); monitors.triggered.connect(self.open_monitors); conn.triggered.connect(self.open_connections); hist.triggered.connect(self.open_history); quit_a.triggered.connect(QApplication.quit)
        self.tray.show(); self.enable_startup()
    def enable_startup(self):
        if not getattr(sys,"frozen",False): return
        run=QSettings(r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run",QSettings.Format.NativeFormat); run.setValue("DailyLogNotify",f'"{sys.executable}" --startup')
    def open_monitors(self): MonitorSettingsDialog(self.settings,self.engine.start,self).exec()
    def open_connections(self): ConnectionsDialog(self.channels,self).exec()
    def open_history(self): HistoryDialog(self.history,self).exec()
    def update_summary(self,sathorn,srinakarin,total): self.summary.setText(f"🚗 ส่งรถวันนี้ {total} คัน   |   Sathorn {sathorn}   Srinakarin {srinakarin}")
    def notify(self,source,title,message):
        self.history.add(source,title,message); self.tray.showMessage(title,message,QSystemTrayIcon.MessageIcon.Information,10000)
        if self.channels.line_enabled(): self.channels.send_line(f"{title}\n{message}")
    def closeEvent(self,event): event.ignore(); self.hide()

if __name__=="__main__":
    app=QApplication(sys.argv); app.setQuitOnLastWindowClosed(False); w=NotifyApp()
    if "--startup" not in sys.argv: w.show()
    sys.exit(app.exec())
