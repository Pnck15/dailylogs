import hashlib
import html
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from PySide6.QtCore import QEvent, QLockFile, QSettings, QTimer, Qt, QUrl
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QInputDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from notify_history import NotificationHistory, app_data_dir
from notify_excel import make_history_xlsx
from notify_receiver import CentralNotifyReceiver
from notify_windows_toast import NativeToastDispatcher, toast_script_path
from notify_updates import fetch_update, prepare_update
from workers import run_async


APP_VERSION = "1.5.16"
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


def clean_sa_notification_message(message):
    """Hide SA display-only metadata; never change stored Sheet/Central rows."""
    lines = []
    for line in str(message or "").splitlines():
        if re.match(r"^\s*Merged\s+D\s*:", line, flags=re.IGNORECASE):
            continue
        if re.match(r"^\s*C\s*[-–]\s*", line, flags=re.IGNORECASE):
            continue
        # Inherited D still matters, but the popup needs no merge internals.
        line = re.sub(r"\s*\(Merged D\)", "", line, flags=re.IGNORECASE)
        line = re.sub(r"\s*\(Column\s+D\)", "", line, flags=re.IGNORECASE)
        lines.append(line)
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    # Older Central events may still have date and time on two lines.
    # Normalize those display copies without changing Central or Sheets.
    return re.sub(
        r"(วันที่นัดหมาย:[^\n]+)\n\s*(เวลานัดหมาย:[^\n]+)",
        r"\1    \2",
        cleaned,
    )


def popup_content_html(message):
    """White popup, black field names, navy cell values, safe escaped HTML."""
    fragments = []
    for raw in str(message or "").splitlines():
        # The date and time must share one LINE while BOTH labels stay black.
        if raw.strip().startswith("วันที่นัดหมาย:") and "เวลานัดหมาย:" in raw:
            date_part, time_part = raw.split("เวลานัดหมาย:", 1)
            _, date_value = date_part.split("วันที่นัดหมาย:", 1)
            fragments.append(
                '<span style="color:#111827;">วันที่นัดหมาย:</span>'
                '<span style="color:#1E3A8A;font-weight:600;">'
                + html.escape(date_value.strip()) + '</span>'
                '&nbsp;&nbsp;&nbsp;'
                '<span style="color:#111827;">เวลานัดหมาย:</span>'
                '<span style="color:#1E3A8A;font-weight:600;">'
                + html.escape(time_part.strip()) + '</span>'
            )
            continue
        if ":" in raw:
            prefix, value = raw.split(":", 1)
            if value.strip():
                fragments.append(
                    '<span style="color:#111827;">'
                    + html.escape(prefix) + ':</span>'
                    + '<span style="color:#1E3A8A;font-weight:600;">'
                    + html.escape(value) + '</span>'
                )
                continue
        # Standalone section headings are labels, not cell values.
        heading = raw.strip().startswith(("ข้อมูลที่", "รายละเอียดแจ้ง", "รายการแจ้ง"))
        color = "#111827" if heading else "#1E3A8A"
        fragments.append(
            '<span style="color:' + color + ';">'
            + html.escape(raw) + '</span>'
        )
    return (
        '<html><body style="background-color:#FFFFFF;font-family:Segoe UI;">'
        + '<p style="white-space:pre-wrap;margin:0;">'
        + '<br/>'.join(fragments) + '</p></body></html>'
    )


