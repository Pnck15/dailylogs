import sys
import os
import shutil
import json
import uuid
from datetime import datetime, date

from PySide6.QtCore import (
    QTimer,
    Qt,
    QDate,
    QLocale,
    QSettings,
)
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QCalendarWidget,
    QStackedWidget,
    QLineEdit,
    QTextEdit,
    QMessageBox,
    QDialog,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QColorDialog,
    QFileDialog,
    QCheckBox,
)
from PySide6.QtGui import (
    QColor,
    QPalette,
    QPixmap,
    QImage,
    QTextCharFormat,
    QIcon,
)

from cloud_worker import CloudService
from workers import run_async
from sale_api_monitor import SaleAPIMonitor
from sheet_monitor import NotificationPresenter
from update_checker import UpdateChecker
from notify_channels import NotificationChannels


APP_ORGANIZATION = "MiniDailyLog"
APP_NAME = "DailyLog"
APP_DISPLAY_NAME = "GAC日記"

DEFAULT_ACCENT = "#2563EB"
APP_VERSION = "1.2.0"
DEVELOPER_CREDIT = "Developed by 王纯真"

UPDATE_CHECK_DELAY_MS = 2500

# 300000 ms = 5 นาที
SALE_MONITOR_INTERVAL_MS = 300000

SEARCH_DEBOUNCE_MS = 350


