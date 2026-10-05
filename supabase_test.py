import sys
import os
import re
import sqlite3
import difflib
from datetime import datetime
from PySide6.QtCore import QTimer

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
)

from PySide6.QtCore import (
    Qt,
    QDate,
    QLocale,
    QSettings,
)

from PySide6.QtGui import (
    QColor,
    QPalette,
    QPixmap,
    QImage,
    QTextCharFormat,
    QIcon,
)


# =================================
# Application Constants
# =================================

APP_ORGANIZATION = "MiniDailyLog"
APP_NAME = "DailyLog"
APP_DISPLAY_NAME = "日記記錄"
DEFAULT_ACCENT = "#2563EB"


# =================================
# Database Connection / Path
# =================================

DATABASE_PATH = None


def get_application_directory():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def is_usable_sqlite_database(file_path):
    """Check SQLite header + read access without modifying the file."""
    if not file_path or not os.path.isfile(file_path):
        return False

    try:
        with open(file_path, "rb") as file:
            header = file.read(16)

        if header != b"SQLite format 3\x00":
            return False

        uri = (
            "file:"
            + os.path.abspath(file_path).replace("\\", "/")
            + "?mode=ro"
        )

        connection = sqlite3.connect(uri, uri=True, timeout=5)
        connection.execute(
            "SELECT name FROM sqlite_master LIMIT 1"
        ).fetchone()
        connection.close()
        return True

    except (OSError, sqlite3.Error):
        return False


def get_database_latest_log(file_path):
    try:
        uri = (
            "file:"
            + os.path.abspath(file_path).replace("\\", "/")
            + "?mode=ro"
        )

        connection = sqlite3.connect(uri, uri=True, timeout=5)

        connection.execute(
            "SELECT 1 FROM logs LIMIT 1"
        )

        row = connection.execute("""
            SELECT log_date, log_time
            FROM logs
            ORDER BY log_date DESC, log_time DESC
            LIMIT 1
        """).fetchone()

        connection.close()

        if not row:
            return ("", "")

        return (
            str(row[0] or ""),
            str(row[1] or ""),
        )

    except sqlite3.Error:
        return ("", "")


def find_database_path(saved_path=""):
    app_dir = get_application_directory()
    candidates = []

    def add_candidate(path):
        if not path:
            return

        path = os.path.abspath(os.fspath(path))

        if path not in candidates:
            candidates.append(path)

    add_candidate(saved_path)
    add_candidate(os.path.join(app_dir, "daily_log.db"))

    # Important existing locations in this project
    for relative_path in (
        os.path.join("dist", "daily_log.db"),
        os.path.join("dist", "DailyLog", "daily_log.db"),
        os.path.join("Dlist", "daily_log.db"),
        os.path.join("Dlist", "DailyLog", "daily_log.db"),
    ):
        add_candidate(os.path.join(app_dir, relative_path))

    add_candidate(os.path.join(os.path.dirname(app_dir), "daily_log.db"))
    add_candidate(r"C:\DailyLogRecovery\daily_log.db")

    search_roots = [
        app_dir,
        os.path.join(app_dir, "dist"),
        os.path.join(app_dir, "Dlist"),
        r"C:\DailyLogRecovery",
    ]

    for root in search_roots:
        if not os.path.isdir(root):
            continue

        try:
            for current_root, directories, files in os.walk(root):
                directories[:] = [
                    d for d in directories
                    if d not in {".venv", "__pycache__", "site-packages"}
                ]
                if "daily_log.db" in files:
                    add_candidate(
                        os.path.join(current_root, "daily_log.db")
                    )
        except OSError:
            continue

    valid_databases = []

    for path in candidates:
        if not is_usable_sqlite_database(path):
            continue

        latest_date, latest_time = get_database_latest_log(path)

        try:
            modified_time = os.path.getmtime(path)
        except OSError:
            modified_time = 0

        valid_databases.append(
            (path, latest_date, latest_time, modified_time)
        )

    if valid_databases:
        valid_databases.sort(
            key=lambda item: (
                item[1],
                item[2],
                item[3],
            ),
            reverse=True,
        )
        return valid_databases[0][0]

    return os.path.join(app_dir, "daily_log.db")


def configure_database_path(path):
    global DATABASE_PATH
    DATABASE_PATH = os.path.abspath(path)


def get_connection():
    if not DATABASE_PATH:
        configure_database_path(
            os.path.join(
                get_application_directory(),
                "daily_log.db",
            )
        )

    return sqlite3.connect(DATABASE_PATH)



# =================================
# Main Window
# =================================

