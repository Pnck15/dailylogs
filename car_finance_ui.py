"""Compact finance calculator shared by DailyLog and standalone Windows EXE."""
import html
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QLocale, QRegularExpression, QSettings, QTimer, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDoubleSpinBox, QHBoxLayout, QLabel,
    QLineEdit, QMenu, QMessageBox, QPushButton, QScrollArea, QSpinBox, QTabWidget,
    QTextEdit, QVBoxLayout, QWidget,
)

from car_finance_math import (
    DOWN_OPTIONS, RECEIPT_ITEMS, RECEIPT_PRICE_TYPES, RECEIPT_TRADE_IN,
    finance_quote, quote_text, vehicle_receipt_quote, vehicle_receipt_text,
)
from workers import run_async

CAR_CALCULATOR_VERSION = "1.7.0"
DEVELOPER = "by 王纯真"


def set_start_with_windows(enabled, executable=None):
    """Use HKCU Run (no admin permission); standalone EXE only."""
    if executable is None:
        executable = sys.executable if getattr(sys, "frozen", False) else ""
    if not executable or not Path(executable).is_file():
        raise ValueError("ใช้ FinanceCalculator.exe ที่ Build แล้วสำหรับเปิดพร้อม Windows / 请使用已打包的FinanceCalculator.exe设置开机启动")
    key = QSettings(
        r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run",
        QSettings.Format.NativeFormat,
    )
    if enabled:
        key.setValue("DailyLogFinanceCalculator", f'"{executable}"')
    else:
        key.remove("DailyLogFinanceCalculator")
    key.sync()
    if key.status() != QSettings.Status.NoError:
        raise OSError("ไม่สามารถบันทึก Windows Startup Registry ได้ / 无法保存开机启动设置")
    return bool(key.value("DailyLogFinanceCalculator", ""))