class DailyLog(QWidget):

    def __init__(self):
        super().__init__()

        self.setWindowTitle(APP_DISPLAY_NAME)

        self.expanded_width = 580
        self.expanded_height = 280
        self.collapsed_height = 33

        self.setFixedSize(
            self.expanded_width,
            self.expanded_height,
        )

        self.setWindowFlag(
            Qt.WindowType.WindowStaysOnTopHint
        )

        self.is_collapsed = False

        self.selected_date = QDate.currentDate()

        self.calendar_marked_dates = set()

        # =========================================
        # Sale & MainNoti Monitor State
        # =========================================

        self.sale_monitors = {
            "Sathorn": None,
            "Srinakarin": None,
            "SA": None,
            "MainNoti": None,
        }

        self.sale_enabled = {
            "Sathorn": False,
            "Srinakarin": False,
            "SA": False,
            "MainNoti": False,
        }

        self.sale_errors = {
            "Sathorn": False,
            "Srinakarin": False,
            "SA": False,
            "MainNoti": False,
        }

        self.sale_last_error = {
            "Sathorn": "",
            "Srinakarin": "",
            "SA": "",
            "MainNoti": "",
        }

        self.sale_last_elapsed = {
            "Sathorn": 0.0,
            "Srinakarin": 0.0,
            "SA": 0.0,
            "MainNoti": 0.0,
        }

        self.sale_notifications = []

        self.sale_due_notified = set()

        # Admin-only notification integrations (GAS / LINE)
        self.notification_channels = NotificationChannels()
        self.line_status = "idle"

        # Presentation only. This object never calls GAS.
        self.notification_presenter = NotificationPresenter(self)

        # =========================================
        # Settings
        # =========================================

        self.settings_file = (
            self._get_settings_file_path()
        )

        self.settings = QSettings(
            self.settings_file,
            QSettings.Format.IniFormat,
        )

        self._migrate_legacy_settings()

        self.current_accent = str(
            self.settings.value(
                "accent_color",
                DEFAULT_ACCENT,
            )
        )

        self.background_path = str(
            self.settings.value(
                "background_path",
                "",
            )
        )

        self.icon_path = str(
            self.settings.value(
                "icon_path",
                "",
            )
        )

        # =========================================
        # Sale API & MainNoti URLs
        # =========================================

        self.sale_api_urls = {
            "Sathorn": str(
                self.settings.value(
                    "sathorn_url",
                    "",
                )
            ).strip(),

            "Srinakarin": str(
                self.settings.value(
                    "srinakarin_url",
                    "",
                )
            ).strip(),

            "SA": str(
                self.settings.value(
                    "sa_url",
                    "",
                )
            ).strip(),

            "MainNoti": str(
                self.settings.value(
                    "main_noti_url",
                    "",
                )
            ).strip(),
        }

        # =========================================
        # Sale Monitor Timers
        # =========================================

        self.sale_sheet_timer = QTimer(self)
        self.sale_sheet_timer.setInterval(SALE_MONITOR_INTERVAL_MS)
        self.sale_sheet_timer.timeout.connect(
            lambda: self.check_sale_delivery_plan("Sathorn")
        )

        self.sale_sheet_timer_srinakarin = QTimer(self)
        self.sale_sheet_timer_srinakarin.setInterval(SALE_MONITOR_INTERVAL_MS)
        self.sale_sheet_timer_srinakarin.timeout.connect(
            lambda: self.check_sale_delivery_plan("Srinakarin")
        )

        self.sale_sheet_timer_sa = QTimer(self)
        self.sale_sheet_timer_sa.setInterval(SALE_MONITOR_INTERVAL_MS)
        self.sale_sheet_timer_sa.timeout.connect(
            lambda: self.check_sale_delivery_plan("SA")
        )

        self.sale_sheet_timer_main_noti = QTimer(self)
        self.sale_sheet_timer_main_noti.setInterval(SALE_MONITOR_INTERVAL_MS)
        self.sale_sheet_timer_main_noti.timeout.connect(
            lambda: self.check_sale_delivery_plan("MainNoti")
        )

        # =========================================
        # General State
        # =========================================

        self.background_is_dark = False

        self._workers = []

        self._cloud_pending = {}

        self._cloud_request_generation = 0

        self._main_event_last_id = 0
        self._main_event_cursor_ready = False
        self._main_event_poll_busy = False
        self.main_notification_timer = QTimer(
            self
        )
        self.main_notification_timer.setInterval(
            15000
        )
        self.main_notification_timer.timeout.connect(
            self.poll_main_notification_events
        )

        self._search_timer = QTimer(self)

        self._search_timer.setSingleShot(True)

        self._search_timer.setInterval(
            SEARCH_DEBOUNCE_MS
        )

        self._search_timer.timeout.connect(
            self._run_debounced_search
        )

        # =========================================
        # Sale Busy State
        # =========================================

        self._sale_busy = {
            "Sathorn": False,
            "Srinakarin": False,
            "SA": False,
            "MainNoti": False,
        }

        self._sale_retry_waiting = {
            "Sathorn": False,
            "Srinakarin": False,
            "SA": False,
            "MainNoti": False,
        }

        # Heavy GAS scans are serialized across all sources.
        # Pings may run in parallel, but only one action=changes call
        # is allowed at a time to avoid hammering Google Sheets/GAS.
        self._gas_scan_active = None
        self._gas_scan_queue = []

        # =========================================
        # Database / Cloud Login
        # =========================================

        self.database_ready = self.init_database()

        if not self.database_ready:
            QTimer.singleShot(
                0,
                QApplication.quit,
            )
            return

        # =========================================
        # Theme
        # =========================================

        self.apply_theme()

        # =========================================
        # Pages
        # =========================================

        self.pages = QStackedWidget()

        self.calendar_page = (
            self.create_calendar_page()
        )

        self.add_page = self.create_add_page()

        self.pages.addWidget(
            self.calendar_page
        )

        self.pages.addWidget(
            self.add_page
        )

        # =========================================
        # Header
        # =========================================

        self.title = QLabel(
            APP_DISPLAY_NAME
        )

        # Legacy MainNoti button kept only for backward-compatible
        # internal monitor helpers. Main Notification Sources now live in Menu.
        self.main_noti_button = QPushButton(
            "MainNoti",
            self,
        )
        self.main_noti_button.hide()

        self.line_status_button = QPushButton("⚪ LINE")
        self.line_status_button.clicked.connect(
            self.configure_line_notifications
        )

        # =========================================
        # Sale Deli Sathorn Button
        # =========================================

        self.sale_alert_button = QPushButton(
            "Sale Deli Sathorn"
        )

        self.sale_alert_button.clicked.connect(
            lambda: self.configure_sale_branch(
                "Sathorn"
            )
        )

        # =========================================
        # Sale Deli Srinakarin Button
        # =========================================

        self.sale_alert_button_srinakarin = (
            QPushButton(
                "Sale Deli Srinakarin"
            )
        )

        self.sale_alert_button_srinakarin.clicked.connect(
            lambda: self.configure_sale_branch(
                "Srinakarin"
            )
        )

        # =========================================
        # SA Notify Button
        # =========================================

        self.sa_notify_button = QPushButton(
            "⚪ SA Sathorn"
        )

        self.sa_notify_button.clicked.connect(
            lambda: self.configure_sale_branch(
                "SA"
            )
        )

        # =========================================
        # Header Buttons
        # =========================================

        self.menu_button = QPushButton("☰")

        self.menu_button.setFixedSize(32, 28)

        self.menu_button.clicked.connect(
            self.show_settings_menu
        )

        self.save_background_button = QPushButton(
            "💾"
        )

        self.save_background_button.setToolTip(
            "Save Background"
        )

        self.save_background_button.setFixedSize(
            32,
            28,
        )

        self.save_background_button.clicked.connect(
            self.save_background
        )

        self.collapse_button = QPushButton("−")

        self.collapse_button.setFixedSize(
            32,
            28,
        )

        self.collapse_button.clicked.connect(
            self.toggle_window
        )

        # =========================================
        # Header Layout
        # =========================================

        header = QHBoxLayout()

        header.setSpacing(6)

        header.addWidget(
            self.title
        )

        # Compact monitor status buttons.
        # Click still opens the Admin GAS configuration dialog.
        for button in (
            self.sale_alert_button,
            self.sale_alert_button_srinakarin,
            self.sa_notify_button,
            self.line_status_button,
        ):
            button.setFixedHeight(24)

        self.sale_alert_button.setFixedWidth(72)
        self.sale_alert_button_srinakarin.setFixedWidth(82)
        # Keep enough width for the status dot + "SA Sathorn".
        self.sa_notify_button.setFixedWidth(86)
        self.line_status_button.setFixedWidth(66)

        header.addWidget(self.sale_alert_button)
        header.addWidget(self.sale_alert_button_srinakarin)
        header.addWidget(self.sa_notify_button)
        header.addWidget(self.line_status_button)

        header.addStretch()

        header.addWidget(
            self.save_background_button
        )

        header.addWidget(
            self.menu_button
        )

        header.addWidget(
            self.collapse_button
        )

        # =========================================
        # Main Layout
        # =========================================

        main_layout = QVBoxLayout()

        main_layout.setContentsMargins(
            10,
            8,
            10,
            8,
        )

        main_layout.setSpacing(6)

        # =========================================
        # Assemble
        # =========================================

        main_layout.addLayout(
            header
        )

        main_layout.addWidget(
            self.pages
        )

        self.setLayout(
            main_layout
        )

        # =========================================
        # Restore
        # =========================================

        self.restore_saved_icon()

        self.move_to_bottom_right()

        self.update_daily_logs(
            self.selected_date
        )

        # =========================================
        # Start Saved Sale Monitors
        # =========================================

        self.start_saved_sale_monitors()
        self.update_line_button()

        # Sync saved GAS endpoints to Supabase Central Worker.
        QTimer.singleShot(
            3000,
            self.sync_saved_monitor_sources_to_cloud,
        )

        QTimer.singleShot(
            3500,
            self.start_main_notification_event_stream,
        )

        self.restore_saved_background()

        # =========================================
        # Program Update
        # =========================================

        QTimer.singleShot(
            UPDATE_CHECK_DELAY_MS,
            self.check_for_updates,
        )

    # =========================================
    # Program Update
    # =========================================

    def check_for_updates(self, manual=False):

        def finished(result):

            if not result.get("available"):

                if manual:
                    QMessageBox.information(
                        self,
                        "Update",
                        (
                            "คุณกำลังใช้ DailyLog "
                            "เวอร์ชันล่าสุด\n\n"
                            f"Version: {APP_VERSION}\n\n"
                            f"{DEVELOPER_CREDIT}"
                        ),
                    )

                return

            latest = result.get(
                "latest_version",
                "",
            )

            notes = result.get(
                "release_notes"
            ) or []

            download_url = result.get(
                "download_url",
                "",
            )

            sha256 = result.get(
                "sha256",
                "",
            )

            dialog = QDialog(self)

            dialog.setWindowTitle(
                "🔔 DailyLog Update"
            )

            dialog.resize(
                500,
                330,
            )

            layout = QVBoxLayout(
                dialog
            )

            layout.addWidget(
                QLabel(
                    "🔔 มีโปรแกรม DailyLog "
                    "เวอร์ชันใหม่"
                )
            )

            layout.addWidget(
                QLabel(
                    f"เวอร์ชันปัจจุบัน: {APP_VERSION}\n"
                    f"เวอร์ชันใหม่: {latest}\n\n"
                    f"{DEVELOPER_CREDIT}"
                )
            )

            notes_text = QTextEdit()

            notes_text.setReadOnly(True)

            notes_text.setPlainText(
                "\n".join(
                    f"• {n}"
                    for n in notes
                )
                if notes
                else
                "ไม่มีรายละเอียดการเปลี่ยนแปลง"
            )

            layout.addWidget(
                notes_text
            )

            buttons = QHBoxLayout()

            update_button = QPushButton(
                "อัปเดตตอนนี้"
            )

            later_button = QPushButton(
                "ภายหลัง"
            )

            buttons.addStretch()

            buttons.addWidget(
                update_button
            )

            buttons.addWidget(
                later_button
            )

            layout.addLayout(
                buttons
            )

            if not download_url:
                update_button.setEnabled(
                    False
                )

            def do_update():

                if not getattr(
                    sys,
                    "frozen",
                    False,
                ):
                    QMessageBox.information(
                        dialog,
                        "Update",
                        (
                            "Auto Update จะทำงานเมื่อ "
                            "รัน DailyLog.exe "
                            "ที่ Build แล้วเท่านั้น"
                        ),
                    )
                    return

                updater_path = os.path.join(
                    os.path.dirname(
                        sys.executable
                    ),
                    "DailyLogUpdater.exe",
                )

                if not os.path.isfile(
                    updater_path
                ):
                    QMessageBox.warning(
                        dialog,
                        "Update",
                        (
                            "ไม่พบ "
                            "DailyLogUpdater.exe\n"
                            "ให้ Build Release Phase 3 ก่อน"
                        ),
                    )
                    return

                import subprocess

                subprocess.Popen(
                    [
                        updater_path,
                        str(os.getpid()),
                        sys.executable,
                        download_url,
                        sha256,
                    ]
                )

                QApplication.quit()

            update_button.clicked.connect(
                do_update
            )

            later_button.clicked.connect(
                dialog.close
            )

            dialog.show()

            self._update_dialog = dialog

        def failed(message):

            if manual:
                QMessageBox.warning(
                    self,
                    "Update",
                    (
                        "ตรวจสอบ Update ไม่สำเร็จ\n\n"
                        f"{message}\n\n"
                        f"{DEVELOPER_CREDIT}"
                    ),
                )

        run_async(
            self,
            UpdateChecker(APP_VERSION).check,
            finished,
            failed,
        )

    # =========================================
    # Settings Path
    # =========================================

    def _get_settings_file_path(self):

        base = (
            os.environ.get("LOCALAPPDATA")
            or os.environ.get("APPDATA")
            or os.path.expanduser("~")
        )

        path = os.path.join(
            base,
            APP_ORGANIZATION,
            APP_NAME,
        )

        os.makedirs(
            path,
            exist_ok=True,
        )

        return os.path.join(
            path,
            "settings.ini",
        )

    def _migrate_legacy_settings(self):

        legacy = QSettings(
            APP_ORGANIZATION,
            APP_NAME,
        )

        keys = [
            "accent_color",
            "background_path",
            "icon_path",
            "cloud_email",
            "sathorn_url",
            "srinakarin_url",
            "sa_url",
            "main_noti_url",
            "database_path",
        ]

        changed = False

        for key in keys:

            if self.settings.value(
                key,
                None,
            ) is None:

                value = legacy.value(
                    key,
                    None,
                )

                if (
                    value is not None
                    and str(value) != ""
                ):

                    self.settings.setValue(
                        key,
                        value,
                    )

                    changed = True

        if changed:
            self.settings.sync()

    # =========================================
    # App Data
    # =========================================

    def get_app_data_dir(self):

        path = os.path.dirname(
            self.settings_file
        )

        os.makedirs(
            path,
            exist_ok=True,
        )

        return path

    # =========================================
    # Background
    # =========================================

    def restore_saved_background(self):

        settings_dir = (
            self.get_app_data_dir()
        )

        candidates = []

        if self.background_path:
            candidates.append(
                self.background_path
            )

        for ext in (
            ".png",
            ".jpg",
            ".jpeg",
            ".bmp",
            ".webp",
        ):
            candidates.append(
                os.path.join(
                    settings_dir,
                    "background" + ext,
                )
            )

        seen = set()

        for path in candidates:

            if not path:
                continue

            path = os.path.abspath(
                os.path.expanduser(path)
            )

            if path in seen:
                continue

            seen.add(path)

            if os.path.isfile(path):

                self.background_path = path

                self.settings.setValue(
                    "background_path",
                    self.background_path,
                )

                self.settings.sync()

                self.apply_background(
                    self.background_path
                )

                return

        self.background_path = ""

        self.settings.setValue(
            "background_path",
            "",
        )

        self.settings.sync()

    def choose_background(self):

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Background Image",
            "",
            (
                "Images "
                "(*.png *.jpg *.jpeg *.bmp *.webp)"
            ),
        )

        if not file_path:
            return

        file_path = os.path.abspath(
            file_path
        )

        settings_dir = (
            self.get_app_data_dir()
        )

        ext = (
            os.path.splitext(
                file_path
            )[1].lower()
            or ".png"
        )

        stored_path = os.path.join(
            settings_dir,
            "background" + ext,
        )

        try:

            for old_ext in (
                ".png",
                ".jpg",
                ".jpeg",
                ".bmp",
                ".webp",
            ):

                old_path = os.path.join(
                    settings_dir,
                    "background" + old_ext,
                )

                if (
                    old_path != stored_path
                    and os.path.isfile(old_path)
                ):
                    os.remove(old_path)

            shutil.copy2(
                file_path,
                stored_path,
            )

        except OSError as error:

            QMessageBox.warning(
                self,
                "Background Error",
                (
                    "ไม่สามารถบันทึกรูป "
                    "Background ได้\n\n"
                    f"{error}"
                ),
            )

            return

        self.background_path = stored_path

        self.settings.setValue(
            "background_path",
            self.background_path,
        )

        self.settings.sync()

        self.apply_background(
            self.background_path
        )

    def save_background(self):

        if (
            not self.background_path
            or not os.path.isfile(
                self.background_path
            )
        ):

            QMessageBox.information(
                self,
                "Background",
                "ยังไม่มี Background ที่เลือกไว้",
            )

            return

        settings_dir = (
            self.get_app_data_dir()
        )

        source = os.path.abspath(
            self.background_path
        )

        ext = (
            os.path.splitext(
                source
            )[1].lower()
            or ".png"
        )

        stored_path = os.path.join(
            settings_dir,
            "background" + ext,
        )

        try:

            if (
                os.path.abspath(source)
                != os.path.abspath(stored_path)
            ):

                for old_ext in (
                    ".png",
                    ".jpg",
                    ".jpeg",
                    ".bmp",
                    ".webp",
                ):

                    old_path = os.path.join(
                        settings_dir,
                        "background" + old_ext,
                    )

                    if (
                        old_path != stored_path
                        and os.path.isfile(old_path)
                    ):
                        os.remove(old_path)

                shutil.copy2(
                    source,
                    stored_path,
                )

            self.background_path = stored_path

            self.settings.setValue(
                "background_path",
                stored_path,
            )

            self.settings.sync()

            saved = str(
                self.settings.value(
                    "background_path",
                    "",
                )
            ).strip()

            if (
                not saved
                or not os.path.isfile(saved)
            ):
                raise OSError(
                    "ไม่พบไฟล์ Background "
                    "หลังจากบันทึก"
                )

            self.background_path = (
                os.path.abspath(saved)
            )

            self.apply_background(
                self.background_path
            )

            QMessageBox.information(
                self,
                "Background",
                (
                    "บันทึก Background "
                    "เรียบร้อยแล้ว\n\n"
                    "เก็บไว้ที่:\n"
                    f"{self.background_path}"
                ),
            )

        except OSError as error:

            QMessageBox.warning(
                self,
                "Background Error",
                (
                    "ไม่สามารถบันทึก Background "
                    "ได้\n\n"
                    f"{error}"
                ),
            )

    # =========================================
    # Theme
    # =========================================

    def apply_theme(self):

        accent = self.current_accent

        if self.background_is_dark:

            main_text = "#FFFFFF"
            border_color = "rgba(255,255,255,90)"
            glass_color = "rgba(20,20,25,125)"
            hover_color = "rgba(255,255,255,50)"

        else:

            main_text = "#111827"
            border_color = "rgba(0,0,0,65)"
            glass_color = "rgba(255,255,255,150)"
            hover_color = "rgba(255,255,255,110)"

        self.setStyleSheet(
            f"""
            DailyLog {{
                background: transparent;
                color: {main_text};
                font-family: Arial;
                font-size: 9px;
            }}

            QLabel {{
                background: transparent;
                color: {main_text};
            }}

            QPushButton {{
                background-color: {glass_color};
                color: {main_text};
                border: 1px solid {border_color};
                border-radius: 7px;
                padding: 5px 8px;
            }}

            QPushButton:hover {{
                background-color: {hover_color};
                border: 1px solid {accent};
            }}

            QPushButton:pressed {{
                background-color: rgba(0,0,0,45);
            }}

            QLineEdit {{
                background-color: {glass_color};
                color: {main_text};
                border: 1px solid {border_color};
                border-radius: 7px;
                padding: 5px 8px;
                selection-background-color: {accent};
                selection-color: white;
            }}

            QLineEdit:focus {{
                border: 1px solid {accent};
            }}

            QTextEdit {{
                background-color: {glass_color};
                color: {main_text};
                border: 1px solid {border_color};
                border-radius: 7px;
                padding: 7px;
                selection-background-color: {accent};
                selection-color: white;
            }}

            QTextEdit:focus {{
                border: 1px solid {accent};
            }}

            QStackedWidget {{
                background: transparent;
                border: none;
            }}

            QWidget {{
                background: transparent;
            }}

            QCalendarWidget {{
                background-color: transparent;
                color: {main_text};
                border: none;
            }}

            QCalendarWidget QWidget {{
                background-color: transparent;
                color: {main_text};
            }}

            QCalendarWidget QToolButton {{
                background-color: {glass_color};
                color: {main_text};
                border: 1px solid {border_color};
                border-radius: 6px;
                padding: 2px;
                font-size: 9px;
            }}

            QCalendarWidget QToolButton:hover {{
                background-color: {hover_color};
                border: 1px solid {accent};
            }}

            QCalendarWidget QMenu {{
                background-color: {glass_color};
                color: {main_text};
                border: 1px solid {border_color};
            }}

            QCalendarWidget QSpinBox {{
                background-color: {glass_color};
                color: {main_text};
                border: 1px solid {border_color};
            }}

            QCalendarWidget QAbstractItemView {{
                background-color: {glass_color};
                color: {main_text};
                selection-background-color: {accent};
                selection-color: white;
                font-size: 9px;
                padding: 0px;
                margin: 0px;
                outline: none;
            }}

            QCalendarWidget QAbstractItemView::item {{
                padding: 0px;
                margin: 0px;
            }}

            QListWidget {{
                background-color: {glass_color};
                color: {main_text};
                border: 1px solid {border_color};
                border-radius: 8px;
                padding: 5px;
                outline: none;
            }}

            QListWidget::item {{
                background-color: transparent;
                color: {main_text};
                padding: 7px;
                border-bottom: 1px solid {border_color};
            }}

            QListWidget::item:hover {{
                background-color: {hover_color};
            }}

            QListWidget::item:selected {{
                background-color: {accent};
                color: white;
                border-radius: 5px;
            }}

            QMenu {{
                background-color: {glass_color};
                color: {main_text};
                border: 1px solid {border_color};
                border-radius: 7px;
                padding: 4px;
            }}

            QMenu::item {{
                padding: 7px 25px 7px 10px;
                border-radius: 5px;
            }}

            QMenu::item:selected {{
                background-color: {accent};
                color: white;
            }}

            QMenu::separator {{
                height: 1px;
                background: {border_color};
                margin: 4px 8px;
            }}

            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 2px;
            }}

            QScrollBar::handle:vertical {{
                background: {border_color};
                border-radius: 4px;
                min-height: 25px;
            }}

            QScrollBar::handle:vertical:hover {{
                background: {accent};
            }}

            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            """
        )

        if hasattr(
            self,
            "selected_date_label",
        ):
            self.selected_date_label.setStyleSheet(
                f"""
                color: {accent};
                background: transparent;
                font-weight: bold;
                padding: 4px;
                """
            )

        if hasattr(
            self,
            "logs_title",
        ):
            self.logs_title.setStyleSheet(
                f"""
                color: {accent};
                background: transparent;
                font-size: 10px;
                font-weight: bold;
                padding: 4px;
                """
            )

        if hasattr(
            self,
            "add_date_label",
        ):
            self.add_date_label.setStyleSheet(
                f"""
                color: {accent};
                background: transparent;
                font-weight: bold;
                padding: 6px;
                """
            )

        if hasattr(
            self,
            "title",
        ):
            self.title.setStyleSheet(
                f"""
                color: {main_text};
                background: transparent;
                font-size: 12px;
                font-weight: bold;
                """
            )

        if hasattr(
            self,
            "calendar",
        ):
            self.update_calendar_log_markers()

    def detect_background_brightness(
        self,
        file_path,
    ):

        image = QImage(file_path)

        if image.isNull():
            return False

        image = image.scaled(
            50,
            50,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )

        total_brightness = 0
        pixel_count = 0

        for y in range(
            image.height()
        ):

            for x in range(
                image.width()
            ):

                color = image.pixelColor(
                    x,
                    y,
                )

                brightness = (
                    0.299 * color.red()
                    + 0.587 * color.green()
                    + 0.114 * color.blue()
                )

                total_brightness += brightness
                pixel_count += 1

        if pixel_count == 0:
            return False

        return (
            total_brightness
            / pixel_count
        ) < 128

    # =========================================
    # Icon
    # =========================================

    def restore_saved_icon(self):

        if (
            not self.icon_path
            or not os.path.isfile(
                self.icon_path
            )
        ):

            self.icon_path = ""

            self.settings.setValue(
                "icon_path",
                "",
            )

            self.settings.sync()

            return

        icon = QIcon(
            self.icon_path
        )

        if not icon.isNull():

            self.setWindowIcon(
                icon
            )

            app = QApplication.instance()

            if app is not None:
                app.setWindowIcon(
                    icon
                )

    def show_settings_menu(self):

        menu = QMenu(self)

        color_action = menu.addAction(
            "🎨 Change Program Color"
        )

        color_action.triggered.connect(
            self.change_program_color
        )

        icon_action = menu.addAction(
            "🖼 Change Program Icon (.ico)"
        )

        icon_action.triggered.connect(
            self.change_program_icon
        )

        background_action = menu.addAction(
            "🌄 Set Background Image"
        )

        background_action.triggered.connect(
            self.choose_background
        )

        save_background_action = menu.addAction(
            "💾 Save Background"
        )

        save_background_action.triggered.connect(
            self.save_background
        )

        remove_background_action = menu.addAction(
            "✕ Remove Background"
        )

        remove_background_action.triggered.connect(
            self.remove_background
        )

        menu.addSeparator()

        notify_menu = menu.addMenu(
            "🔔 Notification System Settings"
        )

        for branch, label in (
            ("Sathorn", "Sale Deli Sathorn GAS"),
            ("Srinakarin", "Sale Deli Srinakarin GAS"),
            ("SA", "SA Sathorn GAS"),
        ):
            action = notify_menu.addAction(label)
            action.triggered.connect(
                lambda checked=False, b=branch:
                self.configure_sale_branch(b)
            )

        main_sources_action = notify_menu.addAction(
            "📚 Main Notification Sources..."
        )
        main_sources_action.triggered.connect(
            self.open_main_notification_sources
        )

        devices_action = notify_menu.addAction(
            "🖥 DailyLogNotify Devices / Sessions..."
        )
        devices_action.triggered.connect(
            self.open_notify_devices_sessions
        )

        notify_menu.addSeparator()

        reconnect_menu = notify_menu.addMenu(
            "🔄 Re-connect GAS"
        )

        reconnect_all_action = reconnect_menu.addAction(
            "Re-connect all GAS"
        )
        reconnect_all_action.triggered.connect(
            self.reconnect_all_sale_monitors
        )

        reconnect_menu.addSeparator()

        for branch, label in (
            ("Sathorn", "Sale Deli Sathorn"),
            ("Srinakarin", "Sale Deli Srinakarin"),
            ("SA", "SA Sathorn"),
        ):
            action = reconnect_menu.addAction(
                f"Re-connect {label}"
            )
            action.triggered.connect(
                lambda checked=False, b=branch:
                self.reconnect_sale_monitor(b)
            )

        notify_menu.addSeparator()

        line_action = notify_menu.addAction(
            "LINE Messaging API"
        )
        line_action.triggered.connect(
            self.configure_line_notifications
        )

        menu.addSeparator()

        update_action = menu.addAction(
            "🔄 Check for Program Update"
        )

        update_action.triggered.connect(
            lambda: self.check_for_updates(
                manual=True
            )
        )

        menu.addSeparator()

        reset_color_action = menu.addAction(
            "↺ Reset Program Color"
        )

        reset_color_action.triggered.connect(
            self.reset_program_color
        )

        reset_icon_action = menu.addAction(
            "↺ Reset Program Icon"
        )

        reset_icon_action.triggered.connect(
            self.reset_program_icon
        )

        menu.exec(
            self.menu_button.mapToGlobal(
                self.menu_button.rect().bottomLeft()
            )
        )

    # =========================================
    # DailyLogNotify Devices / Sessions
    # =========================================

    def open_notify_devices_sessions(
        self,
    ):
        dialog = QDialog(
            self
        )
        dialog.setWindowTitle(
            "DailyLogNotify Devices / Sessions"
        )
        dialog.resize(
            820,
            560,
        )

        layout = QVBoxLayout(
            dialog
        )

        info = QLabel(
            "ตรวจสอบเครื่องที่ Login DailyLogNotify และออก Session รายเครื่อง\n"
            "เครื่องที่ยังเป็นเวอร์ชันเก่าจะขึ้น Unknown/Legacy จนกว่าจะอัปเดตและส่ง Heartbeat"
        )
        info.setWordWrap(
            True
        )
        layout.addWidget(
            info
        )

        session_list = QListWidget()
        layout.addWidget(
            session_list,
            2,
        )

        details = QTextEdit()
        details.setReadOnly(
            True
        )
        details.setMinimumHeight(
            180
        )
        details.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        layout.addWidget(
            details,
            1,
        )

        status = QLabel(
            ""
        )
        status.setWordWrap(
            True
        )
        layout.addWidget(
            status
        )

        buttons = QHBoxLayout()

        refresh_button = QPushButton(
            "Refresh"
        )
        logout_button = QPushButton(
            "Logout Selected Session"
        )
        close_button = QPushButton(
            "Close"
        )

        logout_button.setEnabled(
            False
        )

        buttons.addWidget(
            refresh_button
        )
        buttons.addWidget(
            logout_button
        )
        buttons.addStretch()
        buttons.addWidget(
            close_button
        )

        layout.addLayout(
            buttons
        )

        dialog._session_list = (
            session_list
        )
        dialog._details = (
            details
        )
        dialog._status = (
            status
        )
        dialog._logout_button = (
            logout_button
        )
        dialog._session_rows = {}

        def selected_changed():
            item = (
                session_list.currentItem()
            )

            if item is None:
                logout_button.setEnabled(
                    False
                )
                details.clear()
                return

            session_id = str(
                item.data(
                    Qt.ItemDataRole.UserRole
                )
                or ""
            ).strip()

            row = (
                dialog._session_rows.get(
                    session_id,
                    {}
                )
            )

            if not row:
                logout_button.setEnabled(
                    False
                )
                details.clear()
                return

            registered = bool(
                row.get(
                    "device_registered",
                    False,
                )
            )
            online = bool(
                row.get(
                    "online",
                    False,
                )
            )

            sources = row.get(
                "selected_sources",
                [],
            )

            if isinstance(
                sources,
                str,
            ):
                try:
                    sources = json.loads(
                        sources
                    )
                except Exception:
                    sources = [
                        sources
                    ]

            if not isinstance(
                sources,
                list,
            ):
                sources = []

            source_text = (
                ", ".join(
                    str(item)
                    for item in sources
                    if str(
                        item
                    ).strip()
                )
                or "-"
            )

            detail_lines = [
                (
                    "Status: 🟢 Online"
                    if online
                    else (
                        "Status: ⚪ Registered / Offline"
                        if registered
                        else "Status: ⚪ Legacy session / ยังไม่มี Device Heartbeat"
                    )
                ),
                (
                    "User: "
                    + str(
                        row.get(
                            "user_email",
                            "",
                        )
                        or "-"
                    )
                ),
                (
                    "Device: "
                    + str(
                        row.get(
                            "device_name",
                            "",
                        )
                        or "Unknown"
                    )
                ),
                (
                    "App Version: "
                    + str(
                        row.get(
                            "app_version",
                            "",
                        )
                        or "Unknown"
                    )
                ),
                (
                    "Device ID: "
                    + str(
                        row.get(
                            "device_id",
                            "",
                        )
                        or "-"
                    )
                ),
                (
                    "Session ID: "
                    + session_id
                ),
                (
                    "Session Created: "
                    + str(
                        row.get(
                            "session_created_at",
                            "",
                        )
                        or "-"
                    )
                ),
                (
                    "Session Updated: "
                    + str(
                        row.get(
                            "session_updated_at",
                            "",
                        )
                        or "-"
                    )
                ),
                (
                    "Last Heartbeat: "
                    + str(
                        row.get(
                            "last_seen_at",
                            "",
                        )
                        or "-"
                    )
                ),
                (
                    "Windows Startup: "
                    + (
                        "✅"
                        if row.get(
                            "startup_enabled",
                            False,
                        )
                        else "⚪"
                    )
                ),
                (
                    "Updater Ready: "
                    + (
                        "✅"
                        if row.get(
                            "updater_ready",
                            False,
                        )
                        else "⚪"
                    )
                ),
                (
                    "Sources: "
                    + source_text
                ),
            ]

            details.setPlainText(
                "\n".join(
                    detail_lines
                )
            )

            logout_button.setEnabled(
                True
            )

        def logout_selected():
            item = (
                session_list.currentItem()
            )

            if item is None:
                return

            session_id = str(
                item.data(
                    Qt.ItemDataRole.UserRole
                )
                or ""
            ).strip()

            row = (
                dialog._session_rows.get(
                    session_id,
                    {}
                )
            )

            if not session_id:
                return

            device_name = str(
                row.get(
                    "device_name",
                    "",
                )
                or "Unknown device"
            )
            user_email = str(
                row.get(
                    "user_email",
                    "",
                )
                or ""
            )

            answer = QMessageBox.question(
                dialog,
                "Logout DailyLogNotify Session",
                (
                    "ต้องการออก Session นี้หรือไม่?\n\n"
                    f"Device: {device_name}\n"
                    f"User: {user_email}\n"
                    f"Session: {session_id[:12]}..."
                ),
            )

            if (
                answer
                != QMessageBox.StandardButton.Yes
            ):
                return

            logout_button.setEnabled(
                False
            )
            status.setText(
                "กำลังออก Session..."
            )

            request_id = self.cloud.call(
                "revoke_notify_session",
                session_id,
            )

            self._cloud_pending[
                request_id
            ] = (
                "notify_session_revoke",
                dialog,
            )

        session_list.currentItemChanged.connect(
            lambda _current, _previous:
            selected_changed()
        )
        refresh_button.clicked.connect(
            lambda:
            self._load_notify_sessions(
                dialog
            )
        )
        logout_button.clicked.connect(
            logout_selected
        )
        close_button.clicked.connect(
            dialog.close
        )

        self._load_notify_sessions(
            dialog
        )

        dialog.exec()

    def _load_notify_sessions(
        self,
        dialog,
    ):
        if dialog is None:
            return

        dialog._status.setText(
            "กำลังโหลด DailyLogNotify Sessions..."
        )

        request_id = self.cloud.call(
            "list_notify_sessions"
        )

        self._cloud_pending[
            request_id
        ] = (
            "notify_sessions_load",
            dialog,
        )

    def _render_notify_sessions(
        self,
        dialog,
        rows,
    ):
        if dialog is None:
            return

        dialog._session_rows = {}
        dialog._session_list.clear()
        dialog._details.clear()
        dialog._logout_button.setEnabled(
            False
        )

        online_count = 0
        registered_count = 0

        for row in rows or []:
            if not isinstance(
                row,
                dict,
            ):
                continue

            session_id = str(
                row.get(
                    "session_id",
                    "",
                )
                or ""
            ).strip()

            if not session_id:
                continue

            dialog._session_rows[
                session_id
            ] = row

            registered = bool(
                row.get(
                    "device_registered",
                    False,
                )
            )
            online = bool(
                row.get(
                    "online",
                    False,
                )
            )

            if registered:
                registered_count += 1

            if online:
                online_count += 1

            icon = (
                "🟢"
                if online
                else "⚪"
            )

            device_name = str(
                row.get(
                    "device_name",
                    "",
                )
                or (
                    "Unknown device (Legacy)"
                    if not registered
                    else "Unknown device"
                )
            )

            version = str(
                row.get(
                    "app_version",
                    "",
                )
                or (
                    "Legacy"
                    if not registered
                    else "Unknown"
                )
            )

            email = str(
                row.get(
                    "user_email",
                    "",
                )
                or ""
            )

            last_seen = str(
                row.get(
                    "last_seen_at",
                    "",
                )
                or row.get(
                    "session_updated_at",
                    "",
                )
                or ""
            )

            item = QListWidgetItem(
                (
                    f"{icon} {device_name} | "
                    f"{email} | v{version}\n"
                    f"Last seen: {last_seen} | "
                    f"Session: {session_id[:12]}..."
                )
            )
            item.setData(
                Qt.ItemDataRole.UserRole,
                session_id,
            )

            dialog._session_list.addItem(
                item
            )

        total = len(
            dialog._session_rows
        )

        dialog._status.setText(
            (
                f"Sessions: {total} | "
                f"Registered devices: {registered_count} | "
                f"Online: {online_count}"
            )
        )

    # =========================================
    # Dynamic Main Notification Sources
    # =========================================

    def open_main_notification_sources(
        self,
    ):
        dialog = QDialog(
            self
        )
        dialog.setWindowTitle(
            "Main Notification Sources"
        )
        dialog.resize(
            760,
            470,
        )

        root = QHBoxLayout(
            dialog
        )

        left = QVBoxLayout()
        left.addWidget(
            QLabel(
                "Configured Sources"
            )
        )

        source_list = QListWidget()
        left.addWidget(
            source_list
        )

        left_buttons = QHBoxLayout()
        new_button = QPushButton(
            "+ New"
        )
        reload_button = QPushButton(
            "Reload"
        )
        left_buttons.addWidget(
            new_button
        )
        left_buttons.addWidget(
            reload_button
        )
        left.addLayout(
            left_buttons
        )

        root.addLayout(
            left,
            1,
        )

        right = QVBoxLayout()

        right.addWidget(
            QLabel(
                "Source Name"
            )
        )
        name_input = QLineEdit()
        name_input.setPlaceholderText(
            "เช่น Finance Status / Booking / Stock"
        )
        right.addWidget(
            name_input
        )

        right.addWidget(
            QLabel(
                "Apps Script Web App URL"
            )
        )
        url_input = QLineEdit()
        url_input.setPlaceholderText(
            "https://script.google.com/macros/s/.../exec"
        )
        right.addWidget(
            url_input
        )

        enabled_check = QCheckBox(
            "Enable monitoring"
        )
        enabled_check.setChecked(
            True
        )

        notify_check = QCheckBox(
            "Show this Source in DailyLogNotify"
        )
        notify_check.setChecked(
            False
        )

        right.addWidget(
            enabled_check
        )
        right.addWidget(
            notify_check
        )

        explain = QLabel(
            "ถ้าไม่ติ๊ก DailyLogNotify: Event ยังเข้า DailyLog.exe "
            "ผ่าน Central แต่จะไม่ปรากฏเป็นตัวเลือกในเครื่องพนักงาน"
        )
        explain.setWordWrap(
            True
        )
        right.addWidget(
            explain
        )

        status = QLabel("")
        status.setWordWrap(
            True
        )
        right.addWidget(
            status
        )

        right.addStretch()

        buttons = QHBoxLayout()

        test_button = QPushButton(
            "Test Connection"
        )
        save_button = QPushButton(
            "Save"
        )
        delete_button = QPushButton(
            "Delete"
        )
        close_button = QPushButton(
            "Close"
        )

        buttons.addWidget(
            test_button
        )
        buttons.addWidget(
            save_button
        )
        buttons.addWidget(
            delete_button
        )
        buttons.addStretch()
        buttons.addWidget(
            close_button
        )
        right.addLayout(
            buttons
        )

        root.addLayout(
            right,
            2,
        )

        dialog._source_list = (
            source_list
        )
        dialog._name_input = (
            name_input
        )
        dialog._url_input = (
            url_input
        )
        dialog._enabled_check = (
            enabled_check
        )
        dialog._notify_check = (
            notify_check
        )
        dialog._status = status
        dialog._source_rows = {}
        dialog._source_key = ""

        def clear_form():
            dialog._source_key = ""
            source_list.clearSelection()
            name_input.clear()
            url_input.clear()
            enabled_check.setChecked(
                True
            )
            notify_check.setChecked(
                False
            )
            delete_button.setEnabled(
                False
            )
            status.setText(
                "สร้าง Source ใหม่"
            )

        def select_source():
            item = (
                source_list.currentItem()
            )

            if item is None:
                return

            key = str(
                item.data(
                    Qt.ItemDataRole.UserRole
                )
                or ""
            )

            row = (
                dialog._source_rows.get(
                    key
                )
            )

            if not row:
                return

            dialog._source_key = key

            name_input.setText(
                str(
                    row.get(
                        "source_name",
                        "",
                    )
                    or ""
                )
            )
            url_input.setText(
                str(
                    row.get(
                        "gas_url",
                        "",
                    )
                    or ""
                )
            )
            enabled_check.setChecked(
                bool(
                    row.get(
                        "enabled",
                        True,
                    )
                )
            )
            notify_check.setChecked(
                bool(
                    row.get(
                        "publish_to_notify",
                        False,
                    )
                )
            )
            delete_button.setEnabled(
                True
            )
            status.setText(
                f"Source key: {key}"
            )

        def test_connection():
            url = (
                url_input.text()
                .strip()
                .replace(
                    "https:https://",
                    "https://",
                    1,
                )
            )

            if not url:
                QMessageBox.warning(
                    dialog,
                    "Main Notification Source",
                    "กรุณาใส่ Apps Script Web App URL",
                )
                return

            if (
                "docs.google.com/spreadsheets"
                in url
                or "/spreadsheets/d/"
                in url
            ):
                QMessageBox.warning(
                    dialog,
                    "URL ไม่ถูกต้อง",
                    (
                        "ต้องใช้ Apps Script Web App URL "
                        "ที่ลงท้ายด้วย /exec"
                    ),
                )
                return

            status.setText(
                "กำลังทดสอบ Connection..."
            )
            test_button.setEnabled(
                False
            )

            monitor = SaleAPIMonitor(
                url
            )

            def ok(result):
                test_button.setEnabled(
                    True
                )
                version = str(
                    result.get(
                        "version",
                        "",
                    )
                    or ""
                ).strip()
                status.setText(
                    "✅ Connection สำเร็จ"
                    + (
                        f" | API: {version}"
                        if version
                        else ""
                    )
                )

            def failed(message):
                test_button.setEnabled(
                    True
                )
                status.setText(
                    "❌ Connection ไม่สำเร็จ\n"
                    f"{message}"
                )

            run_async(
                self,
                monitor.ping,
                ok,
                failed,
            )

        def save_source():
            name = (
                name_input.text()
                .strip()
            )
            url = (
                url_input.text()
                .strip()
                .replace(
                    "https:https://",
                    "https://",
                    1,
                )
            )

            if not name or not url:
                QMessageBox.warning(
                    dialog,
                    "Main Notification Source",
                    "กรุณาใส่ Source Name และ Web App URL",
                )
                return

            if (
                "docs.google.com/spreadsheets"
                in url
                or "/spreadsheets/d/"
                in url
                or not url.startswith(
                    (
                        "http://",
                        "https://",
                    )
                )
            ):
                QMessageBox.warning(
                    dialog,
                    "URL ไม่ถูกต้อง",
                    (
                        "ต้องใช้ Apps Script Web App URL "
                        "ที่ลงท้ายด้วย /exec"
                    ),
                )
                return

            source_key = (
                dialog._source_key
                or (
                    "main_"
                    + uuid.uuid4().hex[:12]
                )
            )

            existing = (
                dialog._source_rows.get(
                    source_key,
                    {}
                )
            )

            display_order = int(
                existing.get(
                    "display_order",
                    200
                    + len(
                        dialog._source_rows
                    ),
                )
                or 200
            )

            status.setText(
                "กำลังบันทึก..."
            )
            save_button.setEnabled(
                False
            )

            request_id = self.cloud.call(
                "upsert_monitor_source",
                source_key,
                name,
                "structured",
                url,
                enabled_check.isChecked(),
                notify_check.isChecked(),
                display_order,
            )

            self._cloud_pending[
                request_id
            ] = (
                "main_source_save",
                dialog,
            )

        def delete_source():
            source_key = (
                dialog._source_key
            )

            if not source_key:
                return

            answer = QMessageBox.question(
                dialog,
                "Delete Main Notification Source",
                (
                    "ต้องการลบ Source นี้หรือไม่?\n\n"
                    f"{name_input.text().strip()}"
                ),
            )

            if (
                answer
                != QMessageBox.StandardButton.Yes
            ):
                return

            status.setText(
                "กำลังลบ..."
            )

            request_id = self.cloud.call(
                "delete_monitor_source",
                source_key,
            )

            self._cloud_pending[
                request_id
            ] = (
                "main_source_delete",
                dialog,
            )

        source_list.currentItemChanged.connect(
            lambda _current, _previous:
            select_source()
        )
        new_button.clicked.connect(
            clear_form
        )
        reload_button.clicked.connect(
            lambda:
            self._load_main_notification_sources(
                dialog
            )
        )
        test_button.clicked.connect(
            test_connection
        )
        save_button.clicked.connect(
            save_source
        )
        delete_button.clicked.connect(
            delete_source
        )
        close_button.clicked.connect(
            dialog.close
        )

        delete_button.setEnabled(
            False
        )

        self._load_main_notification_sources(
            dialog
        )

        dialog.exec()

    def _load_main_notification_sources(
        self,
        dialog,
    ):
        if (
            dialog is None
            or not dialog.isVisible()
        ):
            # During initial open exec() has not started yet, but the
            # dialog object is still valid. Continue unless deleted.
            pass

        dialog._status.setText(
            "กำลังโหลด Sources..."
        )

        request_id = self.cloud.call(
            "list_monitor_sources"
        )

        self._cloud_pending[
            request_id
        ] = (
            "main_sources_load",
            dialog,
        )

    def _render_main_notification_sources(
        self,
        dialog,
        rows,
    ):
        if dialog is None:
            return

        source_rows = {}

        for row in rows or []:
            if not isinstance(
                row,
                dict,
            ):
                continue

            key = str(
                row.get(
                    "source_key",
                    "",
                )
                or ""
            ).strip()

            if not key.startswith(
                "main_"
            ):
                continue

            source_rows[
                key
            ] = row

        dialog._source_rows = (
            source_rows
        )
        dialog._source_list.clear()

        for key, row in source_rows.items():
            name = str(
                row.get(
                    "source_name",
                    key,
                )
                or key
            )

            enabled = bool(
                row.get(
                    "enabled",
                    True,
                )
            )
            to_notify = bool(
                row.get(
                    "publish_to_notify",
                    False,
                )
            )

            marks = (
                ("🟢" if enabled else "⚪")
                + (" 🔔" if to_notify else "")
            )

            item = QListWidgetItem(
                f"{marks} {name}"
            )
            item.setData(
                Qt.ItemDataRole.UserRole,
                key,
            )
            dialog._source_list.addItem(
                item
            )

        dialog._status.setText(
            (
                f"โหลดแล้ว {len(source_rows)} Sources"
                if source_rows
                else "ยังไม่มี Main Notification Source"
            )
        )

    # =========================================
    # Central Main Notification Event Stream
    # =========================================

    def start_main_notification_event_stream(
        self,
    ):
        saved = self.settings.value(
            "main_notifications_last_event_id",
            None,
        )

        if saved is None:
            request_id = self.cloud.call(
                "get_latest_main_notification_event_id"
            )
            self._cloud_pending[
                request_id
            ] = (
                "main_event_cursor_init",
                None,
            )
            return

        try:
            self._main_event_last_id = int(
                saved
            )
        except (
            TypeError,
            ValueError,
        ):
            self._main_event_last_id = 0

        self._main_event_cursor_ready = (
            True
        )

        if not self.main_notification_timer.isActive():
            self.main_notification_timer.start()

        self.poll_main_notification_events()

    def poll_main_notification_events(
        self,
    ):
        if (
            not self._main_event_cursor_ready
            or self._main_event_poll_busy
        ):
            return

        self._main_event_poll_busy = True

        request_id = self.cloud.call(
            "get_main_notification_events_after",
            self._main_event_last_id,
        )

        self._cloud_pending[
            request_id
        ] = (
            "main_events",
            None,
        )

    def _process_main_notification_events(
        self,
        rows,
    ):
        for row in rows or []:
            if not isinstance(
                row,
                dict,
            ):
                continue

            try:
                event_id = int(
                    row.get(
                        "id",
                        0,
                    )
                    or 0
                )
            except (
                TypeError,
                ValueError,
            ):
                event_id = 0

            title = str(
                row.get(
                    "title",
                    "Main Notification",
                )
                or "Main Notification"
            )

            message = str(
                row.get(
                    "message",
                    "",
                )
                or ""
            )

            notification_type = str(
                row.get(
                    "notification_type",
                    "info",
                )
                or "info"
            )

            show_popup = True

            created_at = str(
                row.get(
                    "created_at",
                    "",
                )
                or ""
            ).strip()

            if created_at:
                try:
                    parsed = datetime.fromisoformat(
                        created_at.replace(
                            "Z",
                            "+00:00",
                        )
                    )
                    show_popup = (
                        parsed.astimezone().date()
                        ==
                        datetime.now().astimezone().date()
                    )
                except ValueError:
                    show_popup = True

            self.add_sale_notification(
                title,
                message,
                notification_type,
                show_toast=show_popup,
            )

            if (
                event_id
                > self._main_event_last_id
            ):
                self._main_event_last_id = (
                    event_id
                )

        self.settings.setValue(
            "main_notifications_last_event_id",
            self._main_event_last_id,
        )
        self.settings.sync()

    def update_line_button(self):

        enabled = self.notification_channels.line_enabled()
        token = self.notification_channels.line_token()
        target = self.notification_channels.line_target()

        if self.line_status == "busy":
            dot = "🟡"
            tip = "กำลังตรวจสอบ LINE"
        elif self.line_status == "error":
            dot = "🔴"
            tip = "LINE เชื่อมต่อหรือส่งข้อความไม่สำเร็จ"
        elif enabled and token and target:
            dot = "🟢"
            tip = "LINE พร้อมทำงาน"
        elif enabled:
            dot = "🔴"
            tip = "เปิด LINE แล้ว แต่ Token หรือ Target ID ไม่ครบ"
        else:
            dot = "⚪"
            tip = "LINE ยังไม่ได้เปิดใช้งาน"

        self.line_status_button.setText(f"{dot} LINE")
        self.line_status_button.setToolTip(tip)

    def configure_line_notifications(self):

        dialog = QDialog(self)
        dialog.setWindowTitle("LINE Messaging API")
        dialog.resize(520, 250)

        layout = QVBoxLayout(dialog)

        enabled = QCheckBox(
            "เปิดส่ง Notification ไป LINE"
        )
        enabled.setChecked(
            self.notification_channels.line_enabled()
        )

        token = QLineEdit(
            self.notification_channels.line_token()
        )
        token.setEchoMode(
            QLineEdit.EchoMode.Password
        )
        token.setPlaceholderText(
            "Channel access token"
        )

        target = QLineEdit(
            self.notification_channels.line_target()
        )
        target.setPlaceholderText(
            "User ID / Group ID"
        )

        layout.addWidget(enabled)
        layout.addWidget(QLabel("Channel access token"))
        layout.addWidget(token)
        layout.addWidget(QLabel("User / Group ID"))
        layout.addWidget(target)

        buttons = QHBoxLayout()
        test_button = QPushButton("Test LINE")
        save_button = QPushButton("Save")
        close_button = QPushButton("Close")
        buttons.addWidget(test_button)
        buttons.addStretch()
        buttons.addWidget(save_button)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        def save():
            self.notification_channels.save_line(
                enabled.isChecked(),
                token.text(),
                target.text(),
            )
            self.line_status = "idle"
            self.update_line_button()
            QMessageBox.information(
                dialog,
                "LINE",
                "บันทึกการตั้งค่าแล้ว",
            )

        def test():
            self.notification_channels.save_line(
                enabled.isChecked(),
                token.text(),
                target.text(),
            )
            self.line_status = "busy"
            self.update_line_button()
            QApplication.processEvents()
            ok, message = self.notification_channels.send_line(
                "DailyLog: LINE test message"
            )
            self.line_status = "idle" if ok else "error"
            self.update_line_button()
            if ok:
                QMessageBox.information(
                    dialog,
                    "LINE",
                    message,
                )
            else:
                QMessageBox.warning(
                    dialog,
                    "LINE",
                    message,
                )

        save_button.clicked.connect(save)
        test_button.clicked.connect(test)
        close_button.clicked.connect(dialog.close)
        dialog.exec()

    def change_program_color(self):

        color = QColorDialog.getColor(
            QColor(self.current_accent),
            self,
            "Choose Program Color",
        )

        if color.isValid():

            self.current_accent = (
                color.name()
            )

            self.settings.setValue(
                "accent_color",
                self.current_accent,
            )

            self.settings.sync()

            self.apply_theme()

    def reset_program_color(self):

        self.current_accent = (
            DEFAULT_ACCENT
        )

        self.settings.setValue(
            "accent_color",
            self.current_accent,
        )

        self.settings.sync()

        self.apply_theme()

    def change_program_icon(self):

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Program Icon",
            "",
            "ICO files (*.ico)",
        )

        if not file_path:
            return

        file_path = os.path.abspath(
            file_path
        )

        icon = QIcon(file_path)

        if icon.isNull():

            QMessageBox.warning(
                self,
                "Icon Error",
                "ไม่สามารถเปิดไฟล์ .ico นี้ได้",
            )

            return

        self.icon_path = file_path

        self.settings.setValue(
            "icon_path",
            self.icon_path,
        )

        self.settings.sync()

        self.setWindowIcon(
            icon
        )

        app = QApplication.instance()

        if app is not None:
            app.setWindowIcon(
                icon
            )

    def reset_program_icon(self):

        self.icon_path = ""

        self.settings.setValue(
            "icon_path",
            "",
        )

        self.settings.sync()

        self.setWindowIcon(
            QIcon()
        )

        app = QApplication.instance()

        if app is not None:
            app.setWindowIcon(
                QIcon()
            )

    # =========================================
    # Background Apply
    # =========================================

    def apply_background(
        self,
        file_path,
    ):

        if (
            not file_path
            or not os.path.isfile(file_path)
        ):
            return

        pixmap = QPixmap(
            file_path
        )

        if pixmap.isNull():

            QMessageBox.warning(
                self,
                "Background Error",
                "ไม่สามารถเปิดรูปภาพนี้ได้",
            )

            return

        self.background_path = (
            os.path.abspath(file_path)
        )

        self.settings.setValue(
            "background_path",
            self.background_path,
        )

        self.settings.sync()

        self.background_is_dark = (
            self.detect_background_brightness(
                self.background_path
            )
        )

        self.apply_theme()

        scaled_pixmap = pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )

        x = max(
            0,
            (
                scaled_pixmap.width()
                - self.width()
            )
            // 2,
        )

        y = max(
            0,
            (
                scaled_pixmap.height()
                - self.height()
            )
            // 2,
        )

        scaled_pixmap = scaled_pixmap.copy(
            x,
            y,
            self.width(),
            self.height(),
        )

        palette = self.palette()

        palette.setBrush(
            QPalette.ColorRole.Window,
            scaled_pixmap,
        )

        self.setPalette(
            palette
        )

        self.setAutoFillBackground(
            True
        )

        self.update_calendar_log_markers()

    def remove_background(self):

        self.background_path = ""

        self.background_is_dark = False

        self.settings.setValue(
            "background_path",
            "",
        )

        self.settings.sync()

        self.setAutoFillBackground(
            False
        )

        self.setPalette(
            QApplication.palette()
        )

        self.apply_theme()

    # =========================================
    # Cloud Database
    # =========================================

    def init_database(self):

        try:

            self.cloud = CloudService(self)

            dialog = QDialog(self)

            dialog.setWindowTitle(
                "DailyLog Login"
            )

            dialog.setModal(True)

            dialog.resize(
                360,
                220,
            )

            layout = QVBoxLayout(
                dialog
            )

            login_error = QLabel("")

            login_error.setWordWrap(
                True
            )

            login_error.setStyleSheet(
                "color: #DC2626;"
            )

            layout.addWidget(
                login_error
            )

            email_label = QLabel(
                "Email"
            )

            email_input = QLineEdit()

            remember_email_state = (
                self.settings.value(
                    "remember_email",
                    True,
                    type=bool,
                )
            )

            remember_pass_state = (
                self.settings.value(
                    "remember_password",
                    False,
                    type=bool,
                )
            )

            saved_email = (
                str(
                    self.settings.value(
                        "cloud_email",
                        "",
                    )
                ).strip()
                if remember_email_state
                else ""
            )

            saved_pass = (
                str(
                    self.settings.value(
                        "cloud_password",
                        "",
                    )
                )
                if remember_pass_state
                else ""
            )

            email_input.setText(
                saved_email
            )

            email_input.setPlaceholderText(
                "your@email.com"
            )

            password_label = QLabel(
                "Password"
            )

            password_input = QLineEdit()

            password_input.setText(
                saved_pass
            )

            password_input.setEchoMode(
                QLineEdit.EchoMode.Password
            )

            password_input.setPlaceholderText(
                "Password"
            )

            cb_layout = QHBoxLayout()

            remember_email_cb = QCheckBox(
                "Remember Email"
            )

            remember_email_cb.setChecked(
                remember_email_state
            )

            remember_pass_cb = QCheckBox(
                "Remember Password"
            )

            remember_pass_cb.setChecked(
                remember_pass_state
            )

            cb_layout.addWidget(
                remember_email_cb
            )

            cb_layout.addWidget(
                remember_pass_cb
            )

            buttons = QHBoxLayout()

            buttons.addStretch()

            cancel_button = QPushButton(
                "Cancel"
            )

            login_button = QPushButton(
                "OK"
            )

            buttons.addWidget(
                cancel_button
            )

            buttons.addWidget(
                login_button
            )

            layout.addWidget(
                email_label
            )

            layout.addWidget(
                email_input
            )

            layout.addWidget(
                password_label
            )

            layout.addWidget(
                password_input
            )

            layout.addLayout(
                cb_layout
            )

            layout.addStretch()

            layout.addLayout(
                buttons
            )

            login_request = {
                "id": None
            }

            def on_login_success(
                request_id,
                operation,
                result,
            ):

                if (
                    operation != "login"
                    or request_id
                    != login_request["id"]
                ):
                    return

                if remember_email_cb.isChecked():

                    self.settings.setValue(
                        "cloud_email",
                        email_input.text().strip(),
                    )

                    self.settings.setValue(
                        "remember_email",
                        True,
                    )

                else:

                    self.settings.setValue(
                        "cloud_email",
                        "",
                    )

                    self.settings.setValue(
                        "remember_email",
                        False,
                    )

                if remember_pass_cb.isChecked():

                    self.settings.setValue(
                        "cloud_password",
                        password_input.text(),
                    )

                    self.settings.setValue(
                        "remember_password",
                        True,
                    )

                else:

                    self.settings.setValue(
                        "cloud_password",
                        "",
                    )

                    self.settings.setValue(
                        "remember_password",
                        False,
                    )

                self.settings.sync()

                dialog.accept()

            def on_login_error(
                request_id,
                operation,
                message,
            ):

                if (
                    operation != "login"
                    or request_id
                    != login_request["id"]
                ):
                    return

                login_error.setText(
                    f"Login ไม่สำเร็จ: {message}"
                )

                login_button.setEnabled(
                    True
                )

                login_button.setText(
                    "OK"
                )

                if not remember_pass_cb.isChecked():
                    password_input.clear()

                password_input.setFocus()

            self.cloud.result.connect(
                on_login_success
            )

            self.cloud.error.connect(
                on_login_error
            )

            self.cloud.result.connect(
                self._on_cloud_result
            )

            self.cloud.error.connect(
                self._on_cloud_error
            )

            def do_login():

                email = (
                    email_input.text().strip()
                )

                password = (
                    password_input.text()
                )

                if not email or not password:

                    login_error.setText(
                        "กรุณากรอก Email และ Password"
                    )

                    return

                login_button.setEnabled(
                    False
                )

                login_button.setText(
                    "กำลัง Login..."
                )

                login_error.setText(
                    (
                        "กำลังเชื่อมต่อ Cloud... "
                        "(หน้าต่างยังตอบสนองได้)"
                    )
                )

                login_request["id"] = (
                    self.cloud.login(
                        email,
                        password,
                    )
                )

            cancel_button.clicked.connect(
                dialog.reject
            )

            login_button.clicked.connect(
                do_login
            )

            password_input.returnPressed.connect(
                do_login
            )

            email_input.returnPressed.connect(
                lambda: password_input.setFocus()
            )

            if (
                dialog.exec()
                != QDialog.DialogCode.Accepted
            ):

                self.cloud.stop()

                return False

            return True

        except Exception as error:

            try:
                self.cloud.stop()
            except Exception:
                pass

            QMessageBox.critical(
                self,
                "Cloud Database Error",
                (
                    "ไม่สามารถเชื่อมต่อ "
                    "DailyLog Cloud ได้\n\n"
                    f"รายละเอียด: {error}"
                ),
            )

            return False

    # =========================================
    # Calendar
    # =========================================

    def create_calendar_page(self):

        page = QWidget()

        main_layout = QHBoxLayout()

        main_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        main_layout.setSpacing(10)

        calendar_container = QWidget()

        calendar_layout = QVBoxLayout()

        calendar_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        calendar_layout.setSpacing(8)

        self.selected_date_label = QLabel()

        self.selected_date_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.calendar = QCalendarWidget()

        self.calendar.setGridVisible(
            True
        )

        self.calendar.setLocale(
            QLocale(
                QLocale.Language.English,
                QLocale.Country.UnitedStates,
            )
        )

        self.calendar.setSelectedDate(
            self.selected_date
        )

        self.calendar.setVerticalHeaderFormat(
            QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
        )

        self.calendar.setMinimumWidth(
            200
        )

        self.calendar.setMaximumWidth(
            230
        )

        self.calendar.setMinimumHeight(
            165
        )

        self.calendar.setMaximumHeight(
            195
        )

        self.calendar.currentPageChanged.connect(
            self.calendar_page_changed
        )

        self.update_calendar_log_markers()

        self.calendar.clicked.connect(
            self.date_selected
        )

        self.calendar.activated.connect(
            self.open_daily_logs
        )

        # =========================================
        # แถบล่างของปฏิทิน: กล่อง Search (ซ้าย) + ปุ่ม +Add log (ขวา)
        # =========================================

        add_search_layout = QHBoxLayout()
        add_search_layout.setSpacing(6)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search...")
        self.search_input.setFixedHeight(32)
        self.search_input.textChanged.connect(self._schedule_search)

        self.add_button = QPushButton("+ Add Log")
        self.add_button.setFixedHeight(32)
        self.add_button.clicked.connect(self.open_add_page)

        add_search_layout.addWidget(self.search_input)
        add_search_layout.addWidget(self.add_button)

        calendar_layout.addWidget(
            self.selected_date_label
        )

        calendar_layout.addWidget(
            self.calendar,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )

        calendar_layout.addLayout(
            add_search_layout
        )

        calendar_layout.addStretch()

        calendar_container.setLayout(
            calendar_layout
        )

        logs_container = QWidget()

        logs_layout = QVBoxLayout()

        logs_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        logs_layout.setSpacing(5)

        self.logs_title = QLabel(
            "Logs"
        )

        self.logs_list = QListWidget()

        self.logs_list.itemDoubleClicked.connect(
            self.edit_log_from_list
        )

        logs_layout.addWidget(
            self.logs_title
        )

        logs_layout.addWidget(
            self.logs_list
        )

        logs_container.setLayout(
            logs_layout
        )

        logs_container.setMinimumWidth(150)

        # =========================================
        # Sale Delivery Notifications - right panel
        # =========================================

        self.notification_container = QWidget()

        notification_layout = QVBoxLayout(
            self.notification_container
        )

        notification_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        notification_layout.setSpacing(5)

        self.notification_title = QLabel(
            "🔔 Notification Logs"
        )
        self.notification_title.setStyleSheet(
            "font-weight: bold; padding: 4px;"
        )

        self.notification_list = QListWidget()
        self.notification_list.setWordWrap(True)
        self.notification_list.setTextElideMode(
            Qt.TextElideMode.ElideNone
        )
        self.notification_list.setSpacing(4)
        self.notification_list.setUniformItemSizes(False)

        self.notification_presenter.set_central_list(
            self.notification_list
        )

        notification_layout.addWidget(
            self.notification_title
        )

        notification_layout.addWidget(
            self.notification_list
        )

        self.notification_container.setMinimumWidth(120)

        main_layout.addWidget(
            calendar_container,
            0,
        )

        main_layout.addWidget(
            logs_container,
            1,
        )

        main_layout.addWidget(
            self.notification_container,
            1,
        )

        page.setLayout(
            main_layout
        )

        self.update_selected_date(
            self.selected_date
        )

        return page

    def calendar_page_changed(
        self,
        year,
        month,
    ):
        self.update_calendar_log_markers()

    def update_calendar_log_markers(self):

        if not hasattr(
            self,
            "calendar",
        ):
            return

        for date_string in (
            self.calendar_marked_dates
        ):

            date = QDate.fromString(
                date_string,
                "yyyy-MM-dd",
            )

            if date.isValid():
                self.calendar.setDateTextFormat(
                    date,
                    QTextCharFormat(),
                )

        self.calendar_marked_dates.clear()

        request_id = (
            self.cloud.get_log_dates()
        )

        self._cloud_pending[
            request_id
        ] = (
            "calendar_dates",
            None,
        )

    def _render_calendar_log_markers(
        self,
        log_dates,
    ):

        year = self.calendar.yearShown()

        month = self.calendar.monthShown()

        first_date = QDate(
            year,
            month,
            1,
        )

        first_day_of_week = (
            self.calendar.locale()
            .firstDayOfWeek()
            .value
        )

        offset = (
            first_date.dayOfWeek()
            - first_day_of_week
        ) % 7

        display_start = (
            first_date.addDays(
                -offset
            )
        )

        for day_offset in range(42):

            current_date = (
                display_start.addDays(
                    day_offset
                )
            )

            date_string = (
                current_date.toString(
                    "yyyy-MM-dd"
                )
            )

            is_sunday = (
                current_date.dayOfWeek()
                == 7
            )

            has_log = (
                date_string
                in log_dates
            )

            if (
                not is_sunday
                and not has_log
            ):
                continue

            fmt = QTextCharFormat()

            if is_sunday:

                fmt.setForeground(
                    QColor("#EF4444")
                )

            elif has_log:

                fmt.setForeground(
                    QColor("#FFFFFF")
                    if self.background_is_dark
                    else QColor("#111827")
                )

            if has_log:

                font = fmt.font()

                font.setUnderline(
                    True
                )

                fmt.setFont(
                    font
                )

            self.calendar.setDateTextFormat(
                current_date,
                fmt,
            )

            self.calendar_marked_dates.add(
                date_string
            )

    # =========================================
    # Cloud Results
    # =========================================

    def _on_cloud_result(
        self,
        request_id,
        operation,
        result,
    ):

        pending = self._cloud_pending.pop(
            request_id,
            None,
        )

        if pending is None:
            return

        kind, payload = pending

        if kind == "calendar_dates":

            self._render_calendar_log_markers(
                result or set()
            )

        elif kind == "daily_logs":

            self._render_logs(
                result or [],
                payload,
            )

        elif kind == "search":

            keyword, generation = payload

            if (
                generation
                != self._cloud_request_generation
                or keyword
                != self.search_input.text().strip()
            ):
                return

            self._render_search_results(
                result or [],
                keyword,
            )

        elif kind == "open_daily":

            self._fill_daily_dialog(
                payload,
                result or [],
            )

        elif kind == "edit_load":

            self._open_edit_dialog(
                payload,
                result,
            )

        elif kind == "update":

            dialog = payload

            if (
                dialog is not None
                and dialog.isVisible()
            ):
                dialog.accept()

            self.update_calendar_log_markers()

            self._refresh_current_logs()

        elif kind == "delete":

            dialog = payload

            if (
                dialog is not None
                and dialog.isVisible()
            ):
                dialog.accept()

            self.update_calendar_log_markers()

            self._refresh_current_logs()

        elif kind == "add":

            self.update_calendar_log_markers()

            QMessageBox.information(
                self,
                "Success",
                (
                    "บันทึก Log ลง "
                    "Cloud Database สำเร็จ"
                ),
            )

            self.back_to_calendar()

        elif kind == "notify_sessions_load":

            dialog = payload

            if (
                dialog is not None
                and dialog.isVisible()
            ):
                self._render_notify_sessions(
                    dialog,
                    result or [],
                )

        elif kind == "notify_session_revoke":

            dialog = payload

            if (
                dialog is not None
                and dialog.isVisible()
            ):
                if result:
                    dialog._status.setText(
                        "✅ ออก Session แล้ว"
                    )
                else:
                    dialog._status.setText(
                        "⚠️ ไม่พบ Session หรือ Session ถูกออกแล้ว"
                    )

                self._load_notify_sessions(
                    dialog
                )

        elif kind == "main_sources_load":

            dialog = payload

            if (
                dialog is not None
                and dialog.isVisible()
            ):
                self._render_main_notification_sources(
                    dialog,
                    result or [],
                )

        elif kind == "main_source_save":

            dialog = payload

            if (
                dialog is not None
                and dialog.isVisible()
            ):
                dialog._status.setText(
                    "✅ บันทึก Source แล้ว"
                )

                save_buttons = [
                    button
                    for button in dialog.findChildren(
                        QPushButton
                    )
                    if button.text() == "Save"
                ]

                for button in save_buttons:
                    button.setEnabled(
                        True
                    )

                self._load_main_notification_sources(
                    dialog
                )

        elif kind == "main_source_delete":

            dialog = payload

            if (
                dialog is not None
                and dialog.isVisible()
            ):
                dialog._source_key = ""
                dialog._name_input.clear()
                dialog._url_input.clear()
                dialog._enabled_check.setChecked(
                    True
                )
                dialog._notify_check.setChecked(
                    False
                )
                dialog._status.setText(
                    "✅ ลบ Source แล้ว"
                )
                self._load_main_notification_sources(
                    dialog
                )

        elif kind == "main_event_cursor_init":

            try:
                self._main_event_last_id = int(
                    result or 0
                )
            except (
                TypeError,
                ValueError,
            ):
                self._main_event_last_id = 0

            self.settings.setValue(
                "main_notifications_last_event_id",
                self._main_event_last_id,
            )
            self.settings.sync()

            self._main_event_cursor_ready = (
                True
            )

            if not self.main_notification_timer.isActive():
                self.main_notification_timer.start()

            self.poll_main_notification_events()

        elif kind == "main_events":

            self._main_event_poll_busy = False

            self._process_main_notification_events(
                result or []
            )

    def _on_cloud_error(
        self,
        request_id,
        operation,
        message,
    ):

        pending = self._cloud_pending.pop(
            request_id,
            None,
        )

        if pending is None:
            return

        kind, payload = pending

        if kind == "calendar_dates":
            return

        if kind in {
            "daily_logs",
            "search",
        }:

            self.logs_list.clear()

            item = QListWidgetItem(
                (
                    "โหลดข้อมูลไม่สำเร็จ: "
                    f"{message}"
                )
            )

            item.setFlags(
                Qt.ItemFlag.NoItemFlags
            )

            self.logs_list.addItem(
                item
            )

        elif kind == "open_daily":

            self._fill_daily_dialog(
                payload,
                [],
                message,
            )

        elif kind == "edit_load":

            QMessageBox.critical(
                self,
                "Cloud Database",
                (
                    "ไม่สามารถโหลด Log ได้\n\n"
                    f"{message}"
                ),
            )

        elif kind == "update":

            dialog = payload

            QMessageBox.critical(
                dialog,
                "Cloud Database",
                (
                    "บันทึกการแก้ไขไม่สำเร็จ\n\n"
                    f"{message}"
                ),
            )

            dialog.findChild(
                QPushButton,
                "saveButton",
            )

        elif kind == "delete":

            dialog = payload

            QMessageBox.critical(
                self,
                "Cloud Database",
                (
                    "ลบ Log ไม่สำเร็จ\n\n"
                    f"{message}"
                ),
            )

        elif kind == "add":

            QMessageBox.critical(
                self,
                "Cloud Database",
                (
                    "บันทึก Log ไม่สำเร็จ\n\n"
                    f"{message}"
                ),
            )

        elif kind in {
            "notify_sessions_load",
            "notify_session_revoke",
        }:

            dialog = payload

            if (
                dialog is not None
                and dialog.isVisible()
            ):
                dialog._status.setText(
                    "❌ Session Manager Error\n"
                    f"{message}"
                )
                dialog._logout_button.setEnabled(
                    bool(
                        dialog._session_list.currentItem()
                    )
                )

        elif kind in {
            "main_sources_load",
            "main_source_save",
            "main_source_delete",
        }:

            dialog = payload

            if (
                dialog is not None
                and dialog.isVisible()
            ):
                dialog._status.setText(
                    "❌ Central Source Error\n"
                    f"{message}"
                )

                for button in dialog.findChildren(
                    QPushButton
                ):
                    if button.text() == "Save":
                        button.setEnabled(
                            True
                        )

        elif kind == "main_event_cursor_init":

            self._main_event_cursor_ready = (
                True
            )
            self._main_event_last_id = 0

            if not self.main_notification_timer.isActive():
                self.main_notification_timer.start()

        elif kind == "main_events":

            self._main_event_poll_busy = False
            print(
                "[Main Notification Stream]",
                message,
            )

    # =========================================
    # Render Logs
    # =========================================

    def _render_logs(
        self,
        selected_logs,
        date,
    ):

        if date != self.selected_date:
            return

        self.logs_list.clear()

        if not selected_logs:

            item = QListWidgetItem(
                "ยังไม่มี Logs ในวันนี้"
            )

            item.setFlags(
                Qt.ItemFlag.NoItemFlags
            )

            self.logs_list.addItem(
                item
            )

            return

        for log in selected_logs:

            author = (
                log[5]
                if len(log) > 5
                and log[5]
                else "Unknown"
            )

            item = QListWidgetItem(
                (
                    f"🕒 {log[2]} | "
                    f"👤 {author}\n"
                    f"📝 {log[3]}\n"
                    f"{log[4] or ''}"
                )
            )

            item.setData(
                Qt.ItemDataRole.UserRole,
                log[0],
            )

            self.logs_list.addItem(
                item
            )

    def _render_search_results(
        self,
        results,
        keyword,
    ):

        self.logs_list.clear()

        self.logs_title.setText(
            f"Search Results: {len(results)}"
        )

        if not results:

            item = QListWidgetItem(
                (
                    f'ไม่พบ Log ที่มีคำว่า '
                    f'"{keyword}"'
                )
            )

            item.setFlags(
                Qt.ItemFlag.NoItemFlags
            )

            self.logs_list.addItem(
                item
            )

            return

        for log in results:

            author = (
                log[5]
                if len(log) > 5
                and log[5]
                else "Unknown"
            )

            item = QListWidgetItem(
                (
                    f"📅 {log[1]} "
                    f"🕒 {log[2]} | "
                    f"👤 {author}\n"
                    f"📝 {log[3]}\n"
                    f"{log[4] or ''}"
                )
            )

            item.setData(
                Qt.ItemDataRole.UserRole,
                log[0],
            )

            self.logs_list.addItem(
                item
            )

    def _refresh_current_logs(self):

        if self.search_input.text().strip():

            self.search_logs(
                self.search_input.text()
            )

        else:

            self.update_daily_logs(
                self.selected_date
            )

    def date_selected(
        self,
        date,
    ):

        self.selected_date = date

        self.update_selected_date(
            date
        )

        if not self.search_input.text().strip():

            self.update_daily_logs(
                date
            )

    def update_selected_date(
        self,
        date,
    ):

        formatted_date = (
            date.toString(
                "ddd - dd/MM/yyyy"
            )
        )

        self.selected_date_label.setText(
            f"Date: {formatted_date}"
        )

        self.logs_title.setText(
            f"Logs - {formatted_date}"
        )

    def update_daily_logs(
        self,
        date,
    ):

        self.logs_list.clear()

        log_date = date.toString(
            "yyyy-MM-dd"
        )

        request_id = (
            self.cloud.get_logs_for_date(
                log_date
            )
        )

        self._cloud_pending[
            request_id
        ] = (
            "daily_logs",
            date,
        )

        self.logs_title.setText(
            (
                "กำลังโหลด Logs - "
                f"{date.toString('ddd - dd/MM/yyyy')}..."
            )
        )

    # =========================================
    # Search
    # =========================================

    def _schedule_search(
        self,
        text,
    ):

        self._search_timer.stop()

        self._search_timer.start()

    def _run_debounced_search(self):

        self.search_logs(
            self.search_input.text()
        )

    def search_logs(
        self,
        text,
    ):

        keyword = text.strip()

        self._cloud_request_generation += 1

        generation = (
            self._cloud_request_generation
        )

        if not keyword:

            self.update_daily_logs(
                self.selected_date
            )

            return

        self.logs_list.clear()

        self.logs_title.setText(
            "กำลังค้นหา..."
        )

        request_id = (
            self.cloud.search_logs(
                keyword
            )
        )

        self._cloud_pending[
            request_id
        ] = (
            "search",
            (
                keyword,
                generation,
            ),
        )

    # =========================================
    # Daily Logs Dialog
    # =========================================

    def open_daily_logs(
        self,
        date,
    ):

        self.selected_date = date

        self.update_selected_date(
            date
        )

        formatted_date = (
            date.toString(
                "dd/MM/yyyy"
            )
        )

        dialog = QDialog(self)

        dialog.setWindowTitle(
            (
                "Daily Logs 日記 - "
                f"{formatted_date}"
            )
        )

        dialog.resize(
            520,
            400,
        )

        layout = QVBoxLayout(
            dialog
        )

        text_area = QTextEdit()

        text_area.setReadOnly(
            True
        )

        text_area.setPlainText(
            "กำลังโหลด..."
        )

        layout.addWidget(
            text_area
        )

        close_button = QPushButton(
            "Close"
        )

        close_button.clicked.connect(
            dialog.close
        )

        layout.addWidget(
            close_button
        )

        dialog._text_area = (
            text_area
        )

        dialog.show()

        request_id = (
            self.cloud.get_logs_for_date(
                date.toString(
                    "yyyy-MM-dd"
                )
            )
        )

        self._cloud_pending[
            request_id
        ] = (
            "open_daily",
            dialog,
        )

        self.update_daily_logs(
            date
        )

    def _fill_daily_dialog(
        self,
        dialog,
        selected_logs,
        error=None,
    ):

        if (
            not dialog
            or not dialog.isVisible()
        ):
            return

        if error:

            dialog._text_area.setPlainText(
                (
                    "ไม่สามารถโหลด Logs ได้\n\n"
                    f"{error}"
                )
            )

            return

        if selected_logs:

            lines = []

            for log in selected_logs:

                author = (
                    log[5]
                    if len(log) > 5
                    and log[5]
                    else "Unknown"
                )

                lines.append(
                    (
                        f"👍 {log[2]} | "
                        f"👤 {author} | "
                        f"{log[3]}\n"
                        f"{log[4] or ''}"
                    )
                )

            dialog._text_area.setPlainText(
                "\n\n".join(lines)
            )

        else:

            dialog._text_area.setPlainText(
                "ยังไม่มี Logs ในวันนี้"
            )

    # =========================================
    # Edit Log
    # =========================================

    def edit_log_from_list(
        self,
        item,
    ):

        log_id = item.data(
            Qt.ItemDataRole.UserRole
        )

        if log_id is not None:
            self.edit_log(
                log_id
            )

    def edit_log(
        self,
        log_id,
    ):

        request_id = (
            self.cloud.get_log(
                log_id
            )
        )

        self._cloud_pending[
            request_id
        ] = (
            "edit_load",
            log_id,
        )

    def _open_edit_dialog(
        self,
        log_id,
        log,
    ):

        if not log:

            QMessageBox.warning(
                self,
                "Warning",
                "ไม่พบ Log นี้",
            )

            return

        dialog = QDialog(self)

        dialog.setWindowTitle(
            "Edit Log"
        )

        dialog.resize(
            450,
            370,
        )

        author = (
            log[5]
            if len(log) > 5
            and log[5]
            else "Unknown"
        )

        layout = QVBoxLayout(
            dialog
        )

        layout.addWidget(
            QLabel(
                (
                    f"Date: {log[1]}    "
                    f"Time: {log[2]}    "
                    f"Author: 👤 {author}"
                )
            )
        )

        layout.addWidget(
            QLabel("Title")
        )

        title_input = QLineEdit(
            log[3]
        )

        layout.addWidget(
            title_input
        )

        layout.addWidget(
            QLabel("Description")
        )

        description_input = QTextEdit()

        description_input.setPlainText(
            log[4] or ""
        )

        layout.addWidget(
            description_input
        )

        button_layout = QHBoxLayout()

        delete_button = QPushButton(
            "Delete"
        )

        save_button = QPushButton(
            "Save"
        )

        cancel_button = QPushButton(
            "Cancel"
        )

        save_button.setObjectName(
            "saveButton"
        )

        button_layout.addWidget(
            delete_button
        )

        button_layout.addStretch()

        button_layout.addWidget(
            cancel_button
        )

        button_layout.addWidget(
            save_button
        )

        layout.addLayout(
            button_layout
        )

        def save_changes():

            new_title = (
                title_input.text().strip()
            )

            new_description = (
                description_input
                .toPlainText()
                .strip()
            )

            if not new_title:

                QMessageBox.warning(
                    dialog,
                    "Warning",
                    "กรุณาใส่ Title",
                )

                return

            save_button.setEnabled(
                False
            )

            delete_button.setEnabled(
                False
            )

            request_id = (
                self.cloud.update_log(
                    log_id,
                    new_title,
                    new_description,
                )
            )

            self._cloud_pending[
                request_id
            ] = (
                "update",
                dialog,
            )

        def delete_log():

            result = QMessageBox.question(
                dialog,
                "Confirm Delete",
                "ต้องการลบ Log นี้หรือไม่?",
                (
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No
                ),
            )

            if (
                result
                != QMessageBox.StandardButton.Yes
            ):
                return

            save_button.setEnabled(
                False
            )

            delete_button.setEnabled(
                False
            )

            request_id = (
                self.cloud.delete_log(
                    log_id
                )
            )

            self._cloud_pending[
                request_id
            ] = (
                "delete",
                dialog,
            )

        save_button.clicked.connect(
            save_changes
        )

        delete_button.clicked.connect(
            delete_log
        )

        cancel_button.clicked.connect(
            dialog.reject
        )

        dialog.show()

    # =========================================
    # Add Log
    # =========================================

    def create_add_page(self):

        page = QWidget()

        layout = QVBoxLayout()

        layout.setContentsMargins(
            10,
            5,
            10,
            5,
        )

        self.add_date_label = QLabel()

        self.add_date_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        title_label = QLabel(
            "Title"
        )

        self.title_input = QLineEdit()

        self.title_input.setPlaceholderText(
            "เช่น ตรวจสอบเอกสารลูกค้า"
        )

        description_label = QLabel(
            "Description"
        )

        self.description_input = QTextEdit()

        self.description_input.setPlaceholderText(
            "รายละเอียดงาน..."
        )

        self.description_input.setMinimumHeight(
            130
        )

        back_button = QPushButton(
            "Back"
        )

        back_button.clicked.connect(
            self.back_to_calendar
        )

        save_button = QPushButton(
            "Save"
        )

        save_button.clicked.connect(
            self.save_log
        )

        button_layout = QHBoxLayout()

        button_layout.addStretch()

        button_layout.addWidget(
            back_button
        )

        button_layout.addWidget(
            save_button
        )

        layout.addWidget(
            self.add_date_label
        )

        layout.addWidget(
            title_label
        )

        layout.addWidget(
            self.title_input
        )

        layout.addWidget(
            description_label
        )

        layout.addWidget(
            self.description_input
        )

        layout.addStretch()

        layout.addLayout(
            button_layout
        )

        page.setLayout(
            layout
        )

        return page

    def open_add_page(self):

        formatted_date = (
            self.selected_date.toString(
                "ddd - dd/MM/yyyy"
            )
        )

        self.add_date_label.setText(
            f"Date: {formatted_date}"
        )

        self.title_input.clear()

        self.description_input.clear()

        self.pages.setCurrentWidget(
            self.add_page
        )

    def back_to_calendar(self):

        self.pages.setCurrentWidget(
            self.calendar_page
        )

        if self.search_input.text().strip():

            self.search_logs(
                self.search_input.text()
            )

        else:

            self.update_daily_logs(
                self.selected_date
            )

        self.update_calendar_log_markers()

    def save_log(self):

        title = (
            self.title_input.text().strip()
        )

        description = (
            self.description_input
            .toPlainText()
            .strip()
        )

        if not title:

            QMessageBox.warning(
                self,
                "Warning",
                "กรุณาใส่ Title",
            )

            return

        log_date = (
            self.selected_date.toString(
                "yyyy-MM-dd"
            )
        )

        log_time = datetime.now().strftime(
            "%H:%M:%S"
        )

        request_id = (
            self.cloud.add_log(
                log_date,
                log_time,
                title,
                description,
            )
        )

        self._cloud_pending[
            request_id
        ] = (
            "add",
            None,
        )

        self.pages.setEnabled(
            False
        )

        QTimer.singleShot(
            100,
            lambda: self.pages.setEnabled(
                True
            ),
        )

    # =========================================
    # Sale Notifications
    # =========================================

    def add_sale_notification(
        self,
        title,
        message,
        notification_type="info",
        show_toast=True,
    ):
        """Record and present a notification.

        GAS/network access never happens here. SaleAPIMonitor is the only
        connection layer; sheet_monitor.NotificationPresenter owns the
        list/popup UI.
        """
        now = datetime.now().strftime(
            "%H:%M:%S"
        )

        self.sale_notifications.insert(
            0,
            {
                "time": now,
                "title": title,
                "message": message,
                "type": notification_type,
            },
        )

        while (
            len(self.sale_notifications)
            > 50
        ):
            self.sale_notifications.pop()

        self.notification_presenter.present(
            title=title,
            message=message,
            notification_type=notification_type,
            show_popup=show_toast,
            max_items=50,
        )

        if show_toast:
            # GAS-based central events are published by the Supabase
            # Central Worker so employee Notify clients do not depend on
            # this Admin PC being online.
            if self.notification_channels.line_enabled():
                ok, _line_message = (
                    self.notification_channels.send_line(
                        f"{title}\n{message}"
                    )
                )
                self.line_status = (
                    "idle"
                    if ok
                    else "error"
                )
                self.update_line_button()

    def show_sale_toast(
        self,
        title,
        message,
        notification_type="info",
    ):
        """Backward-compatible UI helper; no GAS access."""
        from sheet_monitor import Notification

        self.notification_presenter.show_popup(
            Notification(
                title=title,
                message=message,
                notification_type=notification_type,
            )
        )

    # =========================================
    # Sale Monitor Helpers
    # =========================================

    def _sale_button(
        self,
        branch,
    ):

        if branch == "Sathorn":
            return self.sale_alert_button

        if branch == "Srinakarin":
            return self.sale_alert_button_srinakarin

        if branch == "SA":
            return self.sa_notify_button

        if branch == "MainNoti":
            return self.main_noti_button

        return self.sale_alert_button

    def _sale_timer(
        self,
        branch,
    ):

        if branch == "Sathorn":
            return self.sale_sheet_timer

        if branch == "Srinakarin":
            return self.sale_sheet_timer_srinakarin

        if branch == "SA":
            return self.sale_sheet_timer_sa

        if branch == "MainNoti":
            return self.sale_sheet_timer_main_noti

        return self.sale_sheet_timer

    def _sale_title(
        self,
        branch,
    ):

        if branch == "SA":
            return "SA Sathorn"

        if branch == "MainNoti":
            return "MainNoti"

        return f"Sale Deli {branch}"

    def update_sale_button(
        self,
        branch,
    ):

        button = self._sale_button(branch)

        labels = {
            "Sathorn": "Sathorn",
            "Srinakarin": "Srinakarin",
            "SA": "SA Sathorn",
            "MainNoti": "MainNoti",
        }

        label = labels.get(
            branch,
            self._sale_title(branch),
        )

        if self._sale_busy.get(branch, False):
            dot = "🟡"
            tip = "กำลังเชื่อมต่อ / กำลังตรวจสอบ"
        elif self._sale_retry_waiting.get(branch, False):
            dot = "🟡"
            tip = (
                "Apps Script กำลังทำงานจากคำขออื่น "
                "ระบบจะลองใหม่อัตโนมัติ"
            )
        elif self.sale_errors.get(branch, False):
            dot = "🔴"
            error_text = str(
                self.sale_last_error.get(branch, "")
                or ""
            ).strip()
            tip = (
                "เชื่อมต่อ/อ่านข้อมูลไม่สำเร็จ"
                + (
                    f"\n{error_text[:220]}"
                    if error_text
                    else ""
                )
            )
        elif self.sale_enabled.get(branch, False):
            dot = "🟢"
            elapsed = float(
                self.sale_last_elapsed.get(
                    branch,
                    0.0,
                )
                or 0.0
            )
            tip = (
                "ทำงานปกติ"
                + (
                    f"\nรอบล่าสุด {elapsed:.2f} วินาที"
                    if elapsed > 0
                    else ""
                )
            )
        elif self.sale_api_urls.get(branch, "").strip():
            dot = "🔴"
            tip = "เชื่อมต่อไม่สำเร็จ / ไม่ทำงาน"
        else:
            dot = "⚪"
            tip = "ยังไม่ได้ตั้งค่า GAS URL"

        button.setText(f"{dot} {label}")
        button.setToolTip(
            f"{self._sale_title(branch)}: {tip}"
        )

    def _central_source_meta(
        self,
        branch,
    ):
        mapping = {
            "Sathorn": (
                "sale_sathorn",
                "Sale Deli Sathorn",
                "sale",
            ),
            "Srinakarin": (
                "sale_srinakarin",
                "Sale Deli Srinakarin",
                "sale",
            ),
            "SA": (
                "sa_sathorn",
                "SA Sathorn",
                "sa",
            ),
            "MainNoti": (
                "main_noti",
                "MainNoti",
                "structured",
            ),
        }

        return mapping.get(
            branch
        )

    def sync_monitor_source_to_cloud(
        self,
        branch,
        enabled=True,
    ):
        meta = self._central_source_meta(
            branch
        )

        if not meta:
            return

        source_key, source_name, source_type = (
            meta
        )

        url = (
            self.sale_api_urls.get(
                branch,
                "",
            ).strip()
        )

        if enabled and not url:
            return

        try:
            if enabled:
                self.cloud.call(
                    "upsert_monitor_source",
                    source_key,
                    source_name,
                    source_type,
                    url,
                    True,
                )
            else:
                self.cloud.call(
                    "disable_monitor_source",
                    source_key,
                )
        except Exception as error:
            print(
                "[Central Monitor Sync]",
                branch,
                error,
            )

    def sync_saved_monitor_sources_to_cloud(
        self,
    ):
        for branch in (
            "Sathorn",
            "Srinakarin",
            "SA",
        ):
            if (
                self.sale_api_urls.get(
                    branch,
                    "",
                ).strip()
            ):
                self.sync_monitor_source_to_cloud(
                    branch,
                    enabled=True,
                )

    # =========================================
    # Re-connect GAS Monitors
    # =========================================

    def reconnect_sale_monitor(
        self,
        branch,
    ):
        """Reconnect one configured GAS source without duplicating clients."""

        url = (
            self.sale_api_urls.get(
                branch,
                "",
            ).strip()
        )

        if not url:
            self.update_sale_button(
                branch
            )
            QMessageBox.information(
                self,
                "Re-connect GAS",
                (
                    f"{self._sale_title(branch)} "
                    "ยังไม่มี GAS URL ที่บันทึกไว้"
                ),
            )
            return False

        if self._sale_busy.get(
            branch,
            False,
        ):
            QMessageBox.information(
                self,
                "Re-connect GAS",
                (
                    f"{self._sale_title(branch)} "
                    "กำลังเชื่อมต่อ/ตรวจสอบอยู่แล้ว"
                ),
            )
            return False

        self._sale_timer(
            branch
        ).stop()

        self._gas_scan_queue = [
            queued
            for queued in self._gas_scan_queue
            if queued != branch
        ]

        self.sale_enabled[branch] = (
            False
        )

        self.sale_monitors[branch] = (
            None
        )

        self.sale_errors[branch] = (
            False
        )

        self.sale_last_error[branch] = (
            ""
        )

        self.sale_last_elapsed[branch] = (
            0.0
        )
        self._sale_retry_waiting[branch] = (
            False
        )

        self.update_sale_button(
            branch
        )

        self._start_sale_check(
            branch,
            url,
            initial=True,
        )

        return True

    def reconnect_all_sale_monitors(self):

        connected = 0

        for branch in (
            "Sathorn",
            "Srinakarin",
            "SA",
        ):

            url = (
                self.sale_api_urls.get(
                    branch,
                    "",
                ).strip()
            )

            if not url:
                self.update_sale_button(
                    branch
                )
                continue

            if self._sale_busy.get(
                branch,
                False,
            ):
                continue

            connected += 1

            self._sale_timer(
                branch
            ).stop()

            self._gas_scan_queue = [
                queued
                for queued in self._gas_scan_queue
                if queued != branch
            ]

            self.sale_enabled[branch] = (
                False
            )

            self.sale_monitors[branch] = (
                None
            )

            self.sale_errors[branch] = (
                False
            )

            self.sale_last_error[branch] = (
                ""
            )

            self.sale_last_elapsed[branch] = (
                0.0
            )

            self.update_sale_button(
                branch
            )

            self._start_sale_check(
                branch,
                url,
                initial=True,
            )

        if connected == 0:
            QMessageBox.information(
                self,
                "Re-connect GAS",
                (
                    "ไม่มี GAS URL ที่พร้อม Re-connect "
                    "หรือทุกช่องทางกำลังตรวจสอบอยู่"
                ),
            )

    # =========================================
    # Start Saved Monitors
    # =========================================

    def start_saved_sale_monitors(self):

        for branch in (
            "Sathorn",
            "Srinakarin",
            "SA",
        ):

            url = (
                self.sale_api_urls.get(
                    branch,
                    "",
                ).strip()
            )

            if not url:

                self.update_sale_button(
                    branch
                )

                continue

            self._start_sale_check(
                branch,
                url,
                initial=True,
            )

    # =========================================
    # Start Sale Check
    # =========================================

    def _start_sale_check(
        self,
        branch,
        url,
        initial=False,
    ):

        if self._sale_busy.get(
            branch,
            False,
        ):
            return

        self._sale_busy[branch] = True
        self.sale_errors[branch] = False
        self.sale_last_error[branch] = ""
        self.update_sale_button(branch)

        monitor = self.sale_monitors.get(
            branch
        )

        if (
            monitor is None
            or initial
        ):
            monitor = SaleAPIMonitor(
                url
            )

        def finished(result):

            self._sale_busy[branch] = False
            self.sale_errors[branch] = False
            self.sale_last_error[branch] = ""
            self.sale_last_elapsed[branch] = float(
                result.get(
                    "_elapsed_seconds",
                    0.0,
                )
                or 0.0
            )

            self.sale_monitors[branch] = (
                monitor
            )

            self.sale_enabled[branch] = (
                True
            )

            self.sync_monitor_source_to_cloud(
                branch,
                enabled=True,
            )

            self._sale_timer(
                branch
            ).start()

            self.update_sale_button(
                branch
            )

            if initial:
                api_version = str(
                    result.get("version")
                    or result.get("api_version")
                    or ""
                ).strip()

                elapsed = float(
                    result.get(
                        "_elapsed_seconds",
                        0.0,
                    )
                    or 0.0
                )
                message = (
                    "เชื่อมต่อ Apps Script Web App สำเร็จ"
                    + (
                        f" ({elapsed:.2f} วินาที)"
                        if elapsed > 0
                        else ""
                    )
                )

                if api_version:
                    message += (
                        f"\nAPI: {api_version}"
                    )

                message += (
                    "\nกำลังอ่านข้อมูลรอบแรก..."
                )

                self.add_sale_notification(
                    self._sale_title(
                        branch
                    ),
                    message,
                    "info",
                    show_toast=False,
                )

                QTimer.singleShot(
                    0,
                    lambda b=branch:
                    self.check_sale_delivery_plan(
                        b
                    ),
                )

                return

            self._process_sale_result(
                branch,
                result,
            )

        def failed(message):

            self._sale_busy[branch] = False
            self.sale_errors[branch] = True
            self.sale_last_error[branch] = str(
                message
            )

            if initial:
                self.sale_enabled[branch] = (
                    False
                )

                self.sale_monitors[branch] = (
                    None
                )

                self._sale_timer(
                    branch
                ).stop()

            self.update_sale_button(
                branch
            )

            if initial:
                self.add_sale_notification(
                    self._sale_title(
                        branch
                    ),
                    (
                        "Re-connect ไม่สำเร็จ\n"
                        f"{message}"
                    ),
                    "info",
                    show_toast=False,
                )

        if initial:
            run_async(
                self,
                monitor.ping,
                finished,
                failed,
            )
        else:
            run_async(
                self,
                monitor.check,
                finished,
                failed,
                False,
            )

    # =========================================
    # Configure Sale Branch / MainNoti
    # =========================================

    def configure_sale_branch(
        self,
        branch,
    ):

        dialog = QDialog(
            self
        )

        dialog.setWindowTitle(
            (
                "ตั้งค่าแจ้งเตือน "
                f"{self._sale_title(branch)}"
            )
        )

        dialog.resize(
            560,
            240,
        )

        layout = QVBoxLayout(
            dialog
        )

        info = QLabel(
            (
                "ใส่ URL ของ Google Apps Script "
                "Web App สำหรับ "
                f"{self._sale_title(branch)}\n\n"
                "ระบบจะอ่าน Google Sheet ผ่าน "
                "Apps Script โดยไม่ใช้ Google Cloud"
            )
        )

        info.setWordWrap(
            True
        )

        layout.addWidget(
            info
        )

        url_input = QLineEdit()

        url_input.setPlaceholderText(
            "https://script.google.com/macros/s/.../exec"
        )

        url_input.setText(
            self.sale_api_urls.get(
                branch,
                "",
            )
        )

        layout.addWidget(
            url_input
        )

        button_layout = QHBoxLayout()

        start_button = QPushButton(
            "เริ่มแจ้งเตือน"
        )

        reconnect_button = QPushButton(
            "🔄 Re-connect"
        )

        stop_button = QPushButton(
            "หยุดแจ้งเตือน"
        )

        cancel_button = QPushButton(
            "ยกเลิก"
        )

        button_layout.addWidget(
            start_button
        )

        button_layout.addWidget(
            reconnect_button
        )

        button_layout.addWidget(
            stop_button
        )

        button_layout.addStretch()

        button_layout.addWidget(
            cancel_button
        )

        layout.addLayout(
            button_layout
        )

        def start_monitoring():

            url = (
                url_input.text()
                .strip()
                .replace(
                    "https:https://",
                    "https://",
                    1,
                )
            )

            if (
                "/spreadsheets/d/" in url
                or "docs.google.com/spreadsheets"
                in url
            ):

                QMessageBox.warning(
                    dialog,
                    "URL ไม่ถูกต้อง",
                    (
                        "URL นี้เป็น URL ของ Google Sheet "
                        "ไม่ใช่ Apps Script Web App\n\n"
                        "ให้ใช้ URL ของ Apps Script "
                        "Web App ที่ลงท้ายด้วย /exec"
                    ),
                )

                return

            if not url:

                QMessageBox.warning(
                    dialog,
                    "ข้อมูลไม่ครบ",
                    (
                        "กรุณาใส่ Apps Script "
                        "Web App URL"
                    ),
                )

                return

            start_button.setEnabled(
                False
            )

            reconnect_button.setEnabled(
                False
            )

            stop_button.setEnabled(
                False
            )

            url_input.setEnabled(
                False
            )

            self._sale_timer(
                branch
            ).stop()

            self.sale_enabled[branch] = (
                False
            )

            self.sale_monitors[branch] = (
                None
            )

            self.sale_api_urls[branch] = (
                url
            )

            # -----------------------------------------
            # Settings key for each branch
            # -----------------------------------------

            setting_keys = {
                "Sathorn": "sathorn_url",
                "Srinakarin": "srinakarin_url",
                "SA": "sa_url",
                "MainNoti": "main_noti_url",
            }

            setting_key = setting_keys.get(
                branch
            )

            if setting_key:

                self.settings.setValue(
                    setting_key,
                    url,
                )

                self.settings.sync()

            self._start_sale_check_for_dialog(
                branch,
                url,
                dialog,
                controls={
                    "start": start_button,
                    "reconnect": reconnect_button,
                    "stop": stop_button,
                    "url": url_input,
                },
            )

        start_button.clicked.connect(
            start_monitoring
        )

        reconnect_button.clicked.connect(
            start_monitoring
        )

        stop_button.clicked.connect(
            lambda: self._stop_sale_branch(
                branch,
                dialog,
            )
        )

        cancel_button.clicked.connect(
            dialog.reject
        )

        dialog.show()

    # =========================================
    # Start Monitor From Dialog
    # =========================================

    def _start_sale_check_for_dialog(
        self,
        branch,
        url,
        dialog,
        controls=None,
    ):

        if self._sale_busy.get(
            branch,
            False,
        ):
            return

        controls = controls or {}

        self._sale_busy[branch] = True
        self.sale_errors[branch] = False
        self.sale_last_error[branch] = ""
        self.update_sale_button(branch)

        monitor = SaleAPIMonitor(
            url
        )

        def restore_controls():

            for key in (
                "start",
                "reconnect",
                "stop",
                "url",
            ):
                widget = controls.get(
                    key
                )

                if widget is not None:
                    widget.setEnabled(
                        True
                    )

        def finished(result):

            self._sale_busy[branch] = False
            self.sale_errors[branch] = False
            self.sale_last_error[branch] = ""
            self.sale_last_elapsed[branch] = float(
                result.get(
                    "_elapsed_seconds",
                    0.0,
                )
                or 0.0
            )

            self.sale_monitors[branch] = (
                monitor
            )

            self.sale_enabled[branch] = (
                True
            )

            self.sync_monitor_source_to_cloud(
                branch,
                enabled=True,
            )

            self._sale_timer(
                branch
            ).start()

            self.update_sale_button(
                branch
            )

            api_version = str(
                result.get("version")
                or result.get("api_version")
                or ""
            ).strip()

            elapsed = float(
                result.get(
                    "_elapsed_seconds",
                    0.0,
                )
                or 0.0
            )
            message = (
                "Re-connect สำเร็จ"
                + (
                    f" ({elapsed:.2f} วินาที)"
                    if elapsed > 0
                    else ""
                )
            )

            if api_version:
                message += (
                    f"\nAPI: {api_version}"
                )

            message += (
                "\nกำลังอ่านข้อมูลรอบแรก..."
            )

            self.add_sale_notification(
                self._sale_title(
                    branch
                ),
                message,
                "info",
            )

            if dialog.isVisible():
                dialog.accept()

            QTimer.singleShot(
                0,
                lambda b=branch:
                self.check_sale_delivery_plan(
                    b
                ),
            )

        def failed(message):

            self._sale_busy[branch] = False
            self.sale_errors[branch] = True
            self.sale_last_error[branch] = str(
                message
            )

            self.sale_enabled[branch] = (
                False
            )

            self.sale_monitors[branch] = (
                None
            )

            self._sale_timer(
                branch
            ).stop()

            self.update_sale_button(
                branch
            )

            restore_controls()

            QMessageBox.critical(
                dialog,
                "Re-connect ไม่สำเร็จ",
                (
                    "ไม่สามารถเชื่อมต่อ "
                    "Apps Script Web App ได้\n\n"
                    f"{message}\n\n"
                    "ตรวจว่า Deploy เป็น Web App, "
                    "URL ลงท้าย /exec และ GAS รองรับ action=ping"
                ),
            )

        run_async(
            self,
            monitor.ping,
            finished,
            failed,
        )

    # =========================================
    # Stop Sale Branch
    # =========================================

    def _stop_sale_branch(
        self,
        branch,
        dialog=None,
    ):

        self.sale_enabled[branch] = (
            False
        )

        self._sale_timer(
            branch
        ).stop()

        self.sale_monitors[branch] = (
            None
        )

        self._sale_busy[branch] = (
            False
        )

        setting_keys = {
            "Sathorn": "sathorn_url",
            "Srinakarin": "srinakarin_url",
            "SA": "sa_url",
            "MainNoti": "main_noti_url",
        }

        setting_key = setting_keys.get(
            branch
        )

        self.sync_monitor_source_to_cloud(
            branch,
            enabled=False,
        )

        self.sale_api_urls[branch] = (
            ""
        )

        if setting_key:

            self.settings.setValue(
                setting_key,
                "",
            )

            self.settings.sync()

        self.update_sale_button(
            branch
        )

        if (
            dialog
            and dialog.isVisible()
        ):

            dialog.accept()

    # =========================================
    # Polling
    # =========================================

    def check_sale_delivery_plan(
        self,
        branch="Sathorn",
    ):
        """Queue one GAS data scan.

        Connection pings are lightweight and may finish together, but the
        expensive action=changes requests are serialized globally so Sathorn,
        Srinakarin, SA and MainNoti never perform heavy sheet scans at the
        same time.
        """

        if not self.sale_enabled.get(
            branch,
            False,
        ):
            return

        if self.sale_monitors.get(
            branch
        ) is None:
            return

        if (
            branch == self._gas_scan_active
            or branch in self._gas_scan_queue
        ):
            return

        self._gas_scan_queue.append(
            branch
        )

        # If another source is scanning, this source is healthy but waiting.
        if self._gas_scan_active is not None:
            self._sale_retry_waiting[branch] = (
                True
            )
            self.sale_errors[branch] = False
            self.sale_last_error[branch] = (
                "รอคิวตรวจข้อมูลจาก GAS ช่องทางอื่น"
            )
            self.update_sale_button(
                branch
            )

        self._run_next_gas_scan()

    def _run_next_gas_scan(self):
        if self._gas_scan_active is not None:
            return

        while self._gas_scan_queue:
            branch = self._gas_scan_queue.pop(0)

            if not self.sale_enabled.get(
                branch,
                False,
            ):
                self._sale_retry_waiting[branch] = (
                    False
                )
                self.update_sale_button(
                    branch
                )
                continue

            monitor = self.sale_monitors.get(
                branch
            )

            if monitor is None:
                self._sale_retry_waiting[branch] = (
                    False
                )
                self.update_sale_button(
                    branch
                )
                continue

            self._gas_scan_active = branch
            self._sale_busy[branch] = True
            self._sale_retry_waiting[branch] = False
            self.sale_errors[branch] = False
            self.sale_last_error[branch] = ""
            self.update_sale_button(branch)

            def finished(
                result,
                b=branch,
            ):
                self._sale_busy[b] = False
                self._gas_scan_active = None
                self._sale_retry_waiting[b] = False
                self.sale_errors[b] = False
                self.sale_last_error[b] = ""
                self.sale_last_elapsed[b] = float(
                    result.get(
                        "_elapsed_seconds",
                        0.0,
                    )
                    or 0.0
                )
                self.update_sale_button(b)

                self._process_sale_result(
                    b,
                    result,
                )

                QTimer.singleShot(
                    800,
                    self._run_next_gas_scan,
                )

            def failed(
                message,
                b=branch,
            ):
                self._sale_busy[b] = False
                self._gas_scan_active = None

                error_text = str(
                    message
                )

                if error_text.startswith(
                    "[GAS_BUSY]"
                ):
                    clean_message = (
                        error_text
                        .replace(
                            "[GAS_BUSY]",
                            "",
                            1,
                        )
                        .strip()
                    )

                    self.sale_errors[b] = False
                    self._sale_retry_waiting[b] = True
                    self.sale_last_error[b] = (
                        clean_message
                    )
                    self.update_sale_button(b)

                    # Do not put the same request back immediately because
                    # the server-side GAS execution may still hold the lock.
                    QTimer.singleShot(
                        20000,
                        lambda branch_to_retry=b:
                        self._queue_busy_gas_retry(
                            branch_to_retry
                        ),
                    )

                    QTimer.singleShot(
                        800,
                        self._run_next_gas_scan,
                    )
                    return

                self._sale_retry_waiting[b] = False
                self.sale_errors[b] = True

                if error_text.startswith(
                    "[GAS_404]"
                ):
                    clean_error = (
                        error_text
                        .replace(
                            "[GAS_404]",
                            "",
                            1,
                        )
                        .strip()
                    )
                else:
                    clean_error = (
                        error_text
                    )

                self.sale_last_error[b] = (
                    clean_error
                )
                self.update_sale_button(b)

                # Keep the exact reason visible in the DailyLog notification
                # list without creating a popup/LINE/central event.
                self.add_sale_notification(
                    self._sale_title(b),
                    (
                        "Web App เชื่อมต่อได้ แต่การอ่านข้อมูลไม่สำเร็จ\n"
                        f"{clean_error}"
                    ),
                    "info",
                    show_toast=False,
                )

                QTimer.singleShot(
                    800,
                    self._run_next_gas_scan,
                )

            run_async(
                self,
                monitor.check,
                finished,
                failed,
                False,
            )

            return

    def _queue_busy_gas_retry(
        self,
        branch,
    ):
        if not self.sale_enabled.get(
            branch,
            False,
        ):
            self._sale_retry_waiting[branch] = (
                False
            )
            self.update_sale_button(
                branch
            )
            return

        if self.sale_monitors.get(
            branch
        ) is None:
            self._sale_retry_waiting[branch] = (
                False
            )
            self.update_sale_button(
                branch
            )
            return

        if (
            branch == self._gas_scan_active
            or branch in self._gas_scan_queue
        ):
            return

        self._sale_retry_waiting[branch] = (
            False
        )
        self.check_sale_delivery_plan(
            branch
        )

    # =========================================
    # Process Sale Result
    # =========================================

    def _process_sale_result(
        self,
        branch,
        result,
    ):

        title = self._sale_title(
            branch
        )

        def row_data_items(values):
            items = (
                values.get(
                    "row_data"
                )
                if isinstance(
                    values,
                    dict,
                )
                else None
            )

            if isinstance(
                items,
                list,
            ):
                return [
                    item
                    for item in items
                    if isinstance(
                        item,
                        dict,
                    )
                ]

            fallback = []

            for (
                label,
                key,
            ) in (
                ("Model", "model"),
                ("VIN", "vin"),
                ("Customer", "customer"),
                ("Sale", "sale"),
                ("Pay Day", "pay_day"),
                (
                    "Delivery Date",
                    "delivery_date",
                ),
            ):
                fallback.append({
                    "column": "",
                    "header": label,
                    "value":
                        values.get(
                            key,
                            "",
                        )
                        if isinstance(
                            values,
                            dict,
                        )
                        else "",
                })

            return fallback

        def row_data_map(values):
            result_map = {}

            for item in row_data_items(
                values
            ):
                column = str(
                    item.get(
                        "column",
                        "",
                    )
                    or ""
                ).strip()

                header = str(
                    item.get(
                        "header",
                        "",
                    )
                    or ""
                ).strip()

                key = (
                    column
                    or header
                )

                if not key:
                    continue

                result_map[key] = {
                    "column": column,
                    "header": header,
                    "value": str(
                        item.get(
                            "value",
                            "",
                        )
                        or ""
                    ),
                }

            return result_map

        def row_item_label(item):
            column = str(
                item.get(
                    "column",
                    "",
                )
                or ""
            ).strip()

            header = str(
                item.get(
                    "header",
                    "",
                )
                or ""
            ).strip()

            if column and header:
                return (
                    f"{column} - {header}"
                )

            return (
                header
                or column
                or "ข้อมูล"
            )

        def format_full_row(values):
            lines = []

            for item in row_data_items(
                values
            ):
                value = str(
                    item.get(
                        "value",
                        "",
                    )
                    or ""
                ).strip()

                if value == "":
                    continue

                lines.append(
                    (
                        f"{row_item_label(item)}: "
                        f"{value}"
                    )
                )

            if not lines:
                return "ไม่มีข้อมูลในแถว"

            return "\n".join(
                lines
            )

        def full_row_changes(
            old_values,
            new_values,
        ):
            old_map = row_data_map(
                old_values
            )
            new_map = row_data_map(
                new_values
            )

            ordered_keys = []

            for item in row_data_items(
                new_values
            ):
                key = (
                    str(
                        item.get(
                            "column",
                            "",
                        )
                        or ""
                    ).strip()
                    or str(
                        item.get(
                            "header",
                            "",
                        )
                        or ""
                    ).strip()
                )

                if (
                    key
                    and key not in
                    ordered_keys
                ):
                    ordered_keys.append(
                        key
                    )

            for item in row_data_items(
                old_values
            ):
                key = (
                    str(
                        item.get(
                            "column",
                            "",
                        )
                        or ""
                    ).strip()
                    or str(
                        item.get(
                            "header",
                            "",
                        )
                        or ""
                    ).strip()
                )

                if (
                    key
                    and key not in
                    ordered_keys
                ):
                    ordered_keys.append(
                        key
                    )

            changes = []

            for key in ordered_keys:
                old_item = old_map.get(
                    key,
                    {},
                )
                new_item = new_map.get(
                    key,
                    {},
                )

                old_value = str(
                    old_item.get(
                        "value",
                        "",
                    )
                    or ""
                )

                new_value = str(
                    new_item.get(
                        "value",
                        "",
                    )
                    or ""
                )

                if (
                    old_value ==
                    new_value
                ):
                    continue

                label = row_item_label(
                    new_item
                    or old_item
                )

                if (
                    old_value == ""
                    and new_value != ""
                ):
                    changes.append(
                        (
                            f"{label}: เพิ่ม "
                            f"{new_value}"
                        )
                    )

                elif (
                    old_value != ""
                    and new_value == ""
                ):
                    changes.append(
                        (
                            f"{label}: ลบ "
                            f"{old_value}"
                        )
                    )

                else:
                    changes.append(
                        (
                            f"{label}: "
                            f"{old_value or '-'} "
                            "→ "
                            f"{new_value or '-'}"
                        )
                    )

            return changes

        # =====================================
        # NEW
        # =====================================

        for row, values in result.get(
            "added",
            [],
        ):
            message = (
                "ข้อมูลที่เพิ่ม\n"
                + format_full_row(
                    values
                )
            )

            self.add_sale_notification(
                f"{title} - เพิ่มข้อมูล",
                message,
                "new",
            )

        # =====================================
        # EDIT
        # =====================================

        for (
            row,
            old_values,
            new_values,
        ) in result.get(
            "changed",
            [],
        ):
            changes = full_row_changes(
                old_values,
                new_values,
            )

            if not changes:
                continue

            message = (
                "ข้อมูลที่เปลี่ยน\n"
                + "\n".join(
                    changes
                )
                + "\n\nรายละเอียดแจ้ง:\n"
                + format_full_row(
                    new_values
                )
            )

            self.add_sale_notification(
                (
                    f"{title} "
                    "- มีการแก้ไขข้อมูล"
                ),
                message,
                "edit",
            )

        # =====================================
        # DELETE
        # =====================================

        for deleted_item in result.get(
            "deleted",
            [],
        ):
            if (
                isinstance(
                    deleted_item,
                    (tuple, list),
                )
                and len(
                    deleted_item
                ) >= 2
            ):
                row = (
                    deleted_item[0]
                )
                old_values = (
                    deleted_item[1]
                )
            else:
                row = deleted_item
                old_values = {}

            message = (
                "ข้อมูลที่ถูกลบ\n"
                + format_full_row(
                    old_values
                )
            )

            self.add_sale_notification(
                (
                    f"{title} "
                    "- ลบข้อมูล"
                ),
                message,
                "delete",
            )

        # =====================================
        # STRUCTURED GAS EVENTS
        # =====================================

        sa_column_labels = {
            "B": "เวลานัดหมาย 预约时间",
            "C": "ลำดับ 序号",
            "D": "วันที่ 日期",
            "E": "ชื่อ-นามสกุล ลูกค้า 客户的姓名",
            "F": "ทะเบียนรถ 车牌",
            "G": "เบอร์ติดต่อ 电话",
            "H": "รุ่นรถ 车型",
            "I": "แผนก BP/SV 部分",
            "J": "SA 在",
            "K": "รายการคำสั่งซ่อม 保修项目",
            "L": (
                "สถานะการโทรติดตาม "
                "(รับนัด , ไม่สะดวก , ไม่รับสาย , เข้าศูนย์อื่น) "
                "电话跟进状态：已预约 / 不方便 / 未接 / 去其他店"
            ),
            "M": "เวลาส่งมอบรถ 交车时间",
            "N": "นัดผ่าน 预约方式",
            "O": "สถานะ 预约状态",
            "P": "หมายเหตุ 备注",
        }

        def value_text(value):
            if value is None or value == "":
                return "-"
            if isinstance(value, (dict, list)):
                return json.dumps(
                    value,
                    ensure_ascii=False,
                )
            return str(value)

        def column_letter(value):
            if value is None:
                return ""

            text_value = str(
                value
            ).strip().upper()

            if (
                len(text_value) == 1
                and "A" <= text_value <= "Z"
            ):
                return text_value

            if text_value.isdigit():
                number = int(text_value)
                if 1 <= number <= 26:
                    return chr(
                        64 + number
                    )

            return ""

        def event_item_label(item):
            # Structured Sale Delivery GAS sends "header".
            # SA may send either "header" or column metadata.
            header = (
                item.get("header")
                or item.get("field")
                or item.get("columnName")
                or item.get("name")
            )

            if header:
                return str(header)

            col = column_letter(
                item.get("columnLetter")
                or item.get("column")
                or item.get("col")
                or item.get("columnIndex")
                or item.get("colIndex")
            )

            if (
                branch == "SA"
                and col in sa_column_labels
            ):
                return sa_column_labels[col]

            return col or "ข้อมูล"

        for event in result.get(
            "changes",
            [],
        ):

            if not isinstance(
                event,
                dict,
            ):

                self.add_sale_notification(
                    (
                        f"{title} "
                        "- มีการเปลี่ยนแปลงข้อมูล"
                    ),
                    value_text(event),
                    "edit",
                )
                continue

            event_type = str(
                event.get("type")
                or "row_change"
            ).strip()

            nested_changes = (
                event.get("changes")
                if isinstance(
                    event.get("changes"),
                    list,
                )
                else []
            )

            # SA Notify is date-driven only:
            # show current-day appointment matches, never edit/delete events.
            if branch == "SA":
                if event_type != "today_appointment":
                    continue
                nested_changes = []

            # Pure today reminders repeat from GAS every poll.
            # Persistently suppress only those reminders; a real edit in
            # the same row is still allowed through.
            if (
                event_type in (
                    "delivery_today",
                    "today_appointment",
                )
                and not nested_changes
            ):
                today_fields_for_key = (
                    event.get("today_fields")
                    if isinstance(
                        event.get("today_fields"),
                        list,
                    )
                    else []
                )
                signature = "|".join(
                    (
                        f"{item.get('header', '')}:"
                        f"{item.get('value', '')}"
                    )
                    for item in today_fields_for_key
                    if isinstance(item, dict)
                )
                due_key = (
                    "structured_due/"
                    f"{date.today().isoformat()}/"
                    f"{branch}/"
                    f"{event.get('sheet', '')}/"
                    f"{event.get('row', '')}/"
                    f"{signature}"
                )
                if self.settings.value(
                    due_key,
                    False,
                    type=bool,
                ):
                    continue

                self.settings.setValue(
                    due_key,
                    True,
                )
                self.settings.sync()

            customer = str(
                event.get("customer")
                or ""
            ).strip()

            model = str(
                event.get("model")
                or ""
            ).strip()

            lines = []

            # Context สำคัญของรายการ
            if customer:
                if branch == "SA":
                    lines.append(
                        "ชื่อ-นามสกุล ลูกค้า "
                        f"客户的姓名: {customer}"
                    )
                else:
                    lines.append(
                        f"Customer: {customer}"
                    )

            if model:
                if branch == "SA":
                    lines.append(
                        f"รุ่นรถ 车型: {model}"
                    )
                else:
                    lines.append(
                        f"Model: {model}"
                    )

            # วันที่ที่ตรงกับวันนี้
            today_fields = (
                event.get("today_fields")
                if isinstance(
                    event.get("today_fields"),
                    list,
                )
                else []
            )

            for item in today_fields:

                if not isinstance(
                    item,
                    dict,
                ):
                    continue

                label = (
                    item.get("header")
                    or item.get("field")
                    or "วันที่"
                )

                value = item.get(
                    "value",
                    "",
                )

                if value not in (
                    None,
                    "",
                ):
                    lines.append(
                        f"{label}: {value}"
                    )

            # สิ่งที่เปลี่ยนทั้งหมดใน Row เดียวกัน
            nested = nested_changes

            for item in nested:

                if not isinstance(
                    item,
                    dict,
                ):
                    lines.append(
                        value_text(item)
                    )
                    continue

                label = event_item_label(
                    item
                )

                change_type = str(
                    item.get("type")
                    or ""
                ).lower()

                before = next(
                    (
                        item[key]
                        for key in (
                            "oldValue",
                            "old_value",
                            "before",
                            "old",
                        )
                        if key in item
                    ),
                    None,
                )

                after = next(
                    (
                        item[key]
                        for key in (
                            "newValue",
                            "new_value",
                            "after",
                            "new",
                            "value",
                        )
                        if key in item
                    ),
                    None,
                )

                if change_type == "created":

                    lines.append(
                        f"{label}: "
                        f"{value_text(after)}"
                    )

                elif change_type == "deleted":

                    lines.append(
                        f"{label}: "
                        "ลบข้อมูล "
                        f"(เดิม: {value_text(before)})"
                    )

                else:

                    lines.append(
                        f"{label}: "
                        f"{value_text(before)} "
                        "→ "
                        f"{value_text(after)}"
                    )

            if not lines:
                lines.append(
                    "พบการเปลี่ยนแปลงข้อมูล"
                )

            # ห้ามแสดง Row / Sheet metadata ใน Popup
            message = "\n".join(
                lines
            )

            if event_type == "delivery_today":

                event_title = (
                    f"{title} - ส่งรถวันนี้"
                )
                notification_type = "due"

            elif event_type == "today_appointment":

                event_title = (
                    f"{title} - นัดหมายวันนี้"
                )
                notification_type = "due"

            else:

                event_title = (
                    f"{title} "
                    "- มีการเปลี่ยนแปลงข้อมูล"
                )
                notification_type = "edit"

            self.add_sale_notification(
                event_title,
                message,
                notification_type,
            )

        # =====================================
        # DUE TODAY
        # =====================================

        # Structured GAS already emits delivery_today / today_appointment.
        # Legacy row feeds still use get_due_today().
        if not result.get(
            "structured",
            False,
        ):
            self.notify_due_today(
                branch
            )

    # =========================================
    # Delivery Due Today
    # =========================================

    def notify_due_today(
        self,
        branch="Sathorn",
    ):

        # SA uses the merged Column-D current-day scope and only reports
        # add/edit/delete changes inside that scope.
        if branch == "SA":
            return

        monitor = self.sale_monitors.get(
            branch
        )

        if monitor is None:
            return

        def format_row(values):
            items = (
                values.get(
                    "row_data"
                )
                if isinstance(
                    values,
                    dict,
                )
                else None
            )

            lines = []

            if isinstance(
                items,
                list,
            ):
                for item in items:
                    if not isinstance(
                        item,
                        dict,
                    ):
                        continue

                    value = str(
                        item.get(
                            "value",
                            "",
                        )
                        or ""
                    ).strip()

                    if not value:
                        continue

                    column = str(
                        item.get(
                            "column",
                            "",
                        )
                        or ""
                    ).strip()

                    header = str(
                        item.get(
                            "header",
                            "",
                        )
                        or ""
                    ).strip()

                    label = (
                        (
                            f"{column} - {header}"
                            if column and header
                            else header
                            or column
                        )
                        or "ข้อมูล"
                    )

                    lines.append(
                        f"{label}: {value}"
                    )

            if not lines:
                for label, key in (
                    ("Model", "model"),
                    ("VIN", "vin"),
                    (
                        "Customer",
                        "customer",
                    ),
                    ("Sale", "sale"),
                    (
                        "Pay Day",
                        "pay_day",
                    ),
                    (
                        "Delivery Date",
                        "delivery_date",
                    ),
                ):
                    value = str(
                        values.get(
                            key,
                            "",
                        )
                        or ""
                    ).strip()

                    if value:
                        lines.append(
                            f"{label}: {value}"
                        )

            return "\n".join(
                lines
            )

        for row, values in (
            monitor.get_due_today()
        ):
            due_fields = (
                values.get(
                    "due_fields",
                    [],
                )
                or []
            )

            notification_key = (
                f"{branch}-"
                f"{date.today().isoformat()}-"
                f"{row}-"
                f"{'|'.join(due_fields)}"
            )

            if (
                notification_key
                in self.sale_due_notified
            ):
                continue

            self.sale_due_notified.add(
                notification_key
            )

            if due_fields == [
                "Pay Day"
            ]:
                suffix = (
                    "Pay Day วันนี้"
                )

            elif due_fields == [
                "Delivery Date"
            ]:
                suffix = (
                    "ส่งรถวันนี้"
                )

            else:
                suffix = (
                    "Pay Day / Delivery Date วันนี้"
                )

            message = (
                "รายละเอียดแจ้ง:\n"
                + format_row(
                    values
                )
            )

            self.add_sale_notification(
                (
                    f"{self._sale_title(branch)} "
                    f"- {suffix}"
                ),
                message,
                "due",
            )

    # =========================================
    # Close
    # =========================================

    def closeEvent(
        self,
        event,
    ):

        for timer in (
            self.sale_sheet_timer,
            self.sale_sheet_timer_srinakarin,
            self.sale_sheet_timer_sa,
            self.sale_sheet_timer_main_noti,
            self.main_notification_timer,
        ):

            timer.stop()

        try:
            self.cloud.stop()
        except Exception:
            pass

        event.accept()

    # =========================================
    # Window Position
    # =========================================

    def move_to_bottom_right(self):

        screen = (
            QApplication.primaryScreen()
        )

        if screen is None:
            return

        screen_geometry = (
            screen.availableGeometry()
        )

        x = (
            screen_geometry.right()
            - self.width()
            - 20
        )

        y = (
            screen_geometry.bottom()
            - self.height()
            - 20
        )

        self.move(
            x,
            y,
        )

    # =========================================
    # Collapse / Expand
    # =========================================

    def toggle_window(self):

        if self.is_collapsed:

            self.setFixedHeight(
                self.expanded_height
            )

            self.pages.show()

            self.search_input.show()

            self.sale_alert_button.show()

            self.sale_alert_button_srinakarin.show()

            self.sa_notify_button.show()

            self.menu_button.show()

            self.save_background_button.show()

            self.notification_container.show()

            self.collapse_button.setText(
                "−"
            )

            self.is_collapsed = False

        else:

            self.setFixedHeight(
                self.collapsed_height
            )

            self.pages.hide()

            self.search_input.hide()

            self.sale_alert_button.hide()

            self.sale_alert_button_srinakarin.hide()

            self.sa_notify_button.hide()

            self.menu_button.hide()

            self.save_background_button.hide()

            self.notification_container.hide()

            self.collapse_button.setText(
                "＋"
            )

            self.is_collapsed = True

        self.move_to_bottom_right()


# =============================================
# Main
# =============================================

if __name__ == "__main__":

    app = QApplication(
        sys.argv
    )

    app.setOrganizationName(
        APP_ORGANIZATION
    )

    app.setApplicationName(
        APP_NAME
    )

    app.setApplicationDisplayName(
        APP_DISPLAY_NAME
    )

    window = DailyLog()

    if not getattr(
        window,
        "database_ready",
        False,
    ):
        sys.exit(0)

    window.show()

    sys.exit(
        app.exec()
    )