class DailyLog(QWidget):

    def __init__(self):
        super().__init__()

        # -------------------------
        # Window
        # -------------------------

        self.setWindowTitle(APP_DISPLAY_NAME)

        self.expanded_width = 620
        self.expanded_height = 360
        self.collapsed_height = 45

        self.setFixedSize(
            self.expanded_width,
            self.expanded_height,
        )

        self.setWindowFlag(
            Qt.WindowType.WindowStaysOnTopHint
        )

        # -------------------------
        # State
        # -------------------------

        self.is_collapsed = False
        self.selected_date = QDate.currentDate()
        self.calendar_marked_dates = set()

        # Sale Delivery Plan monitor
        self.sale_sheet_url = ""
        self.sale_sheet_snapshot = {}
        self.sale_sheet_enabled = False
        self.sale_sheet_timer = QTimer(self)
        self.sale_sheet_timer.setInterval(60000)  # ตรวจทุก 60 วินาที
        self.sale_sheet_timer.timeout.connect(self.check_sale_delivery_plan)

        # -------------------------
        # Settings
        # -------------------------

        self.settings = QSettings(
            APP_ORGANIZATION,
            APP_NAME,
        )

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

        self.sale_sheet_url = str(
            self.settings.value("sale_sheet_url", "")
        )

        # -------------------------
        # Database Path
        # -------------------------

        self.database_path = find_database_path(
            self.settings.value(
                "database_path",
                "",
            )
        )

        configure_database_path(
            self.database_path
        )

        # -------------------------
        # Background / Text State
        # -------------------------

        self.background_is_dark = False

        # -------------------------
        # Database
        # -------------------------

        if not self.init_database():

            QTimer.singleShot(
                0,
                QApplication.quit,
            )

            return

        # -------------------------
        # Theme
        # -------------------------

        self.apply_theme()

        # -------------------------
        # Page Manager
        # -------------------------

        self.pages = QStackedWidget()

        self.calendar_page = self.create_calendar_page()
        self.add_page = self.create_add_page()

        self.pages.addWidget(
            self.calendar_page
        )

        self.pages.addWidget(
            self.add_page
        )

        # -------------------------
        # Header
        # -------------------------

        self.title = QLabel(
            APP_DISPLAY_NAME
        )

        # -------------------------
        # Search
        # -------------------------

        self.search_input = QLineEdit()

        self.search_input.setPlaceholderText(
            "Search..."
        )

        self.search_input.setMinimumWidth(
            180
        )

        self.search_input.setMaximumWidth(
            240
        )

        self.search_input.textChanged.connect(
            self.search_logs
        )

        # -------------------------
        # Sale Delivery Plan Button
        # -------------------------

        self.sale_alert_button = QPushButton("แจ้งเตือน Sale Delivery Plan")
        self.sale_alert_button.clicked.connect(
            self.configure_sale_delivery_plan
        )

        # -------------------------
        # Menu Button
        # -------------------------

        self.menu_button = QPushButton(
            "☰"
        )

        self.menu_button.setFixedSize(
            32,
            28,
        )

        self.menu_button.clicked.connect(
            self.show_settings_menu
        )

        # -------------------------
        # Collapse Button
        # -------------------------

        self.collapse_button = QPushButton(
            "−"
        )

        self.collapse_button.setFixedSize(
            32,
            28,
        )

        self.collapse_button.clicked.connect(
            self.toggle_window
        )

        # -------------------------
        # Header Layout
        # -------------------------

        header = QHBoxLayout()
        header.setSpacing(6)

        header.addWidget(
            self.title
        )

        header.addWidget(
            self.search_input
        )

        header.addWidget(
            self.sale_alert_button
        )

        header.addStretch()

        header.addWidget(
            self.menu_button
        )

        header.addWidget(
            self.collapse_button
        )

        # -------------------------
        # Main Layout
        # -------------------------

        main_layout = QVBoxLayout()

        main_layout.setContentsMargins(
            10,
            8,
            10,
            8,
        )

        main_layout.setSpacing(6)

        main_layout.addLayout(
            header
        )

        main_layout.addWidget(
            self.pages
        )

        self.setLayout(
            main_layout
        )

        # -------------------------
        # Restore Saved Icon
        # -------------------------

        self.restore_saved_icon()

        # -------------------------
        # Move Window
        # -------------------------

        self.move_to_bottom_right()

        # -------------------------
        # Current Date
        # -------------------------

        self.update_daily_logs(
            self.selected_date
        )

        if self.sale_sheet_url:
            self.sale_sheet_enabled = True
            self.sale_alert_button.setText("🟢 Sale Delivery Plan: ON")
            self.check_sale_delivery_plan(initial=True)
            self.sale_sheet_timer.start()

        # -------------------------
        # Restore Background
        # -------------------------

        self.restore_saved_background()

    # =================================
    # Theme
    # =================================

    def apply_theme(self):

        accent = self.current_accent

        # ---------------------------------
        # Text Color
        # ---------------------------------

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

        # ---------------------------------
        # Main Theme
        # ---------------------------------

        self.setStyleSheet(f"""

            DailyLog {{
                background: transparent;
                color: {main_text};
                font-family: Arial;
                font-size: 13px;
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
                padding: 5px 10px;
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
                padding: 6px 9px;
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

            /* ==========================
               Calendar
               ========================== */

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
                padding: 4px;
                font-size: 12px;
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
                font-size: 11px;
                outline: none;
            }}

            /* ==========================
               Logs
               ========================== */

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

            /* ==========================
               Menu
               ========================== */

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

            /* ==========================
               Scrollbar
               ========================== */

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

        """)

        # ---------------------------------
        # Selected Date
        # ---------------------------------

        if hasattr(self, "selected_date_label"):

            self.selected_date_label.setStyleSheet(
                f"""
                color: {accent};
                background: transparent;
                font-weight: bold;
                padding: 4px;
                """
            )

        # ---------------------------------
        # Logs Title
        # ---------------------------------

        if hasattr(self, "logs_title"):

            self.logs_title.setStyleSheet(
                f"""
                color: {accent};
                background: transparent;
                font-size: 14px;
                font-weight: bold;
                padding: 4px;
                """
            )

        # ---------------------------------
        # Add Date
        # ---------------------------------

        if hasattr(self, "add_date_label"):

            self.add_date_label.setStyleSheet(
                f"""
                color: {accent};
                background: transparent;
                font-weight: bold;
                padding: 6px;
                """
            )

        # ---------------------------------
        # Main Title
        # ---------------------------------

        if hasattr(self, "title"):

            self.title.setStyleSheet(
                f"""
                color: {main_text};
                background: transparent;
                font-size: 16px;
                font-weight: bold;
                """
            )

        # ---------------------------------
        # Refresh Calendar Markers
        # ---------------------------------

        if hasattr(self, "calendar"):
            self.update_calendar_log_markers()

    # =================================
    # Detect Background Brightness
    # =================================

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

        for y in range(image.height()):

            for x in range(image.width()):

                color = image.pixelColor(x, y)

                brightness = (
                    0.299 * color.red()
                    + 0.587 * color.green()
                    + 0.114 * color.blue()
                )

                total_brightness += brightness
                pixel_count += 1

        if pixel_count == 0:
            return False

        average_brightness = (
            total_brightness / pixel_count
        )

        return average_brightness < 128

    # =================================
    # Restore Saved Icon
    # =================================

    def restore_saved_icon(self):

        if not self.icon_path:
            return

        if not os.path.isfile(self.icon_path):
            self.icon_path = ""
            self.settings.setValue(
                "icon_path",
                "",
            )
            self.settings.sync()
            return

        icon = QIcon(self.icon_path)

        if icon.isNull():
            return

        self.setWindowIcon(icon)

        app = QApplication.instance()

        if app is not None:
            app.setWindowIcon(icon)

    # =================================
    # Restore Saved Background
    # =================================

    def restore_saved_background(self):

        if not self.background_path:
            return

        if not os.path.isfile(self.background_path):
            self.background_path = ""
            self.settings.setValue(
                "background_path",
                "",
            )
            self.settings.sync()
            return

        self.apply_background(
            self.background_path
        )

    # =================================
    # Settings Menu
    # =================================

    def show_settings_menu(self):

        menu = QMenu(self)

        # ---------------------------------
        # Change Color
        # ---------------------------------

        color_action = menu.addAction(
            "🎨 Change Program Color"
        )

        color_action.triggered.connect(
            self.change_program_color
        )

        # ---------------------------------
        # Change Icon
        # ---------------------------------

        icon_action = menu.addAction(
            "🖼 Change Program Icon (.ico)"
        )

        icon_action.triggered.connect(
            self.change_program_icon
        )

        # ---------------------------------
        # Background
        # ---------------------------------

        background_action = menu.addAction(
            "🌄 Set Background Image"
        )

        background_action.triggered.connect(
            self.choose_background
        )

        # ---------------------------------
        # Remove Background
        # ---------------------------------

        remove_background_action = menu.addAction(
            "✕ Remove Background"
        )

        remove_background_action.triggered.connect(
            self.remove_background
        )

        menu.addSeparator()

        # ---------------------------------
        # Reset Color
        # ---------------------------------

        reset_color_action = menu.addAction(
            "↺ Reset Program Color"
        )

        reset_color_action.triggered.connect(
            self.reset_program_color
        )

        # ---------------------------------
        # Reset Icon
        # ---------------------------------

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

    # =================================
    # Change Program Color
    # =================================

    def change_program_color(self):

        color = QColorDialog.getColor(
            QColor(self.current_accent),
            self,
            "Choose Program Color",
        )

        if not color.isValid():
            return

        self.current_accent = color.name()

        self.settings.setValue(
            "accent_color",
            self.current_accent,
        )

        self.settings.sync()

        self.apply_theme()

    # =================================
    # Reset Program Color
    # =================================

    def reset_program_color(self):

        self.current_accent = DEFAULT_ACCENT

        self.settings.setValue(
            "accent_color",
            self.current_accent,
        )

        self.settings.sync()

        self.apply_theme()

    # =================================
    # Change Program Icon
    # =================================

    def change_program_icon(self):

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Program Icon",
            "",
            "ICO files (*.ico)",
        )

        if not file_path:
            return

        file_path = os.path.abspath(file_path)

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

        self.setWindowIcon(icon)

        app = QApplication.instance()

        if app is not None:
            app.setWindowIcon(icon)

    # =================================
    # Reset Program Icon
    # =================================

    def reset_program_icon(self):

        self.icon_path = ""

        self.settings.setValue(
            "icon_path",
            "",
        )

        self.settings.sync()

        self.setWindowIcon(QIcon())

        app = QApplication.instance()

        if app is not None:
            app.setWindowIcon(QIcon())

    # =================================
    # Choose Background
    # =================================

    def choose_background(self):

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Background Image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)",
        )

        if not file_path:
            return

        file_path = os.path.abspath(file_path)

        self.background_path = file_path

        self.settings.setValue(
            "background_path",
            self.background_path,
        )

        self.settings.sync()

        self.apply_background(
            self.background_path
        )

    # =================================
    # Apply Background
    # =================================

    def apply_background(
        self,
        file_path,
    ):

        if not file_path or not os.path.isfile(file_path):
            return

        pixmap = QPixmap(file_path)

        if pixmap.isNull():

            QMessageBox.warning(
                self,
                "Background Error",
                "ไม่สามารถเปิดรูปภาพนี้ได้",
            )

            return

        # ---------------------------------
        # Save Path Again
        # ---------------------------------

        self.background_path = os.path.abspath(
            file_path
        )

        self.settings.setValue(
            "background_path",
            self.background_path,
        )

        self.settings.sync()

        # ---------------------------------
        # Detect Brightness
        # ---------------------------------

        self.background_is_dark = (
            self.detect_background_brightness(
                self.background_path
            )
        )

        # ---------------------------------
        # Apply Theme
        # ---------------------------------

        self.apply_theme()

        # ---------------------------------
        # Scale Background
        # ---------------------------------

        scaled_pixmap = pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )

        # ---------------------------------
        # Center Crop
        # ---------------------------------

        x = max(
            0,
            (
                scaled_pixmap.width()
                - self.width()
            ) // 2,
        )

        y = max(
            0,
            (
                scaled_pixmap.height()
                - self.height()
            ) // 2,
        )

        scaled_pixmap = scaled_pixmap.copy(
            x,
            y,
            self.width(),
            self.height(),
        )

        # ---------------------------------
        # Palette
        # ---------------------------------

        palette = self.palette()

        palette.setBrush(
            QPalette.ColorRole.Window,
            scaled_pixmap,
        )

        self.setPalette(palette)
        self.setAutoFillBackground(True)

        self.update_calendar_log_markers()

    # =================================
    # Remove Background
    # =================================

    def remove_background(self):

        self.background_path = ""
        self.background_is_dark = False

        self.settings.setValue(
            "background_path",
            "",
        )

        self.settings.sync()

        self.setAutoFillBackground(False)
        self.setPalette(QApplication.palette())

        self.apply_theme()

    # =================================
    # Database
    # =================================

    def init_database(self):

        try:

            if os.path.exists(self.database_path):

                if not is_usable_sqlite_database(
                    self.database_path
                ):

                    QMessageBox.critical(
                        self,
                        "Database Error",
                        (
                            "นี่ไม่ใช่ SQLite database ที่ใช้งานได้\n\n"
                            f"{self.database_path}\n\n"
                            "โปรแกรมจะไม่ลบหรือเขียนทับไฟล์นี้ "
                            "เพื่อป้องกันข้อมูลหาย"
                        ),
                    )

                    return False

            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    log_date TEXT NOT NULL,
                    log_time TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT
                )
            """)

            connection.commit()
            connection.close()

            self.settings.setValue(
                "database_path",
                self.database_path,
            )

            self.settings.sync()

            return True

        except (sqlite3.Error, OSError) as error:

            QMessageBox.critical(
                self,
                "Database Error",
                (
                    "ไม่สามารถเปิด SQLite database ได้\n\n"
                    f"{self.database_path}\n\n"
                    f"รายละเอียด: {error}"
                ),
            )

            return False

    # =================================
    # Calendar Page
    # =================================

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

        # =================================
        # LEFT SIDE
        # Calendar
        # =================================

        calendar_container = QWidget()
        calendar_layout = QVBoxLayout()

        calendar_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        calendar_layout.setSpacing(4)

        # -------------------------
        # Date Label
        # -------------------------

        self.selected_date_label = QLabel()

        self.selected_date_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        # -------------------------
        # Calendar
        # -------------------------

        self.calendar = QCalendarWidget()

        self.calendar.setGridVisible(True)

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

        self.calendar.setMinimumWidth(275)
        self.calendar.setMaximumWidth(300)
        self.calendar.setMinimumHeight(210)
        self.calendar.setMaximumHeight(235)

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

        # -------------------------
        # Add Button
        # -------------------------

        self.add_button = QPushButton(
            "+ Add Log"
        )

        self.add_button.clicked.connect(
            self.open_add_page
        )

        calendar_layout.addWidget(
            self.selected_date_label
        )

        calendar_layout.addWidget(
            self.calendar,
            alignment=Qt.AlignmentFlag.AlignCenter,
        )

        calendar_layout.addWidget(
            self.add_button
        )

        calendar_container.setLayout(
            calendar_layout
        )

        # =================================
        # RIGHT SIDE
        # Daily Logs
        # =================================

        logs_container = QWidget()
        logs_layout = QVBoxLayout()

        logs_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        logs_layout.setSpacing(5)

        self.logs_title = QLabel("Logs")

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

        # -------------------------
        # Main
        # -------------------------

        main_layout.addWidget(
            calendar_container,
            0,
        )

        main_layout.addWidget(
            logs_container,
            1,
        )

        page.setLayout(main_layout)

        self.update_selected_date(
            self.selected_date
        )

        return page

    # =================================
    # Calendar Page Changed
    # =================================

    def calendar_page_changed(
        self,
        year,
        month,
    ):

        self.update_calendar_log_markers()

    # =================================
    # Calendar Log Markers
    # =================================

    def update_calendar_log_markers(self):

        if not hasattr(self, "calendar"):
            return

        # ---------------------------------
        # Clear Previous Formats
        # ---------------------------------

        for date_string in self.calendar_marked_dates:

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

        # ---------------------------------
        # Get Log Dates
        # ---------------------------------

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT DISTINCT log_date
            FROM logs
        """)

        log_dates = {
            row[0]
            for row in cursor.fetchall()
        }

        connection.close()

        # ---------------------------------
        # Visible Calendar Month
        # ---------------------------------

        year = self.calendar.yearShown()
        month = self.calendar.monthShown()

        first_date = QDate(
            year,
            month,
            1,
        )

        # ---------------------------------
        # Find Start Of Visible Calendar
        # ---------------------------------

        first_day_of_week = (
            self.calendar
            .locale()
            .firstDayOfWeek()
            .value
        )

        offset = (
            first_date.dayOfWeek()
            - first_day_of_week
        ) % 7

        display_start = first_date.addDays(
            -offset
        )

        # ---------------------------------
        # Display 6 Weeks
        # ---------------------------------

        for day_offset in range(42):

            current_date = display_start.addDays(
                day_offset
            )

            date_string = current_date.toString(
                "yyyy-MM-dd"
            )

            is_sunday = (
                current_date.dayOfWeek() == 7
            )

            has_log = (
                date_string in log_dates
            )

            if not is_sunday and not has_log:
                continue

            fmt = QTextCharFormat()

            # Sunday = Red
            if is_sunday:
                fmt.setForeground(
                    QColor("#EF4444")
                )

            # Other date with Log = Theme color
            elif has_log:
                if self.background_is_dark:
                    fmt.setForeground(
                        QColor("#FFFFFF")
                    )
                else:
                    fmt.setForeground(
                        QColor("#111827")
                    )

            # Log exists = Underline
            if has_log:
                font = fmt.font()
                font.setUnderline(True)
                fmt.setFont(font)

            self.calendar.setDateTextFormat(
                current_date,
                fmt,
            )

            self.calendar_marked_dates.add(
                date_string
            )

    # =================================
    # Date Selected
    # =================================

    def date_selected(
        self,
        date,
    ):

        self.selected_date = date

        self.update_selected_date(date)

        if not self.search_input.text().strip():
            self.update_daily_logs(date)

    # =================================
    # Update Selected Date
    # =================================

    def update_selected_date(
        self,
        date,
    ):

        formatted_date = date.toString(
            "ddd - dd/MM/yyyy"
        )

        self.selected_date_label.setText(
            f"Date: {formatted_date}"
        )

        self.logs_title.setText(
            f"Logs - {formatted_date}"
        )

    # =================================
    # Load Daily Logs
    # =================================

    def update_daily_logs(
        self,
        date,
    ):

        self.logs_list.clear()

        log_date = date.toString(
            "yyyy-MM-dd"
        )

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                id,
                log_time,
                title,
                description
            FROM logs
            WHERE log_date = ?
            ORDER BY log_time ASC
        """, (log_date,))

        selected_logs = cursor.fetchall()
        connection.close()

        if not selected_logs:

            item = QListWidgetItem(
                "ยังไม่มี Logs ในวันนี้"
            )

            item.setFlags(
                Qt.ItemFlag.NoItemFlags
            )

            self.logs_list.addItem(item)
            return

        for log in selected_logs:

            log_id = log[0]
            log_time = log[1]
            title = log[2]
            description = log[3] or ""

            text = (
                f"🕒 {log_time}\n"
                f"📝 {title}\n"
                f"{description}"
            )

            item = QListWidgetItem(text)

            item.setData(
                Qt.ItemDataRole.UserRole,
                log_id,
            )

            self.logs_list.addItem(item)

    # =================================
    # Search Logs
    # =================================

    def search_logs(
        self,
        text,
    ):

        keyword = text.strip()

        if not keyword:
            self.update_daily_logs(
                self.selected_date
            )
            return

        self.logs_list.clear()

        search_pattern = f"%{keyword}%"

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                id,
                log_date,
                log_time,
                title,
                description
            FROM logs
            WHERE
                title LIKE ?
                OR description LIKE ?
            ORDER BY
                log_date DESC,
                log_time DESC
        """, (search_pattern, search_pattern))

        results = cursor.fetchall()
        connection.close()

        self.logs_title.setText(
            f"Search Results: {len(results)}"
        )

        if not results:

            item = QListWidgetItem(
                f'ไม่พบ Log ที่มีคำว่า "{keyword}"'
            )

            item.setFlags(
                Qt.ItemFlag.NoItemFlags
            )

            self.logs_list.addItem(item)
            return

        for log in results:

            log_id = log[0]
            log_date = log[1]
            log_time = log[2]
            title = log[3]
            description = log[4] or ""

            text = (
                f"📅 {log_date}  🕒 {log_time}\n"
                f"📝 {title}\n"
                f"{description}"
            )

            item = QListWidgetItem(text)

            item.setData(
                Qt.ItemDataRole.UserRole,
                log_id,
            )

            self.logs_list.addItem(item)

    # =================================
    # Open Daily Logs
    # =================================

    def open_daily_logs(
        self,
        date,
    ):

        self.selected_date = date

        self.update_selected_date(date)
        self.update_daily_logs(date)

        formatted_date = date.toString(
            "dd/MM/yyyy"
        )

        dialog = QDialog(self)
        dialog.setWindowTitle(
            f"Daily Logs 日記 - {formatted_date}"
        )
        dialog.resize(520, 400)

        layout = QVBoxLayout()
        text_area = QTextEdit()
        text_area.setReadOnly(True)

        log_date = date.toString(
            "yyyy-MM-dd"
        )

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                id,
                log_time,
                title,
                description
            FROM logs
            WHERE log_date = ?
            ORDER BY log_time ASC
        """, (log_date,))

        selected_logs = cursor.fetchall()
        connection.close()

        if selected_logs:

            message = "\n\n".join(
                f"👍 {log[1]} | {log[2]}\n"
                f"{log[3] or ''}"
                for log in selected_logs
            )

        else:
            message = "ยังไม่มี Logs ในวันนี้"

        text_area.setPlainText(message)
        layout.addWidget(text_area)

        close_button = QPushButton("Close")
        close_button.clicked.connect(dialog.close)
        layout.addWidget(close_button)

        dialog.setLayout(layout)
        dialog.exec()

    # =================================
    # Edit Log From List
    # =================================

    def edit_log_from_list(
        self,
        item,
    ):

        log_id = item.data(
            Qt.ItemDataRole.UserRole
        )

        if log_id is None:
            return

        self.edit_log(log_id)

    # =================================
    # Edit Log
    # =================================

    def edit_log(
        self,
        log_id,
    ):

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT
                log_date,
                log_time,
                title,
                description
            FROM logs
            WHERE id = ?
        """, (log_id,))

        log = cursor.fetchone()
        connection.close()

        if not log:

            QMessageBox.warning(
                self,
                "Warning",
                "ไม่พบ Log นี้",
            )

            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Edit Log")
        dialog.resize(450, 350)

        layout = QVBoxLayout()

        date_label = QLabel(
            f"Date: {log[0]}    Time: {log[1]}"
        )

        title_label = QLabel("Title")
        title_input = QLineEdit()
        title_input.setText(log[2])

        description_label = QLabel("Description")
        description_input = QTextEdit()
        description_input.setPlainText(
            log[3] or ""
        )

        button_layout = QHBoxLayout()

        delete_button = QPushButton("Delete")
        save_button = QPushButton("Save")
        cancel_button = QPushButton("Cancel")

        button_layout.addWidget(delete_button)
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(save_button)

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

            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute("""
                UPDATE logs
                SET
                    title = ?,
                    description = ?
                WHERE id = ?
            """, (
                new_title,
                new_description,
                log_id,
            ))

            connection.commit()
            connection.close()

            self.update_calendar_log_markers()

            dialog.accept()

            if self.search_input.text().strip():

                self.search_logs(
                    self.search_input.text()
                )

            else:

                self.update_daily_logs(
                    self.selected_date
                )

        def delete_log():

            result = QMessageBox.question(
                dialog,
                "Confirm Delete",
                "ต้องการลบ Log นี้หรือไม่?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
            )

            if result != QMessageBox.StandardButton.Yes:
                return

            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute("""
                DELETE FROM logs
                WHERE id = ?
            """, (log_id,))

            connection.commit()
            connection.close()

            self.update_calendar_log_markers()

            dialog.accept()

            if self.search_input.text().strip():

                self.search_logs(
                    self.search_input.text()
                )

            else:

                self.update_daily_logs(
                    self.selected_date
                )

        save_button.clicked.connect(save_changes)
        delete_button.clicked.connect(delete_log)
        cancel_button.clicked.connect(dialog.reject)

        layout.addWidget(date_label)
        layout.addWidget(title_label)
        layout.addWidget(title_input)
        layout.addWidget(description_label)
        layout.addWidget(description_input)
        layout.addStretch()
        layout.addLayout(button_layout)

        dialog.setLayout(layout)
        dialog.exec()

    # =================================
    # Add Log Page
    # =================================

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

        title_label = QLabel("Title")

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
        self.description_input.setMinimumHeight(130)

        back_button = QPushButton("Back")
        back_button.clicked.connect(
            self.back_to_calendar
        )

        save_button = QPushButton("Save")
        save_button.clicked.connect(
            self.save_log
        )

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(back_button)
        button_layout.addWidget(save_button)

        layout.addWidget(self.add_date_label)
        layout.addWidget(title_label)
        layout.addWidget(self.title_input)
        layout.addWidget(description_label)
        layout.addWidget(self.description_input)
        layout.addStretch()
        layout.addLayout(button_layout)

        page.setLayout(layout)

        return page

    # =================================
    # Open Add Page
    # =================================

    def open_add_page(self):

        formatted_date = self.selected_date.toString(
            "ddd - dd/MM/yyyy"
        )

        self.add_date_label.setText(
            f"Date: {formatted_date}"
        )

        self.title_input.clear()
        self.description_input.clear()

        self.pages.setCurrentWidget(
            self.add_page
        )

    # =================================
    # Back To Calendar
    # =================================

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

    # =================================
    # Save Log
    # =================================

    def save_log(self):

        title = (
            self.title_input
            .text()
            .strip()
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

        log_date = self.selected_date.toString(
            "yyyy-MM-dd"
        )

        log_time = datetime.now().strftime(
            "%H:%M:%S"
        )

        connection = get_connection()
        cursor = connection.cursor()

        # -------------------------
        # Database เดิม
        # ไม่เปลี่ยน
        # -------------------------

        cursor.execute("""
            INSERT INTO logs (
                log_date,
                log_time,
                title,
                description
            )
            VALUES (?, ?, ?, ?)
        """, (
            log_date,
            log_time,
            title,
            description,
        ))

        connection.commit()
        connection.close()

        self.update_calendar_log_markers()

        QMessageBox.information(
            self,
            "Success",
            "บันทึก Log ลง Database สำเร็จ",
        )

        self.back_to_calendar()

    # =================================
    # Sale Delivery Plan Monitor
    # =================================

    def configure_sale_delivery_plan(self):

        dialog = QDialog(self)
        dialog.setWindowTitle("ตั้งค่าแจ้งเตือน Sale Delivery Plan")
        dialog.resize(520, 230)

        layout = QVBoxLayout(dialog)

        info = QLabel(
            "ใส่ลิงก์ Google Sheet ที่เปิดให้ดูได้\n"
            "แนะนำให้ใช้ลิงก์ Published to web / CSV\n"
            "ระบบจะตรวจคอลัมน์ F, H, K และ L ทุก 60 วินาที"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        url_input = QLineEdit()
        url_input.setPlaceholderText("Google Sheet URL หรือ CSV URL")
        url_input.setText(self.sale_sheet_url)
        layout.addWidget(url_input)

        button_layout = QHBoxLayout()
        start_button = QPushButton("เริ่มแจ้งเตือน")
        stop_button = QPushButton("หยุดแจ้งเตือน")
        cancel_button = QPushButton("ยกเลิก")

        button_layout.addWidget(start_button)
        button_layout.addWidget(stop_button)
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

        def start_monitoring():
            url = url_input.text().strip()
            if not url:
                QMessageBox.warning(dialog, "ข้อมูลไม่ครบ", "กรุณาใส่ลิงก์ Google Sheet")
                return
            self.sale_sheet_url = self.convert_sheet_url_to_csv(url)
            self.settings.setValue("sale_sheet_url", self.sale_sheet_url)
            self.settings.sync()
            self.sale_sheet_enabled = True
            self.sale_sheet_snapshot = {}
            self.check_sale_delivery_plan(initial=True)
            self.sale_sheet_timer.start()
            self.sale_alert_button.setText("🟢 Sale Delivery Plan: ON")
            dialog.accept()

        def stop_monitoring():
            self.sale_sheet_enabled = False
            self.sale_sheet_timer.stop()
            self.sale_alert_button.setText("แจ้งเตือน Sale Delivery Plan")
            dialog.accept()

        start_button.clicked.connect(start_monitoring)
        stop_button.clicked.connect(stop_monitoring)
        cancel_button.clicked.connect(dialog.reject)
        dialog.exec()

    def convert_sheet_url_to_csv(self, url):
        if "export?format=csv" in url or "output=csv" in url:
            return url

        import re
        match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
        if not match:
            return url

        sheet_id = match.group(1)
        gid_match = re.search(r"gid=([0-9]+)", url)
        gid = gid_match.group(1) if gid_match else "0"
        return (
            f"https://docs.google.com/spreadsheets/d/{sheet_id}/export"
            f"?format=csv&gid={gid}"
        )

    def fetch_sale_sheet_rows(self):
        request = urllib.request.Request(
            self.sale_sheet_url,
            headers={"User-Agent": "MiniDailyLog/1.0"}
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            raw_data = response.read().decode("utf-8-sig")

        return list(csv.reader(io.StringIO(raw_data)))

    def check_sale_delivery_plan(self, initial=False):
        if not self.sale_sheet_enabled or not self.sale_sheet_url:
            return

        try:
            rows = self.fetch_sale_sheet_rows()
        except Exception as error:
            self.show_sale_popup(
                "Sale Delivery Plan",
                f"ไม่สามารถอ่าน Google Sheet ได้\n{error}"
            )
            self.sale_sheet_timer.stop()
            self.sale_sheet_enabled = False
            self.sale_alert_button.setText("แจ้งเตือน Sale Delivery Plan")
            return

        current_snapshot = {}
        changed_items = []
        deleted_items = []

        # CSV index: F=5, H=7, K=10, L=11
        for row_number, row in enumerate(rows[1:], start=2):
            padded = row + [""] * max(0, 12 - len(row))
            key = f"row-{row_number}"
            values = tuple(padded[index].strip() for index in (5, 7, 10, 11))
            current_snapshot[key] = values

            if not initial and self.sale_sheet_snapshot.get(key) != values:
                changed_items.append((row_number, values))

            if not initial:
                self.check_due_date(values, row_number)

        if not initial:
            for key in self.sale_sheet_snapshot:
                if key not in current_snapshot:
                    deleted_items.append(key)

            if changed_items or deleted_items:
                parts = []
                if changed_items:
                    parts.append(f"แก้ไข/บันทึก {len(changed_items)} แถว")
                if deleted_items:
                    parts.append(f"ลบ {len(deleted_items)} แถว")
                self.show_sale_popup(
                    "Sale Delivery Plan มีการเปลี่ยนแปลง",
                    "\n".join(parts)
                )

        self.sale_sheet_snapshot = current_snapshot

    def check_due_date(self, values, row_number):
        due_text = values[3]
        if not due_text:
            return

        possible_formats = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y"]
        due_date = None
        for date_format in possible_formats:
            try:
                due_date = datetime.strptime(due_text[:10], date_format).date()
                break
            except ValueError:
                continue

        if due_date is None:
            return

        today = datetime.now().date()
        notification_key = f"due-{row_number}-{due_date.isoformat()}"
        if due_date == today and not self.settings.value(notification_key, False, type=bool):
            self.show_sale_popup(
                "ถึงกำหนด Sale Delivery Plan วันนี้",
                f"แถวที่ {row_number}\nF: {values[0]}\nH: {values[1]}\nK: {values[2]}\nL: {values[3]}"
            )
            self.settings.setValue(notification_key, True)
            self.settings.sync()

    def show_sale_popup(self, title, message):
        popup = QDialog(self, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        popup.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        popup.setWindowTitle(title)
        popup.setFixedSize(330, 145)
        popup.setStyleSheet("""
            QDialog { background-color: #FFFFFF; border: 2px solid #2563EB; border-radius: 10px; }
            QLabel { color: #111827; background: transparent; }
            QPushButton { padding: 5px 12px; border: 1px solid #CBD5E1; border-radius: 6px; }
        """)

        layout = QVBoxLayout(popup)
        title_label = QLabel(f"🔔 {title}")
        title_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        message_label = QLabel(message)
        message_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(message_label)
        close_button = QPushButton("ปิด")
        close_button.clicked.connect(popup.close)
        layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignRight)

        screen = QApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            popup.move(area.right() - popup.width() - 20, area.top() + 20)
        popup.show()
        popup.raise_()
        popup.activateWindow()
        popup.setModal(False)
        popup.show()

    # =================================
    # Move Window
    # =================================

    def move_to_bottom_right(self):

        screen = QApplication.primaryScreen()

        if screen is None:
            return

        screen_geometry = screen.availableGeometry()

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

        self.move(x, y)

    # =================================
    # Collapse / Expand
    # =================================

    def toggle_window(self):

        if self.is_collapsed:

            self.setFixedHeight(
                self.expanded_height
            )

            self.pages.show()
            self.search_input.show()
            self.sale_alert_button.show()
            self.menu_button.show()

            self.collapse_button.setText("−")
            self.is_collapsed = False

        else:

            self.setFixedHeight(
                self.collapsed_height
            )

            self.pages.hide()
            self.search_input.hide()
            self.sale_alert_button.hide()
            self.menu_button.hide()

            self.collapse_button.setText("＋")
            self.is_collapsed = True

        self.move_to_bottom_right()


# =================================
# Application
# =================================

if __name__ == "__main__":

    app = QApplication(sys.argv)

    # กำหนดชื่อ Application ให้คงที่
    # เพื่อให้ QSettings ใช้ชุด Settings เดิมทุกครั้ง
    app.setOrganizationName(APP_ORGANIZATION)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)

    window = DailyLog()
    window.show()

    sys.exit(app.exec())
