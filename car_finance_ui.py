"""Always-on-top car finance calculator, shared by DailyLog and standalone EXE."""
import os
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QDialog, QDoubleSpinBox,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox,
    QPushButton, QSpinBox, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from car_finance_math import DOWN_OPTIONS, finance_quote, quote_text

CAR_CALCULATOR_VERSION = "1.0.0"


def set_start_with_windows(enabled, executable=None):
    """HKCU Run entry; only the standalone frozen EXE can register startup."""
    if executable is None:
        executable = sys.executable if getattr(sys, "frozen", False) else ""
    if not executable or not Path(executable).is_file():
        raise ValueError("ต้องใช้ FinanceCalculator.exe เวอร์ชัน Build สำหรับ Startup")
    registry = QSettings(
        r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run",
        QSettings.Format.NativeFormat,
    )
    if enabled:
        registry.setValue("DailyLogFinanceCalculator", f'"{executable}"')
    else:
        registry.remove("DailyLogFinanceCalculator")
    registry.sync()
    if registry.status() != QSettings.Status.NoError:
        raise OSError("ไม่สามารถบันทึก Windows Startup Registry ได้")
    return bool(registry.value("DailyLogFinanceCalculator", ""))


class CarFinanceCalculator(QDialog):
    """Top-level, non-modal calculator; stays above other windows until minimized."""

    def __init__(self, parent=None, standalone=False):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowMinimizeButtonHint | Qt.WindowType.WindowCloseButtonHint
        )
        self.setModal(False)
        self.setWindowTitle("คำนวณเงินดาวน์ / ดอกเบี้ย / ค่าคอมมิชชั่น")
        self.resize(515, 685)
        self.setMinimumSize(465, 570)
        self.setObjectName("carFinanceCalculator")
        self._standalone = bool(standalone)
        self._settings = QSettings("MiniDailyLog", "FinanceCalculator")
        self.setStyleSheet(
            "QDialog,QWidget {background:#111827;color:#F9FAFB;}"
            "QLabel {color:#F9FAFB;}"
            "QLineEdit,QDoubleSpinBox,QSpinBox {background:#1F2937;color:#FFFFFF;"
            "border:1px solid #475569;border-radius:5px;padding:6px;}"
            "QTextEdit {background:#18212E;color:#FFFFFF;"
            "border:1px solid #475569;border-radius:5px;padding:5px;}"
            "QPushButton {background:#334155;color:white;border:1px solid #64748B;"
            "padding:5px 8px;border-radius:5px;}"
            "QPushButton:hover {background:#475569;}"
            "QPushButton:checked {background:#1D4ED8;border-color:#60A5FA;}"
            "QTabWidget::pane {border:1px solid #475569;}"
            "QTabBar::tab {background:#334155;color:white;padding:7px 9px;}"
            "QTabBar::tab:selected {background:#1D4ED8;}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(7)

        tools = QHBoxLayout()
        self.app_title = QLabel("🚗 เงินดาวน์ • ดอกเบี้ย Flat Rate • ค่าคอมมิชชั่น")
        tools.addWidget(self.app_title, 1)
        self.menu_button = QPushButton("☰")
        self.menu_button.setObjectName("calculatorOptionsMenu")
        self.menu_button.setFixedWidth(42)
        tools.addWidget(self.menu_button)
        root.addLayout(tools)
        self.menu = QMenu(self)
        self.on_top_action = self.menu.addAction("อยู่ด้านบนสุด (Always on Top)")
        self.on_top_action.setCheckable(True)
        self.on_top_action.setChecked(True)
        self.on_top_action.triggered.connect(self._update_on_top)
        self.startup_action = self.menu.addAction("เปิดอัตโนมัติเมื่อเข้า Windows")
        self.startup_action.setCheckable(True)
        self.startup_action.setEnabled(self._standalone and getattr(sys, "frozen", False))
        self.startup_action.setChecked(self._startup_enabled())
        self.startup_action.triggered.connect(self._update_startup)
        self.menu_button.setMenu(self.menu)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        finance_tab = QWidget()
        form_root = QVBoxLayout(finance_tab)
        form_root.setSpacing(6)
        form = QFormLayout()
        form.setSpacing(7)
        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("ไม่บังคับ")
        self.accessories_input = QLineEdit()
        self.accessories_input.setPlaceholderText("ไม่บังคับ")
        form.addRow("ชื่อรุ่นรถ:", self.model_input)
        form.addRow("พร้อมอุปกรณ์:", self.accessories_input)
        self.price_input = QDoubleSpinBox()
        self.price_input.setObjectName("financeCarPrice")
        self.price_input.setRange(0, 100_000_000)
        self.price_input.setDecimals(2)
        self.price_input.setGroupSeparatorShown(True)
        self.price_input.setSuffix(" บาท")
        self.price_input.setSingleStep(10000)
        form.addRow("ราคาเต็มรถ:", self.price_input)
        form_root.addLayout(form)

        form_root.addWidget(QLabel("เลือกเงินดาวน์ (%)"))
        down_grid = QVBoxLayout()
        self.down_buttons = QButtonGroup(self)
        self.down_buttons.setExclusive(True)
        self.selected_down = 20
        for start in range(0, len(DOWN_OPTIONS), 5):
            row = QHBoxLayout()
            for percent in DOWN_OPTIONS[start:start + 5]:
                button = QPushButton(f"{percent}%")
                button.setCheckable(True)
                button.setObjectName(f"down{percent}Percent")
                button.setProperty("downPercent", percent)
                button.clicked.connect(
                    lambda checked=False, p=percent: self._choose_down(p)
                )
                self.down_buttons.addButton(button, percent)
                if percent == self.selected_down:
                    button.setChecked(True)
                row.addWidget(button)
            down_grid.addLayout(row)
        form_root.addLayout(down_grid)

        extra = QFormLayout()
        self.years_input = QSpinBox()
        self.years_input.setObjectName("financeYears")
        self.years_input.setRange(1, 15)
        self.years_input.setValue(4)
        self.years_input.setSuffix(" ปี")
        self.interest_input = QDoubleSpinBox()
        self.interest_input.setObjectName("financeAnnualFlatRate")
        self.interest_input.setRange(0, 100)
        self.interest_input.setDecimals(3)
        self.interest_input.setSingleStep(0.1)
        self.interest_input.setSuffix("% ต่อปี")
        self.commission_input = QDoubleSpinBox()
        self.commission_input.setObjectName("financeCommissionRate")
        self.commission_input.setRange(0, 100)
        self.commission_input.setDecimals(3)
        self.commission_input.setSingleStep(0.1)
        self.commission_input.setSuffix("%")
        extra.addRow("ระยะเวลาผ่อน:", self.years_input)
        extra.addRow("ดอกเบี้ย Flat Rate:", self.interest_input)
        extra.addRow("ค่าคอมมิชชั่น:", self.commission_input)
        form_root.addLayout(extra)

        self.result_text = QTextEdit()
        self.result_text.setObjectName("financeQuoteSummary")
        self.result_text.setReadOnly(True)
        self.result_text.setPlaceholderText("กรอกราคา เลือกดาวน์ แล้วกดคำนวณ")
        form_root.addWidget(self.result_text, 1)

        button_row = QHBoxLayout()
        self.calculate_button = QPushButton("คำนวณใหม่")
        self.clear_button = QPushButton("ล้างข้อมูล")
        self.copy_button = QPushButton("คัดลอกทั้งหมด")
        button_row.addWidget(self.clear_button)
        button_row.addWidget(self.calculate_button)
        button_row.addWidget(self.copy_button)
        form_root.addLayout(button_row)

        self.calculate_button.clicked.connect(self.calculate)
        self.clear_button.clicked.connect(self.clear_inputs)
        self.copy_button.clicked.connect(self.copy_all)
        self.tabs.addTab(finance_tab, "1. คำนวณเงินดาวน์")
        self.calculate_button.setDefault(True)

    def _choose_down(self, percent):
        self.selected_down = int(percent)

    def calculate(self):
        try:
            result = finance_quote(
                self.price_input.value(), self.selected_down,
                self.years_input.value(), self.interest_input.value(),
                self.commission_input.value(),
            )
        except ValueError as error:
            QMessageBox.warning(self, "ตรวจสอบข้อมูล", str(error))
            return
        self.result_text.setPlainText(
            quote_text(result, self.model_input.text(), self.accessories_input.text())
        )

    def clear_inputs(self):
        self.model_input.clear()
        self.accessories_input.clear()
        self.price_input.setValue(0)
        self.years_input.setValue(4)
        self.interest_input.setValue(0)
        self.commission_input.setValue(0)
        self.selected_down = 20
        self.down_buttons.button(20).setChecked(True)
        self.result_text.clear()

    def copy_all(self):
        # Only copy a valid quote; never accidentally copy old calculations.
        if not self.result_text.toPlainText().strip():
            self.calculate()
        if self.result_text.toPlainText().strip():
            QApplication.clipboard().setText(self.result_text.toPlainText())

    def _update_on_top(self, checked):
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(checked))
        if was_visible:
            self.show()

    def _startup_enabled(self):
        if not getattr(sys, "frozen", False) or not self._standalone:
            return False
        run = QSettings(
            r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run",
            QSettings.Format.NativeFormat,
        )
        return bool(run.value("DailyLogFinanceCalculator", ""))

    def _update_startup(self, checked):
        try:
            actual = set_start_with_windows(bool(checked))
            self.startup_action.setChecked(actual)
        except (OSError, ValueError) as error:
            self.startup_action.setChecked(self._startup_enabled())
            QMessageBox.warning(self, "Start with Windows", str(error))