class CarFinanceCalculator(QDialog):
    def __init__(self, parent=None, standalone=False):
        super().__init__(parent)
        self._standalone = bool(standalone)
        self._settings = QSettings("MiniDailyLog", "FinanceCalculator")
        self._checking_update = False
        self._last_update_attempt = 0.0
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setWindowTitle("Car - Finance Calculator 购车分期付款计算器")
        self.setModal(False)
        # The native window border remains freely resizable vertically.
        self.resize(510, 535)
        self.setMinimumSize(455, 390)
        self.setWindowOpacity(0.93)
        self.setObjectName("carFinanceCalculator")
        self.setStyleSheet(
            "QDialog, QWidget { background:#1A202B; color:#F9FAFB; }"
            "QLabel {color:#E5E7EB; font-size:11px;}"
            "QLineEdit,QDoubleSpinBox,QSpinBox,QComboBox {background:#283342;"
            "color:#FFFFFF; border:1px solid #475569; border-radius:4px;"
            "padding:4px 5px; min-height:21px;}"
            "QComboBox QAbstractItemView {background:#283342;color:white;"
            "selection-background-color:#991B1B;}"
            "QTextEdit {background:#18212E;color:#FFFFFF;"
            "border:1px solid #475569;border-radius:5px;padding:3px;}"
            "QPushButton {background:#344255;color:#FFFFFF;"
            "border:1px solid #475569;border-radius:5px;padding:5px 7px;}"
            "QPushButton:hover {background:#46566B;}"
            "QPushButton#financeCalculateButton {background:#DC2626;"
            "border:1px solid #EF4444;font-weight:700;}"
            "QPushButton#financeCalculateButton:hover {background:#B91C1C;}"
            "QTabWidget::pane {border:1px solid #7F1D1D;}"
            "QTabBar::tab {background:#7F1D1D;color:#FFFFFF;"
            "padding:6px 11px;border:1px solid #991B1B;}"
            "QTabBar::tab:selected {background:#DC2626;color:#FFFFFF;"
            "font-weight:700;border:1px solid #EF4444;}"
            "QMenu {background:#202A37;color:#FFFFFF;}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)
        head = QHBoxLayout()
        head.addWidget(QLabel("🚗 เงินดาวน์ / 首付款 · ดอกเบี้ย / 利息 · คอมมิชชั่น / 佣金"), 1)
        self.menu_button = QPushButton("☰")
        self.menu_button.setObjectName("calculatorOptionsMenu")
        self.menu_button.setFixedWidth(34)
        head.addWidget(self.menu_button)
        root.addLayout(head)

        self.menu = QMenu(self)
        self.on_top_action = self.menu.addAction("อยู่ด้านบนสุด / 窗口置顶 (Always on Top)")
        self.on_top_action.setCheckable(True)
        self.on_top_action.setChecked(True)
        self.on_top_action.triggered.connect(self._update_on_top)
        self.startup_action = self.menu.addAction("เปิดอัตโนมัติเมื่อเข้า Windows / 开机自动启动")
        self.startup_action.setCheckable(True)
        self.startup_action.setEnabled(
            self._standalone and bool(getattr(sys, "frozen", False))
        )
        self.startup_action.setChecked(self._startup_enabled())
        self.startup_action.triggered.connect(self._update_startup)
        self.auto_update_action = self.menu.addAction("อัปเดตอัตโนมัติ / 自动更新")
        self.auto_update_action.setCheckable(True)
        self.auto_update_action.setChecked(
            self._settings.value("updates/auto_enabled", True, type=bool)
        )
        self.auto_update_action.setEnabled(self._can_self_update())
        self.auto_update_action.triggered.connect(self._toggle_auto_update)
        self.manual_update_action = self.menu.addAction("ตรวจสอบอัปเดต / 检查更新")
        self.manual_update_action.setEnabled(self._can_self_update())
        self.manual_update_action.triggered.connect(
            lambda: self.check_for_updates(manual=True)
        )
        self.menu.addSeparator()
        self.menu.addAction(f"Finance Calculator v{CAR_CALCULATOR_VERSION} · {DEVELOPER}")
        self.menu_button.setMenu(self.menu)

        self.tabs = QTabWidget(self)
        root.addWidget(self.tabs, 1)
        first = QWidget()
        frame = QVBoxLayout(first)
        frame.setContentsMargins(7, 8, 7, 5)
        frame.setSpacing(6)

        # All four fields align in precisely two compact columns.
        self.model_input = QLineEdit()
        self.model_input.setObjectName("financeModel")
        self.model_input.setPlaceholderText("รุ่นรถ (ไม่บังคับ) / 车型（选填）")
        self.accessories_input = QLineEdit()
        self.accessories_input.setObjectName("financeAccessories")
        self.accessories_input.setPlaceholderText("อุปกรณ์ (ไม่บังคับ) / 配件（选填）")
        frame.addLayout(self._field_row([
            ("รุ่นรถ / 车型", self.model_input, 1),
            ("พร้อมอุปกรณ์ / 随车配件", self.accessories_input, 1),
        ]))

        self.price_input = QLineEdit()
        self.price_input.setObjectName("financeCarPrice")
        self.price_input.setPlaceholderText("เช่น 315000 / 例如 315000")
        # ASCII 0–9 and optional decimal separator only. No Thai numerals.
        self.price_input.setValidator(
            QRegularExpressionValidator(
                QRegularExpression(r"^[0-9]{0,9}(?:\.[0-9]{0,2})?$"),
                self.price_input,
            )
        )
        self.down_combo = QComboBox()
        self.down_combo.setObjectName("financeDownPercent")
        for percent in DOWN_OPTIONS:
            self.down_combo.addItem(f"{percent}%", percent)
        self.down_combo.addItem(
            "กำหนดเอง (บาท) / 自定义金额（泰铢）", "manual"
        )
        self.down_combo.setCurrentIndex(self.down_combo.findData(20))
        frame.addLayout(self._field_row([
            ("ราคาเต็มรถ / 车价 (บาท)", self.price_input, 2),
            ("เลือกเงินดาวน์ / 选择首付方式", self.down_combo, 1),
        ]))

        # Manual down payment is shown only for the "กำหนดเอง" selection.
        # It is ignored whenever a percentage is selected.
        self.manual_down_panel = QWidget()
        self.manual_down_panel.setObjectName("financeManualDownPanel")
        manual_row = QHBoxLayout(self.manual_down_panel)
        manual_row.setContentsMargins(0, 0, 0, 0)
        manual_row.setSpacing(6)
        manual_row.addWidget(QLabel("เงินดาวน์เอง (บาท) / 自定义首付款（泰铢）"))
        self.manual_down_input = self._money_input(
            "financeManualDownAmount", "เช่น 60000 / 例如 60000"
        )
        manual_row.addWidget(self.manual_down_input, 1)
        frame.addWidget(self.manual_down_panel)
        self.down_combo.currentIndexChanged.connect(
            self._on_down_mode_changed
        )
        self._on_down_mode_changed()

        # Added to the cash down total, excluded from financing and interest.
        self.loan_insurance_input = self._money_input(
            "financeLoanInsurancePremium", "เช่น 16952 / 例如 16952"
        )
        frame.addLayout(self._field_row([
            ("เงินประกันคุ้มครองสินเชื่อ / 贷款保障保险费 (บาท)",
             self.loan_insurance_input, 1),
        ]))

        self.years_input = QSpinBox()
        self.years_input.setObjectName("financeYears")
        self.years_input.setLocale(QLocale.c())
        self.years_input.setRange(1, 15)
        self.years_input.setValue(4)
        self.interest_input = QDoubleSpinBox()
        self.interest_input.setObjectName("financeAnnualFlatRate")
        self.interest_input.setLocale(QLocale.c())
        self.interest_input.setRange(0, 100)
        self.interest_input.setDecimals(3)
        self.interest_input.setSingleStep(0.1)
        self.commission_input = QDoubleSpinBox()
        self.commission_input.setObjectName("financeCommissionRate")
        self.commission_input.setLocale(QLocale.c())
        self.commission_input.setRange(0, 100)
        self.commission_input.setDecimals(3)
        self.commission_input.setSingleStep(0.1)
        frame.addLayout(self._field_row([
            ("ผ่อน / 年限 (ปี)", self.years_input, 1),
            ("ดอกเบี้ย/ปี / 年息 (%)", self.interest_input, 1),
            ("คอมมิชชั่น / 佣金 (%)", self.commission_input, 1),
        ]))

        self.result_text = QTextEdit()
        self.result_text.setObjectName("financeQuoteSummary")
        self.result_text.setReadOnly(True)
        self.result_text.setPlaceholderText("กรอกราคาแล้วกดคำนวณ / 请输入车价并点击计算")
        frame.addWidget(self.result_text, 1)

        buttons = QHBoxLayout()
        self.clear_button = QPushButton("ล้างข้อมูล / 清空")
        self.calculate_button = QPushButton("คำนวน / 计算")
        self.calculate_button.setObjectName("financeCalculateButton")
        self.calculate_button.setDefault(True)
        self.copy_button = QPushButton("คัดลอกทั้งหมด / 复制全部")
        buttons.addWidget(self.clear_button)
        buttons.addWidget(self.calculate_button)
        buttons.addWidget(self.copy_button)
        frame.addLayout(buttons)
        self.clear_button.clicked.connect(self.clear_inputs)
        self.calculate_button.clicked.connect(self.calculate)
        self.copy_button.clicked.connect(self.copy_all)
        self.tabs.addTab(first, "1. คำนวณเงินดาวน์ / 首付款计算")
        self._build_receipt_tab()
        if self._can_self_update():
            self.update_timer = QTimer(self)
            self.update_timer.setInterval(15 * 60 * 1000)
            self.update_timer.timeout.connect(self._auto_update_tick)
            self.update_timer.start()
            QTimer.singleShot(8000, self._auto_update_tick)

    @staticmethod
    def _field_row(fields):
        row = QHBoxLayout()
        row.setSpacing(6)
        for title, widget, ratio in fields:
            column = QVBoxLayout()
            column.setSpacing(2)
            label = QLabel(title)
            label.setWordWrap(True)
            column.addWidget(label)
            column.addWidget(widget)
            row.addLayout(column, ratio)
        return row

    def _on_down_mode_changed(self, _index=None):
        is_manual = self.down_combo.currentData() == "manual"
        self.manual_down_panel.setVisible(is_manual)
        if is_manual:
            self.manual_down_input.setFocus()

    @property
    def selected_down(self):
        choice = self.down_combo.currentData()
        return None if choice == "manual" else int(choice)

    def calculate(self):
        try:
            result = finance_quote(
                self.price_input.text(), self.selected_down,
                self.years_input.value(), self.interest_input.value(),
                self.commission_input.value(),
                down_amount=(
                    self.manual_down_input.text()
                    if self.selected_down is None else None
                ),
                loan_insurance_premium=(self.loan_insurance_input.text() or "0"),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "ตรวจสอบข้อมูล / 检查输入", str(exc))
            return
        self._show_calculation(
            self.result_text,
            quote_text(result, self.model_input.text(),
                       self.accessories_input.text())
        )


    @staticmethod
    def _money_input(object_name, placeholder="0.00"):
        """Numeric ASCII money input with optional two decimal places."""
        field = QLineEdit()
        field.setObjectName(object_name)
        field.setPlaceholderText(placeholder)
        field.setValidator(
            QRegularExpressionValidator(
                QRegularExpression(r"^[0-9]{0,9}(?:\.[0-9]{0,2})?$"),
                field,
            )
        )
        return field

    @staticmethod
    def _show_calculation(widget, plain):
        """Yellow numeric values, bold financed principal and monthly payment."""
        segments = []
        bold_keys = (
            "ยอดจัดไฟแนนซ์",
            "ยอดรวมเงินดาวน์",
            "ค่างวดต่อเดือนสุทธิ",
            "เงินดาวน์สุทธิที่ต้องชำระ",
            "ยอดสุทธิที่ต้องชำระ",
        )
        for line in plain.splitlines():
            safe = html.escape(line).replace(":   ", ":&nbsp;&nbsp;&nbsp;")
            safe = re.sub(
                r"(?<![0-9])[0-9][0-9,.]*%?",
                lambda match: '<span style="color:#FDE047;">'
                              + match.group(0) + "</span>",
                safe,
            )
            if line.startswith(bold_keys):
                safe = "<b>" + safe + "</b>"
            segments.append(
                '<div style="margin:0;padding:0;line-height:1.25;">'
                + safe + "</div>"
            )
        widget.setHtml(
            "<html><body style='color:#FFFFFF; font-family:Segoe UI;"
            "font-size:9pt;'>" + "".join(segments) + "</body></html>"
        )

    def _build_receipt_tab(self):
        """Cash-receipt tab; independent of instalment/interest calculations."""
        receipt = QWidget()
        receipt.setObjectName("financeReceiptTab")
        outer = QVBoxLayout(receipt)
        outer.setContentsMargins(6, 6, 6, 4)
        outer.setSpacing(4)

        # Make long bilingual labels readable, even if the window is
        # resized vertically. The calculation output always stays visible.
        scroll = QScrollArea()
        scroll.setObjectName("receiptFieldsScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setMinimumHeight(190)
        fields_widget = QWidget()
        form = QVBoxLayout(fields_widget)
        form.setContentsMargins(2, 2, 6, 2)
        form.setSpacing(7)

        self.receipt_model_input = QLineEdit()
        self.receipt_model_input.setObjectName("receiptCarModel")
        self.receipt_model_input.setPlaceholderText("รุ่นรถ / 车型（选填）")
        self.receipt_accessories_input = QLineEdit()
        self.receipt_accessories_input.setObjectName("receiptAccessories")
        self.receipt_accessories_input.setPlaceholderText("อุปกรณ์ / 配件（选填）")
        form.addLayout(self._field_row([
            ("รุ่นรถ / 车型", self.receipt_model_input, 1),
            ("พร้อมอุปกรณ์ / 随车配件", self.receipt_accessories_input, 1),
        ]))

        self.receipt_price_type = QComboBox()
        self.receipt_price_type.setObjectName("receiptPriceType")
        for label, value in RECEIPT_PRICE_TYPES:
            self.receipt_price_type.addItem(label, value)
        self.receipt_price_input = self._money_input(
            "receiptCarPrice", "เช่น 315000 / 例如 315000"
        )
        self.receipt_trade_in = QComboBox()
        self.receipt_trade_in.setObjectName("receiptTradeIn")
        for company in RECEIPT_TRADE_IN:
            self.receipt_trade_in.addItem(company, "" if company.startswith("ไม่ระบุ") else company)
        form.addLayout(self._field_row([
            ("ประเภทราคา / 金额类型", self.receipt_price_type, 1),
            ("จำนวนเงิน (บาท) / 金额（泰铢）", self.receipt_price_input, 1),
            ("Trade-in? / 置换服务商", self.receipt_trade_in, 1),
        ]))

        # Several charge/discount fields per row, without any annual
        # interest, down-percent dropdown, or instalment years.
        self.receipt_fields = {}
        for index in range(0, len(RECEIPT_ITEMS), 3):
            row_fields = []
            for key, title, sign in RECEIPT_ITEMS[index:index + 3]:
                field = self._money_input(
                    "receipt_" + key,
                    "0.00",
                )
                self.receipt_fields[key] = field
                row_fields.append((title, field, 1))
            form.addLayout(self._field_row(row_fields))
        form.addStretch(1)
        scroll.setWidget(fields_widget)
        outer.addWidget(scroll, 3)

        note = QLabel(
            "ค่าภาษี = ฐานภาษี × 7% / 税额 = 税基 × 7%   ·   "
            "Trade-in เลือกบริษัทเท่านั้น / 仅记录置换服务商"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#CBD5E1; font-size:10px;")
        outer.addWidget(note)

        self.receipt_result_text = QTextEdit()
        self.receipt_result_text.setObjectName("receiptQuoteSummary")
        self.receipt_result_text.setReadOnly(True)
        self.receipt_result_text.setMinimumHeight(78)
        self.receipt_result_text.setPlaceholderText(
            "คำนวณยอดรับชำระ / 计算应付金额"
        )
        outer.addWidget(self.receipt_result_text, 2)

        buttons = QHBoxLayout()
        self.receipt_clear_button = QPushButton("ล้างข้อมูล / 清空")
        self.receipt_calculate_button = QPushButton("คำนวน / 计算")
        self.receipt_calculate_button.setObjectName("financeCalculateButton")
        self.receipt_copy_button = QPushButton("คัดลอกทั้งหมด / 复制全部")
        buttons.addWidget(self.receipt_clear_button)
        buttons.addWidget(self.receipt_calculate_button)
        buttons.addWidget(self.receipt_copy_button)
        outer.addLayout(buttons)
        self.receipt_clear_button.clicked.connect(self.clear_receipt_inputs)
        self.receipt_calculate_button.clicked.connect(self.calculate_receipt)
        self.receipt_copy_button.clicked.connect(self.copy_receipt)
        self.tabs.addTab(receipt, "2. ใบเสร็จรับเงินค่ารถ / 购车款收据")

    def calculate_receipt(self):
        try:
            result = vehicle_receipt_quote(
                self.receipt_price_input.text(),
                price_type=self.receipt_price_type.currentData(),
                trade_in=self.receipt_trade_in.currentData(),
                **{key: field.text() or "0"
                   for key, field in self.receipt_fields.items()},
            )
        except ValueError as exc:
            self.receipt_result_text.clear()
            QMessageBox.warning(self, "ตรวจสอบข้อมูล / 检查输入", str(exc))
            return
        self._show_calculation(
            self.receipt_result_text,
            vehicle_receipt_text(
                result, self.receipt_model_input.text(),
                self.receipt_accessories_input.text(),
            ),
        )

    def clear_receipt_inputs(self):
        self.receipt_model_input.clear()
        self.receipt_accessories_input.clear()
        self.receipt_price_type.setCurrentIndex(0)
        self.receipt_price_input.clear()
        self.receipt_trade_in.setCurrentIndex(0)
        for field in self.receipt_fields.values():
            field.clear()
        self.receipt_result_text.clear()

    def copy_receipt(self):
        if not self.receipt_result_text.toPlainText().strip():
            self.calculate_receipt()
        if self.receipt_result_text.toPlainText().strip():
            QApplication.clipboard().setText(
                self.receipt_result_text.toPlainText()
            )

    def clear_inputs(self):
        self.model_input.clear()
        self.accessories_input.clear()
        self.price_input.clear()
        self.down_combo.setCurrentIndex(self.down_combo.findData(20))
        self.manual_down_input.clear()
        self.loan_insurance_input.clear()
        self.years_input.setValue(4)
        self.interest_input.setValue(0)
        self.commission_input.setValue(0)
        self.result_text.clear()

    def copy_all(self):
        if not self.result_text.toPlainText().strip():
            self.calculate()
        if self.result_text.toPlainText().strip():
            QApplication.clipboard().setText(self.result_text.toPlainText())

    def _update_on_top(self, checked):
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(checked))
        if visible:
            self.show()

    def _startup_enabled(self):
        if not self._can_self_update():
            return False
        registry = QSettings(
            r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run",
            QSettings.Format.NativeFormat,
        )
        return bool(registry.value("DailyLogFinanceCalculator", ""))

    def _update_startup(self, checked):
        try:
            self.startup_action.setChecked(set_start_with_windows(checked))
        except (ValueError, OSError) as exc:
            self.startup_action.setChecked(self._startup_enabled())
            QMessageBox.warning(self, "Start with Windows", str(exc))

    def _can_self_update(self):
        return bool(
            self._standalone and getattr(sys, "frozen", False)
            and Path(sys.executable).name.lower() == "financecalculator.exe"
        )

    def _toggle_auto_update(self, checked):
        self._settings.setValue("updates/auto_enabled", bool(checked))
        self._settings.sync()

    def _auto_update_tick(self):
        if self.auto_update_action.isChecked():
            self.check_for_updates()

    def check_for_updates(self, manual=False):
        """Check and stage updates in the background, then relaunch with updater."""
        if not self._can_self_update():
            if manual:
                QMessageBox.information(
                    self, "Car - Finance Calculator 购车分期付款计算器", "โปรแกรมรุ่นใน DailyLog.exe / DailyLog内置版 "
                    "จะอัปเดตพร้อมโปรแกรมหลัก / 将随主程序一起更新"
                )
            return
        if self._checking_update:
            return
        if not manual and time.time()-self._last_update_attempt < 15*60:
            return
        self._checking_update = True
        self._last_update_attempt = time.time()
        from car_finance_updates import fetch_finance_update, prepare_finance_update

        def lookup():
            result = fetch_finance_update(CAR_CALCULATOR_VERSION)
            if result.get("available"):
                result = prepare_finance_update(result, Path(sys.executable).parent)
            return result

        def success(result):
            self._checking_update = False
            if not result.get("available"):
                if manual:
                    QMessageBox.information(
                        self, "Car - Finance Calculator 购车分期付款计算器", "เป็นเวอร์ชันล่าสุดแล้ว / 已是最新版本 "
                        f"v{CAR_CALCULATOR_VERSION}\n{DEVELOPER}"
                    )
                return
            updater = Path(sys.executable).parent / "DailyLogUpdater.exe"
            cmd = [
                str(updater), str(os.getpid()), sys.executable,
                result["prepared_file"], result["finance_sha256"],
            ]
            try:
                subprocess.Popen(cmd, close_fds=True)
                QApplication.quit()
            except (OSError, ValueError) as exc:
                QMessageBox.warning(
                    self, "Finance Calculator Update",
                    f"เริ่มอัปเดตไม่ได้ / 无法启动更新: {exc}"
                )

        def failure(error):
            self._checking_update = False
            if manual:
                QMessageBox.warning(
                    self, "Finance Calculator Update",
                    "ตรวจสอบอัปเดต / 检查更新ไม่สำเร็จ / 检查更新失败: " + str(error)[:240]
                )

        run_async(self, lookup, success, failure)
