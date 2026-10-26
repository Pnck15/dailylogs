"""Standalone VAT Calculator with auto-update, startup and manual update menu."""
import os
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QMenu,
    QMessageBox, QPushButton,
)

from dailylog_finance import WithholdingCalculator
from workers import run_async

VAT_CALCULATOR_VERSION = "1.0.0"
VAT_DISPLAY_TITLE = "VAT Calculator 增值税计算器"
VAT_CREDIT = "by 王纯真"
RUN_KEY = "DailyLogVATCalculator"


def set_vat_start_with_windows(enabled, executable=None):
    """Enable/disable HKCU per-user startup, no administrator access needed."""
    executable = executable or (sys.executable if getattr(sys, "frozen", False) else "")
    if not executable or not Path(executable).is_file():
        raise ValueError("เปิดพร้อม Windows ต้องใช้โปรแกรม VATCalculator.exe")
    settings = QSettings(
        r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run",
        QSettings.Format.NativeFormat,
    )
    if enabled:
        settings.setValue(RUN_KEY, f'"{executable}"')
    else:
        settings.remove(RUN_KEY)
    settings.sync()
    if settings.status() != QSettings.Status.NoError:
        raise OSError("ไม่สามารถบันทึก Windows Startup ได้")
    return bool(settings.value(RUN_KEY, ""))


class VATCalculatorWindow(WithholdingCalculator):
    """Inherits the exact 3 tab calculations used by DailyLog.exe."""

    def __init__(self, parent=None, standalone=False):
        super().__init__(parent)
        self.setWindowTitle(VAT_DISPLAY_TITLE)
        self._standalone = bool(standalone)
        self._settings = QSettings("MiniDailyLog", "VATCalculator")
        self._checking_update = False
        self._last_update_attempt = 0.0
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        header = QHBoxLayout()
        header.addWidget(QLabel(VAT_DISPLAY_TITLE), 1)
        self.menu_button = QPushButton("☰")
        self.menu_button.setObjectName("vatOptionsMenu")
        self.menu_button.setFixedWidth(35)
        header.addWidget(self.menu_button)
        self.layout().insertLayout(0, header)
        self.menu = QMenu(self)
        self.top_action = self.menu.addAction("อยู่ด้านบนสุด (Always on Top)")
        self.top_action.setCheckable(True)
        self.top_action.setChecked(True)
        self.top_action.triggered.connect(self._on_top)
        self.startup_action = self.menu.addAction("เปิดอัตโนมัติเมื่อเข้า Windows")
        self.startup_action.setCheckable(True)
        self.startup_action.setEnabled(self._can_self_update())
        self.startup_action.setChecked(self._is_startup_enabled())
        self.startup_action.triggered.connect(self._set_startup)
        self.auto_action = self.menu.addAction("อัปเดตอัตโนมัติ")
        self.auto_action.setCheckable(True)
        self.auto_action.setChecked(
            self._settings.value("updates/auto_enabled", True, type=bool)
        )
        self.auto_action.setEnabled(self._can_self_update())
        self.auto_action.triggered.connect(self._toggle_auto)
        self.check_action = self.menu.addAction("ตรวจสอบอัปเดต")
        self.check_action.setEnabled(self._can_self_update())
        self.check_action.triggered.connect(
            lambda: self.check_for_updates(manual=True)
        )
        self.menu.addSeparator()
        self.menu.addAction(
            f"VAT Calculator v{VAT_CALCULATOR_VERSION} · {VAT_CREDIT}"
        )
        self.menu_button.setMenu(self.menu)

        if self._can_self_update():
            self._update_timer = QTimer(self)
            self._update_timer.setInterval(15 * 60 * 1000)
            self._update_timer.timeout.connect(self._auto_update_tick)
            self._update_timer.start()
            QTimer.singleShot(8000, self._auto_update_tick)

    def _can_self_update(self):
        return (
            self._standalone
            and bool(getattr(sys, "frozen", False))
            and Path(sys.executable).name.lower() == "vatcalculator.exe"
        )

    def _on_top(self, checked):
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(checked))
        if visible:
            self.show()

    def _is_startup_enabled(self):
        if not self._can_self_update():
            return False
        settings = QSettings(
            r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run",
            QSettings.Format.NativeFormat,
        )
        return bool(settings.value(RUN_KEY, ""))

    def _set_startup(self, checked):
        try:
            self.startup_action.setChecked(set_vat_start_with_windows(checked))
        except (ValueError, OSError) as error:
            self.startup_action.setChecked(self._is_startup_enabled())
            QMessageBox.warning(self, VAT_DISPLAY_TITLE, str(error))

    def _toggle_auto(self, checked):
        self._settings.setValue("updates/auto_enabled", bool(checked))
        self._settings.sync()

    def _auto_update_tick(self):
        if self.auto_action.isChecked():
            self.check_for_updates()

    def check_for_updates(self, manual=False):
        if not self._can_self_update():
            if manual:
                QMessageBox.information(
                    self, VAT_DISPLAY_TITLE,
                    "ตัวที่เปิดจาก DailyLog.exe จะอัปเดตพร้อมโปรแกรมหลัก\n"
                    + VAT_CREDIT,
                )
            return
        if self._checking_update:
            return
        if not manual and time.time() - self._last_update_attempt < 15 * 60:
            return
        self._checking_update = True
        self._last_update_attempt = time.time()

        from vat_calculator_updates import fetch_vat_update, prepare_vat_update

        def lookup():
            info = fetch_vat_update(VAT_CALCULATOR_VERSION)
            if info.get("available"):
                info = prepare_vat_update(info, Path(sys.executable).parent)
            return info

        def success(info):
            self._checking_update = False
            if not info.get("available"):
                if manual:
                    QMessageBox.information(
                        self, VAT_DISPLAY_TITLE,
                        f"คุณใช้เวอร์ชันล่าสุดแล้ว v{VAT_CALCULATOR_VERSION}\n"
                        + VAT_CREDIT,
                    )
                return
            if manual:
                choice = QMessageBox.question(
                    self, VAT_DISPLAY_TITLE + " — Update",
                    f"พบ VAT Calculator v{info['latest']}\n"
                    "ติดตั้งอัปเดตและเปิดโปรแกรมใหม่หรือไม่?\n\n"
                    + VAT_CREDIT,
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                )
                if choice != QMessageBox.StandardButton.Yes:
                    return
            helper = Path(sys.executable).parent / "DailyLogUpdater.exe"
            cmd = [
                str(helper), str(os.getpid()), sys.executable,
                info["prepared_file"], info["vat_sha256"],
            ]
            try:
                subprocess.Popen(cmd, close_fds=True)
                QApplication.quit()
            except (OSError, ValueError) as error:
                QMessageBox.warning(
                    self, VAT_DISPLAY_TITLE + " — Update",
                    f"เริ่มอัปเดตไม่สำเร็จ: {error}\n\n{VAT_CREDIT}",
                )

        def failed(error):
            self._checking_update = False
            if manual:
                QMessageBox.warning(
                    self, VAT_DISPLAY_TITLE + " — Update",
                    f"ตรวจสอบอัปเดตไม่สำเร็จ: {str(error)[:240]}\n\n{VAT_CREDIT}",
                )

        run_async(self, lookup, success, failed)