def claim_single_notify_instance(startup=False, instance_name=None):
    """Keep one receiver per Windows user, avoiding competing auth sessions.

    If an instance is already running, a manual launch activates it, and a
    Windows startup launch exits quietly. No settings or database are changed.
    """
    if not instance_name:
        profile = os.path.normcase(os.path.expanduser("~"))
        suffix = hashlib.sha256(
            profile.encode("utf-8", errors="replace")
        ).hexdigest()[:20]
        instance_name = "MiniDailyLogNotify-" + suffix

    # QLocalServer alone is NOT an exclusive Windows lock: the Windows
    # named-pipe API can allow more than one listener using the same name.
    # QLockFile provides the atomic per-user, cross-process ownership.
    lock_hash = hashlib.sha256(
        instance_name.encode("utf-8", errors="replace")
    ).hexdigest()[:24]
    lock_path = os.path.join(app_data_dir(), lock_hash + ".lock")
    owner_lock = QLockFile(lock_path)
    owner_lock.setStaleLockTime(0)

    if not owner_lock.tryLock(0):
        # An existing process already owns the exclusive receiver lock.
        # On manual launch, failure to reach its IPC MUST be visible to
        # the user rather than causing another silent exit.
        if startup:
            return None
        probe = QLocalSocket()
        probe.connectToServer(instance_name)
        if probe.waitForConnected(1500):
            probe.write(b"activate")
            probe.flush()
            probe.waitForBytesWritten(500)
            probe.disconnectFromServer()
            return None
        raise RuntimeError(
            "พบการล็อกโปรแกรม DailyLogNotify อยู่ "
            "แต่เปิดหน้าต่างของตัวที่รันอยู่ไม่ได้ "
            "กรุณาตรวจใน Task Manager ว่ายังมี "
            "DailyLogNotify.exe เปิดอยู่หรือไม่"
        )

    server = QLocalServer()
    if not server.listen(instance_name):
        # A leftover IPC endpoint is not an active receiver because WE hold
        # the exclusive QLockFile. Cleaning this socket name is safe.
        QLocalServer.removeServer(instance_name)
        if not server.listen(instance_name):
            owner_lock.unlock()
            raise RuntimeError(
                "Cannot create DailyLogNotify local IPC endpoint"
            )

    # Keep the lock object alive as long as the server/process is running.
    server._notify_owner_lock = owner_lock
    return server


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
    """Selectable text, context-menu Copy, Excel export and confirmed delete."""
    def __init__(self, history, source_allowed=None, parent=None):
        super().__init__(parent)
        self.history = history
        self.source_allowed = source_allowed
        self.visible_rows = []
        self._history_limit = 300
        self.setWindowTitle("DailyLogNotify - ประวัติแจ้งเตือนทั้งหมด")
        self.resize(700, 490)

        root = QVBoxLayout(self)
        note = QLabel(
            "แสดงและส่งออกเฉพาะ Source ที่เครื่องนี้เลือกไว้ "
            "• สามารถลากเลือกข้อความหรือคลิกขวาเพื่อ Copy"
        )
        note.setWordWrap(True)
        root.addWidget(note)

        self.text_area = QTextEdit(self)
        self.text_area.setObjectName("selectableHistoryText")
        self.text_area.setReadOnly(True)
        self.text_area.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.text_area.setContextMenuPolicy(
            Qt.ContextMenuPolicy.DefaultContextMenu
        )
        self.text_area.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        root.addWidget(self.text_area, 1)
        self.load_more_button = QPushButton("แสดงรายการก่อนหน้าอีก 300")
        self.load_more_button.setObjectName("loadOlderNotifyHistory")
        self.load_more_button.clicked.connect(self.load_more_history)
        root.addWidget(self.load_more_button)

        self.count_label = QLabel("")
        root.addWidget(self.count_label)
        bottom = QHBoxLayout()
        self.export_button = QPushButton("ส่งออกเป็น .excel")
        self.export_button.setObjectName("exportHistoryExcelButton")
        self.clear_button = QPushButton("ล้างประวัติ (เครื่องนี้)")
        self.clear_button.setObjectName("clearNotificationHistoryButton")
        self.clear_button.setStyleSheet(
            "QPushButton { background-color: #B91C1C; color: #FFFFFF; "
            "border-radius: 5px; padding: 6px; }"
        )
        close_button = QPushButton("Close")
        self.export_button.clicked.connect(self.export_excel)
        self.clear_button.clicked.connect(self.clear_history)
        close_button.clicked.connect(self.close)
        bottom.addWidget(self.export_button)
        bottom.addWidget(self.clear_button)
        bottom.addStretch()
        bottom.addWidget(close_button)
        root.addLayout(bottom)
        self.reload()

    def load_more_history(self):
        self._history_limit += 300
        self.reload()

    def reload(self):
        # Bound the amount of SQLite text loaded into the GUI event loop.
        # Employees can page older rows while keeping selection and scrolling.
        if hasattr(self.history, "recent"):
            rows = self.history.recent(limit=self._history_limit)
        else:
            rows = self.history.all()[:self._history_limit]
        self.visible_rows = [
            item for item in rows
            if (
                not callable(self.source_allowed)
                or self.source_allowed(
                    item.get("source", ""), item.get("source_key", "")
                )
            )
        ]
        self.load_more_button.setEnabled(len(rows) >= self._history_limit)
        blocks = []
        for item in self.visible_rows:
            blocks.append(
                f"{item.get('created_at', '')}  "
                f"[{item.get('source', '')}]\n"
                f"{item.get('title', '')}\n"
                f"{item.get('message', '')}"
            )
        self.text_area.setPlainText(
            "\n\n" + ("─" * 38 + "\n\n").join(blocks)
            if blocks else "ไม่มีประวัติแจ้งเตือนสำหรับ Source ที่เลือก"
        )
        self.text_area.moveCursor(
            self.text_area.textCursor().MoveOperation.Start
        )
        self.count_label.setText(
            f"แสดง {len(self.visible_rows)} รายการตาม Source ที่เลือก"
            f" (โหลดประวัติล่าสุดไม่เกิน {self._history_limit} รายการ)"
        )
        self.export_button.setEnabled(bool(self.visible_rows))

    def export_excel(self):
        if not self.visible_rows:
            QMessageBox.information(
                self, "Notification History",
                "ไม่มีประวัติใน Source ที่เลือกสำหรับส่งออก"
            )
            return
        documents = Path.home() / "Documents"
        if not documents.is_dir():
            documents = Path.home()
        name = "DailyLogNotify_History_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self, "ส่งออกประวัติแจ้งเตือน", str(documents / name),
            "Excel Workbook (*.xlsx)"
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            # Pagination affects only on-screen rendering. Export must
            # preserve the original feature: ALL history for checked Sources.
            all_selected = [
                item for item in self.history.all()
                if (
                    not callable(self.source_allowed)
                    or self.source_allowed(
                        item.get("source", ""), item.get("source_key", "")
                    )
                )
            ]
            count = make_history_xlsx(path, all_selected)
        except (OSError, ValueError, RuntimeError) as error:
            QMessageBox.critical(
                self, "ส่งออก Excel ไม่สำเร็จ", str(error)
            )
            return
        QMessageBox.information(
            self, "ส่งออกสำเร็จ",
            f"บันทึก {count} รายการลง Excel แล้ว\n{path}"
        )

    def clear_history(self):
        choices = {
            "ล้างเมื่อวาน": "yesterday",
            "ล้างย้อนหลัง 7 วัน (ไม่รวมวันนี้)": "last_7_days",
            "ล้างรายการเก่ากว่า 7 วัน": "older_than_7_days",
            "ล้างรายการเก่ากว่า 30 วัน": "older_than_30_days",
            "ล้างทั้งหมด": "all",
        }
        selected, ok = QInputDialog.getItem(
            self, "ช่วงเวลาล้างประวัติในเครื่องนี้",
            "เลือกช่วงเวลาที่ต้องการล้าง:",
            list(choices), 0, False,
        )
        if not ok or selected not in choices:
            return
        scope = choices[selected]
        now_bkk = datetime.now(timezone(timedelta(hours=7)))
        today_start = now_bkk.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        if scope == "yesterday":
            start = today_start - timedelta(days=1)
            end = today_start
        elif scope == "last_7_days":
            start = today_start - timedelta(days=7)
            end = today_start
        elif scope == "older_than_7_days":
            start = None
            end = today_start - timedelta(days=7)
        elif scope == "older_than_30_days":
            start = None
            end = today_start - timedelta(days=30)
        else:
            start = None
            end = now_bkk + timedelta(microseconds=1)

        answer = QMessageBox.question(
            self, "ยืนยันล้างประวัติในเครื่องนี้",
            f"ล้างประวัติ: {selected}\n\n"
            "การล้างจากหน้าต่างนี้มีผลเฉพาะ SQLite บนพีซีนี้ "
            "ไม่ได้ลบเครื่องอื่นและไม่ได้ลดพื้นที่ Supabase\n\n"
            "หากต้องการล้างทุกเครื่อง ให้ Admin ใช้เมนู Central "
            "ใน DailyLog.exe\n\n"
            "รายการที่ลบไม่สามารถย้อนคืนได้ ยืนยันหรือไม่?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            count = self.history.clear_period(
                start.isoformat() if start else None, end.isoformat()
            )
        except (OSError, ValueError, RuntimeError) as error:
            QMessageBox.critical(self, "ล้างประวัติไม่สำเร็จ", str(error))
            return
        self.reload()
        self.count_label.setText(
            f"ล้างประวัติ ({selected}) ในเครื่องนี้แล้ว {count} รายการ"
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

        started = self.receiver.login(
            email,
            password,
            remember=self.remember.isChecked(),
        )
        if started is False:
            # An automatic saved-credentials login may still be active.
            # Do not trap the user on a disabled Login button forever.
            self.login_button.setEnabled(True)
            self.error_label.setText(
                "ระบบกำลังทำ Login รอบก่อนอยู่ "
                "กรุณาดูสถานะหรือกดลองอีกครั้ง"
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
    """Live, scrollable list of sources published by Central."""
    def __init__(self, settings, source_options, first_run=False, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.source_options = []
        self.first_run = first_run
        self.checkboxes = {}
        self.setWindowTitle("DailyLog Notify - Notification Sources")
        self.resize(470, 440)
        self.setModal(True)

        layout = QVBoxLayout(self)
        title = QLabel("เลือกแหล่งข้อมูลที่เครื่องนี้ต้องการรับแจ้งเตือน")
        title.setWordWrap(True)
        layout.addWidget(title)
        note = QLabel(
            "รายการจาก Supabase Central อัปเดตอัตโนมัติ "
            "หรือกด Refresh Sources เพื่อโหลดลิงก์ใหม่จาก DailyLog"
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        raw = str(settings.value("sources/selected", "") or "").strip()
        self._saved_keys = {
            key.strip() for key in raw.split(",") if key.strip()
        }

        self.source_area = QScrollArea()
        self.source_area.setWidgetResizable(True)
        self.source_container = QWidget()
        self.source_layout = QVBoxLayout(self.source_container)
        self.source_area.setWidget(self.source_container)
        layout.addWidget(self.source_area, 1)

        self.status = QLabel("เลือก Source แล้วกด Save")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.refresh_button = QPushButton("🔄 Refresh Sources")
        cancel = QPushButton("Cancel")
        self.save_button = QPushButton("Save")
        buttons.addWidget(self.refresh_button)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

        cancel.clicked.connect(self.reject)
        self.save_button.clicked.connect(self._save)
        self.update_options(source_options)

    def update_options(self, options):
        # Preserve unsaved checkbox changes during asynchronous refresh,
        # preserving saved selection on first construction.
        chosen = (
            set(self.selected_keys()) if self.checkboxes
            else set(self._saved_keys)
        )
        self.source_options = [
            item for item in (options or [])
            if isinstance(item, dict)
            and str(item.get("key", "")).strip()
            and str(item.get("label", "")).strip()
        ]
        while self.source_layout.count():
            item = self.source_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.checkboxes.clear()

        for source in self.source_options:
            key = str(source["key"]).strip()
            checkbox = QCheckBox(str(source["label"]))
            checkbox.setChecked(key in chosen)
            checkbox.toggled.connect(self._update_save_button)
            self.checkboxes[key] = checkbox
            self.source_layout.addWidget(checkbox)

        if not self.checkboxes:
            self.source_layout.addWidget(
                QLabel("Central ยังไม่เปิด Source ให้รับแจ้งเตือน")
            )
        self.source_layout.addStretch()
        self.status.setText(
            f"โหลดรายการที่รับได้ {len(self.source_options)} Sources"
        )
        self._update_save_button()

    def selected_keys(self):
        return [
            key for key, checkbox in self.checkboxes.items()
            if checkbox.isChecked()
        ]

    def _update_save_button(self, *_):
        self.save_button.setEnabled(bool(self.selected_keys()))

    def _save(self):
        selected = self.selected_keys()
        if not selected:
            QMessageBox.warning(
                self, "Notification Sources",
                "กรุณาเลือกอย่างน้อย 1 แหล่งข้อมูล"
            )
            return
        self.settings.setValue("sources/selected", ",".join(selected))
        self.settings.setValue("sources/configured", True)
        self.settings.sync()
        self.accept()


class NotifyPopup(QDialog):
    """Independent DailyLogNotify popup.

    This popup does not depend on Windows Notification settings.
    Text can be selected/copied, the user can close it with X,
    and each popup closes automatically after 26 seconds of inactivity.
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
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)

        self.history_callback = (
            history_callback
        )

        self.setMinimumWidth(405)
        self.setMaximumWidth(495)

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
                background: #FFFFFF;
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
        close_button.setObjectName("notifyPopupCloseButton")
        close_button.setStyleSheet(
            """
            QPushButton#notifyPopupCloseButton {
                background-color: #DC2626;
                color: #FFFFFF;
                border: 1px solid #B91C1C;
                border-radius: 6px;
                font-weight: bold;
                font-size: 16px;
            }
            QPushButton#notifyPopupCloseButton:hover {
                background-color: #B91C1C;
            }
            QPushButton#notifyPopupCloseButton:pressed {
                background-color: #991B1B;
            }
            """
        )
        close_button.setToolTip(
            "Close"
        )
        # QDialog.reject emits finished() as well as closing the window,
        # so the stacked popup list is updated as soon as X is clicked.
        close_button.clicked.connect(
            self.dismiss
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
        self._raw_message = str(message or "")
        self.message_box.setHtml(popup_content_html(self._raw_message))
        self.message_box.setMinimumHeight(
            75
        )
        self.message_box.setMaximumHeight(
            200
        )
        self.message_box.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        root.addWidget(
            self.message_box
        )
        # Mouse selection, keyboard copy and wheel scrolling may exceed the
        # nominal 26 second display lifetime. Suspend the timer while the
        # person is using the message area, resume when the pointer leaves.
        self.message_box.installEventFilter(self)
        self.message_box.viewport().installEventFilter(self)
        self.message_box.verticalScrollBar().installEventFilter(self)

        footer = QHBoxLayout()

        copy_button = QPushButton(
            "Copy All"
        )
        copy_button.clicked.connect(
            self.copy_all
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
            470,
            285,
        )

        self._auto_close_timer = QTimer(
            self
        )
        self._auto_close_timer.setSingleShot(
            True
        )
        self._auto_close_timer.setInterval(
            26 * 1000
        )
        self._auto_close_timer.timeout.connect(
            self.dismiss
        )
        self._auto_close_timer.start()

    def eventFilter(self, watched, event):
        if hasattr(self, "_auto_close_timer"):
            watched_items = (
                self.message_box,
                self.message_box.viewport(),
                self.message_box.verticalScrollBar(),
            )
            if watched in watched_items:
                kind = event.type()
                if kind in (
                    QEvent.Type.Enter, QEvent.Type.MouseButtonPress,
                    QEvent.Type.MouseMove, QEvent.Type.Wheel,
                    QEvent.Type.KeyPress, QEvent.Type.FocusIn,
                ):
                    self._auto_close_timer.stop()
                elif kind in (QEvent.Type.Leave, QEvent.Type.FocusOut):
                    if not self._auto_close_timer.isActive():
                        self._auto_close_timer.start()
        return super().eventFilter(watched, event)

    def dismiss(self):
        """Close on X or timeout, signalling finished for popup cleanup."""
        if self._auto_close_timer.isActive():
            self._auto_close_timer.stop()
        self.reject()

    def open_history(self):
        callback = self.history_callback
        if callable(callback):
            # An always-on-top popup must never cover a modal History window.
            # Schedule from the main event loop, not inside this button click.
            QTimer.singleShot(0, callback)
            self.dismiss()

    def copy_all(self):
        QApplication.clipboard().setText(
            self._raw_message
        )


class NotifyApp(QWidget):
    def __init__(self):
        super().__init__()

        self.settings = QSettings(
            ORG,
            APP,
        )
        self.popup_mode = str(
            self.settings.value("display/notification_mode", "bottom_right")
            or "bottom_right"
        )
        if self.popup_mode not in ("bottom_right", "bottom_left", "windows"):
            self.popup_mode = "bottom_right"
        self._recent_popup_requests = []
        self.history = NotificationHistory()
        self._pending_history_entries = []
        self._history_batch_timer = QTimer(self)
        self._history_batch_timer.setSingleShot(True)
        self._history_batch_timer.setInterval(200)
        self._history_batch_timer.timeout.connect(self._flush_history_batch)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._flush_history_batch)
        self._history_dialog = None
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
            480,
            306,
        )
        # Keep the receiver running even if every popup or main window closes.
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        app = QApplication.instance()
        if app is not None:
            app.setQuitOnLastWindowClosed(False)

        layout = QVBoxLayout(self)

        self.status = QLabel(
            "กำลังเริ่ม DailyLog Notify..."
        )
        self.status.setWordWrap(True)

        self.info = QLabel(
            "รับ Notification จาก DailyLog Central"
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

        popup_row = QHBoxLayout()
        popup_row.addWidget(QLabel("ตำแหน่งแจ้งเตือน:"))
        self.popup_mode_selector = QComboBox(self)
        self.popup_mode_selector.setObjectName("notifyDisplayMode")
        self.popup_mode_selector.addItem("มุมขวาล่าง", "bottom_right")
        self.popup_mode_selector.addItem("มุมซ้ายล่าง", "bottom_left")
        self.popup_mode_selector.addItem("Windows Notification", "windows")
        self.popup_mode_selector.setCurrentIndex(
            {"bottom_right": 0, "bottom_left": 1, "windows": 2}[self.popup_mode]
        )
        self.popup_mode_selector.setToolTip(
            "Windows Notification ขึ้นอยู่กับการตั้งค่าแจ้งเตือนของ Windows"
        )
        popup_row.addWidget(self.popup_mode_selector, 1)
        layout.addLayout(popup_row)
        self.popup_mode_selector.currentIndexChanged.connect(
            self._change_popup_mode
        )

        self.test_notification_button = QPushButton(
            "🔔 ทดสอบการแจ้งเตือน"
        )
        self.test_notification_button.setToolTip(
            "ทดสอบการแจ้งเตือนตามโหมดที่เลือก "
            "โดยไม่ต้องรอการเปลี่ยนข้อมูล Google Sheets"
        )
        self.test_notification_button.clicked.connect(self.show_test_popup)
        popup_row.addWidget(self.test_notification_button)

        layout.addLayout(
            buttons
        )

        # Explicit diagnostic/repair. Do Not Disturb is not the same as the
        # per-app WinRT ToastNotifier.Setting; never change Windows policy.
        native_buttons = QHBoxLayout()
        self.repair_toast_button = QPushButton(
            "ตรวจ/ซ่อม Windows Notification"
        )
        self.repair_toast_button.setObjectName(
            "repairWindowsNotificationButton"
        )
        self.repair_toast_button.setToolTip(
            "ลงทะเบียน Start-menu shortcut ของ DailyLogNotify ใหม่ "
            "และตรวจระดับการบล็อกของ Windows โดยไม่เปลี่ยนสิทธิ์แจ้งเตือน"
        )
        self.open_windows_notifications_button = QPushButton(
            "เปิดการตั้งค่า Notifications"
        )
        self.open_windows_notifications_button.setObjectName(
            "openWindowsNotificationsSettingsButton"
        )
        self.repair_toast_button.clicked.connect(
            self.repair_windows_notifications
        )
        self.open_windows_notifications_button.clicked.connect(
            self.open_windows_notification_settings
        )
        native_buttons.addWidget(self.repair_toast_button, 1)
        native_buttons.addWidget(self.open_windows_notifications_button, 1)
        layout.addLayout(native_buttons)

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
        self._change_popup_mode()

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

        # Qt's tray API does not own the context menu. Keep the menu
        # parented and referenced for the full tray process lifetime.
        self.tray_menu = QMenu(self)
        tray_menu = self.tray_menu

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
        self.tray.activated.connect(self._tray_activated)
        self._tray_hide_notice_shown = False

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

        # Windows Toast needs its own WinRT backend and Start-menu identity.
        # Never block the Qt GUI thread on the PowerShell/Windows API call.
        self.native_toast = NativeToastDispatcher(self)
        self.native_toast.succeeded.connect(self._native_toast_submitted)
        self.native_toast.failed.connect(self._native_toast_failed)
        self.native_toast.registration_status.connect(
            self._native_registration_status
        )
        self.native_toast.registration_error.connect(
            self._native_registration_error
        )

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
            self.receiver.history_purge.connect(
                self._apply_central_history_purge
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
        # A successful password token request is NOT the same as the
        # workspace + device being connected. Show actual failure stage.
        self.status.setText(
            "🔴 Central Notification: " + str(message or "")[:170]
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

            # Preserve legacy source labels in the old history database.
            # The selected source key is authoritative for new events.
            aliases = {label}
            for fallback in FALLBACK_SOURCE_OPTIONS:
                if fallback.get("key") == key:
                    aliases.update(fallback.get("aliases", set()))

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
                "aliases": aliases,
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

        if self.receiver is not None:
            # Push Central source updates into the OPEN dialog; employees
            # do not need to restart DailyLogNotify to select a new link.
            self.receiver.source_list_changed.connect(dialog.update_options)
            dialog.refresh_button.clicked.connect(self.receiver.refresh_sources)
        try:
            result = dialog.exec()
        finally:
            if self.receiver is not None:
                try:
                    self.receiver.source_list_changed.disconnect(dialog.update_options)
                except (RuntimeError, TypeError):
                    pass

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

        registration_state = str(
            getattr(
                self.receiver,
                "device_registration_state",
                "not_connected",
            )
            or "not_connected"
        )
        registration_label = {
            "active": "✅ Active (Heartbeat confirmed)",
            "pending": "🟡 Waiting for first heartbeat",
            "retrying": "🟡 Heartbeat failed — retrying",
            "rejected": "❌ Session not accepted by Central",
            "login_failed": "❌ Login has not completed",
            "not_connected": "❌ Not connected",
        }.get(registration_state, "⚠️ Unknown status")
        last_heartbeat = str(
            getattr(self.receiver, "last_heartbeat_at", "") or "-"
        )
        heartbeat_error = str(
            getattr(self.receiver, "last_heartbeat_error", "") or ""
        )[:200]

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
                    "Device Registration: " + registration_label,
                    "Last Heartbeat: " + last_heartbeat,
                    (
                        "Last Connection Error: " + heartbeat_error
                        if heartbeat_error
                        else "Last Connection Error: -"
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
        # A stacked always-on-top notification can otherwise cover the History
        # dialog, making its Copy and scrollbar appear unresponsive.
        for popup in tuple(self._notify_popups):
            try:
                popup.dismiss()
            except RuntimeError:
                pass
        self._flush_history_batch()
        # The History dialog is deliberately LOCAL only. Global purge is
        # exclusively available to Admin in DailyLog.exe; passing the old
        # global-purge arguments crashes HistoryDialog before it can open.
        dialog = HistoryDialog(
            self.history,
            source_allowed=self._source_allowed,
            parent=self,
        )
        self._history_dialog = dialog
        try:
            dialog.exec()
        finally:
            self._history_dialog = None

    def _flush_history_batch(self):
        if not self._pending_history_entries:
            return
        batch = self._pending_history_entries
        self._pending_history_entries = []
        try:
            self.history.add_many(batch)
        except Exception as error:
            # Never lose queued events because of a temporary local DB lock.
            self._pending_history_entries = batch + self._pending_history_entries
            print("[Notify History] local write deferred:", type(error).__name__)
            if self._history_batch_timer.isActive():
                self._history_batch_timer.stop()
            self._history_batch_timer.start(1500)

    def _apply_central_history_purge(self, payload):
        """Purge markers synchronize the local SQLite cache between PCs."""
        if not isinstance(payload, dict):
            return
        if payload.get("scope") not in (
            "yesterday", "last_7_days",
            "older_than_7_days", "older_than_30_days", "all",
        ):
            return
        self._flush_history_batch()
        try:
            deleted = self.history.clear_period(
                payload.get("start"), payload.get("end")
            )
        except (OSError, ValueError, RuntimeError) as error:
            print("[Notify Central Purge] Failed:", type(error).__name__)
            return
        if self._history_dialog is not None:
            self._history_dialog.reload()
        print(f"[Notify Central Purge] Removed {deleted} local items")

    def notify(
        self,
        source,
        title,
        message,
        show_popup=True,
        source_key="",
        event_created_at="",
    ):
        # This PC receives only sources selected locally AND currently
        # published by Admin through Central.
        if not self._source_allowed(
            source,
            source_key,
        ):
            return

        # Hide SA-only metadata in both new popup and local history.
        # Keep upstream row values, event identity and deduplication intact.
        if (
            str(source_key or "").strip().lower() == "sa_sathorn"
            or str(source or "").strip().casefold()
            in {"sa sathorn", "sa notify"}
        ):
            message = clean_sa_notification_message(message)

        if hasattr(self, "_history_batch_timer"):
            self._pending_history_entries.append({
                "source": source,
                "title": title,
                "message": message,
                "source_key": source_key,
                "event_created_at": event_created_at,
            })
            if not self._history_batch_timer.isActive():
                self._history_batch_timer.start()
        else:
            # Allow lightweight source-routing tests to reuse this method.
            self.history.add(
                source,
                title,
                message,
                source_key=source_key,
                event_created_at=event_created_at,
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
                "ทดสอบการแจ้งเตือน DailyLogNotify\n"
                "ตัวอย่างข้อมูลจากเซลล์: 12345\n"
                "คลิกและลากเลือกข้อความ หรือเลื่อนอ่านข้อความได้"
            ),
        )

    def _show_notify_popup(
        self,
        title,
        message,
        force_app_popup=False,
    ):
        # Qt QSystemTrayIcon.showMessage() can be ignored by Windows 11.
        # Submit a real WinRT Toast (with a registered AUMID) asynchronously.
        # A failed submission MUST fall back to our own Qt popup.
        if self.popup_mode == "windows" and not force_app_popup:
            self.native_toast.send(title, message)
            return

        # A GAS burst can carry hundreds of events in a minute. Persist
        # every selected event in SQLite, but cap GUI toast construction.
        now = time.monotonic()
        self._recent_popup_requests = [
            stamp for stamp in self._recent_popup_requests
            if now - stamp < 10.0
        ]
        if len(self._recent_popup_requests) >= 4:
            return
        self._recent_popup_requests.append(now)
        while len(self._notify_popups) >= 3:
            old = self._notify_popups[0]
            old.dismiss()
            # finished() normally removes it synchronously; guard races.
            if self._notify_popups and self._notify_popups[0] is old:
                self._notify_popups.pop(0)

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

    @staticmethod
    def _toast_setting_explanation(status):
        explanations = {
            "Enabled": (
                "✅ Windows อนุญาตให้ DailyLogNotify ส่ง Notification แล้ว "
                "ทดลองกด 'ทดสอบการแจ้งเตือน' อีกครั้ง"
            ),
            "DisabledForApplication": (
                "⚠️ Windows ปิด Notification เฉพาะ DailyLogNotify: "
                "เปิด Settings → System → Notifications → DailyLogNotify "
                "แล้วเปิด Notifications และ Show notification banners"
            ),
            "DisabledForUser": (
                "⚠️ Windows ปิด Notifications ทั้งบัญชี: "
                "เปิด Settings → System → Notifications และเปิดสวิตช์ "
                "Notifications หลัก (ไม่ใช่ Do Not Disturb)"
            ),
            "DisabledByGroupPolicy": (
                "⛔ Windows Group Policy ของผู้ดูแลระบบบล็อก Notifications "
                "ต้องให้ผู้ดูแล Windows แก้นโยบาย"
            ),
            "DisabledByManifest": (
                "⚠️ Windows ไม่ยอมรับตัวตนแอปสำหรับ Notification: "
                "กดตรวจ/ซ่อมเพื่อสร้าง Start-menu shortcut ใหม่ "
                "หากยังไม่หายให้ใช้ Popup ของโปรแกรมแทน"
            ),
        }
        return explanations.get(
            str(status),
            "⚠️ สถานะ Windows Notification: " + str(status)[:90]
        )

    def repair_windows_notifications(self):
        if not self.repair_toast_button.isEnabled():
            return
        self.repair_toast_button.setEnabled(False)
        self.info.setText(
            "กำลังตรวจและซ่อมการลงทะเบียน Windows Notification... "
            "ยังรับแจ้งเตือนตามปกติระหว่างตรวจ"
        )
        if not self.native_toast.repair_registration():
            self.repair_toast_button.setEnabled(True)

    def open_windows_notification_settings(self):
        ok = QDesktopServices.openUrl(QUrl("ms-settings:notifications"))
        if not ok:
            QMessageBox.information(
                self, "Windows Notifications",
                "กด Windows + I → System → Notifications "
                "และเลือก DailyLogNotify เพื่อดูสิทธิ์การแจ้งเตือน"
            )

    def _native_registration_status(self, status, _repaired):
        self.repair_toast_button.setEnabled(True)
        self.info.setText(self._toast_setting_explanation(status))
        # Intentionally do not force-enable per-user/app notification
        # preferences; only the current Windows user or IT admin may do that.

    def _native_registration_error(self, message):
        self.repair_toast_button.setEnabled(True)
        self.info.setText(
            "⚠️ ตรวจ Windows Notification ไม่สำเร็จ: "
            + str(message or "")[:190]
            + " — สามารถเลือก Popup มุมซ้าย/ขวาได้"
        )

    def _native_toast_submitted(self, _title):
        # Accepted by Windows != necessarily shown on screen. Do Not
        # Disturb/Focus Assist and per-app banner settings are external.
        if self.popup_mode == "windows":
            self.info.setText(
                "Windows รับแจ้งเตือนแล้ว — ถ้าไม่เห็น Banner "
                "ให้ตรวจ Settings → System → Notifications "
                "และปิด Do Not Disturb"
            )

    def _native_toast_failed(self, title, message, reason):
        safe_reason = str(reason or "Unknown Windows toast error")[:200]
        print("[Notify Windows Toast]", safe_reason)
        if self.popup_mode != "windows":
            return
        status_match = re.search(
            r"TOAST_SETTING:([A-Za-z]+)", safe_reason
        )
        if status_match:
            self.info.setText(
                self._toast_setting_explanation(status_match.group(1))
                + " — แสดง Popup ของโปรแกรมแทน"
            )
        else:
            self.info.setText(
                "⚠️ Windows Notification ส่งไม่สำเร็จ: "
                + safe_reason[:135]
                + " — แสดง Popup ของโปรแกรมแทน"
            )
        self._show_notify_popup(
            title, message, force_app_popup=True
        )

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
            if self.popup_mode == "bottom_left":
                x = area.left() + margin
            else:
                x = area.right() - width - margin + 1
            y = (
                y
                - height
            )

            popup.move(
                x,
                y,
            )

            y -= spacing

    def _change_popup_mode(self, _index=0):
        mode = self.popup_mode_selector.currentData()
        if mode not in ("bottom_right", "bottom_left", "windows"):
            return
        self.popup_mode = mode
        self.settings.setValue("display/notification_mode", mode)
        self.settings.sync()
        if mode == "windows":
            self.info.setText(
                "โหมด Windows Toast — กด 'ทดสอบการแจ้งเตือน' "
                "เพื่อตรวจ Windows Settings และการลงทะเบียนโปรแกรม"
            )
        else:
            self.info.setText(
                "โหมด Popup ของโปรแกรม — "
                + ("มุมซ้ายล่าง" if mode == "bottom_left" else "มุมขวาล่าง")
            )
            self._position_notify_popups()

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    def _tray_available(self):
        return (
            QSystemTrayIcon.isSystemTrayAvailable()
            and self.tray is not None
            and self.tray.isVisible()
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

        expected = f'"{sys.executable}" --startup'
        try:
            # Avoid modifying Registry on every launch if the correct
            # startup command was already installed for this Windows user.
            current = str(run.value("DailyLogNotify", "") or "")
            if current != expected:
                run.setValue("DailyLogNotify", expected)
                run.sync()

            registered = str(run.value("DailyLogNotify", "") or "")
            if (
                run.status() != QSettings.Status.NoError
                or registered != expected
            ):
                raise OSError("Windows Run registry value was not saved")

            self.startup_label.setText("✅ Start with Windows")
        except Exception as error:
            self.startup_label.setText(
                "⚠️ Start with Windows: ตั้งค่าไม่สำเร็จ"
            )
            self.startup_label.setToolTip(str(error))
            print("[Notify Startup] Registry setup failed")

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
        # X must NEVER exit or terminate the Central receiver. Only the
        # explicitly named Tray > Exit command terminates this process.
        event.ignore()
        if self._tray_available():
            self.hide()
            if not self._tray_hide_notice_shown:
                self._tray_hide_notice_shown = True
                try:
                    self.tray.showMessage(
                        "DailyLogNotify ยังทำงานอยู่",
                        "โปรแกรมยังรับแจ้งเตือนใน System Tray "
                        "กดไอคอน ^ บน Taskbar หรือดับเบิลคลิก "
                        "DailyLogNotify.exe เพื่อเปิดหน้าต่างอีกครั้ง",
                        QSystemTrayIcon.MessageIcon.Information,
                        4000,
                    )
                except Exception:
                    pass
        else:
            # Do NOT make a working receiver disappear if no tray is
            # available: leave it minimized on the Windows taskbar.
            self.showMinimized()
            self.status.setToolTip(
                "ไม่พบ Windows System Tray — "
                "หน้าต่างถูกย่อไว้ที่ Taskbar ไม่ได้ปิดโปรแกรม"
            )


if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        from notify_receiver import load_notify_config
        from supabase import create_client
        create_client(*load_notify_config())
        if not toast_script_path().is_file():
            raise SystemExit("Bundled Windows native toast helper missing")
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

    # Start with Windows and double-clicked launches share ONE session,
    # updater, notification cursor and tray process per Windows user.
    try:
        notify_instance_server = claim_single_notify_instance(
            startup="--startup" in sys.argv
        )
    except Exception as error:
        print("[Notify Single Instance]", type(error).__name__)
        if "--startup" not in sys.argv:
            QMessageBox.warning(
                None,
                "DailyLogNotify - เปิดโปรแกรมไม่ได้",
                str(error),
            )
        raise SystemExit(1) from error

    if notify_instance_server is None:
        raise SystemExit(0)

    window = NotifyApp()

    def show_existing_window():
        while notify_instance_server.hasPendingConnections():
            connection = notify_instance_server.nextPendingConnection()
            if connection is not None:
                connection.disconnectFromServer()
            window.showNormal()
            window.raise_()
            window.activateWindow()

    notify_instance_server.newConnection.connect(show_existing_window)
    app.aboutToQuit.connect(
        notify_instance_server._notify_owner_lock.unlock
    )

    if "--startup" not in sys.argv:
        window.show()

    sys.exit(
        app.exec()
    )

