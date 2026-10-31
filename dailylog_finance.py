"""Thai invoice breakdown: VAT included 7%, withholding 3% of VAT-exclusive base."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QVBoxLayout, QWidget, QTabWidget,
)

VAT_RATE = Decimal("0.07")
WHT_RATE = Decimal("0.03")
SATANG = Decimal("0.01")


def amount(value):
    value = str(value or "0").strip().replace(",", "")
    if not value:
        value = "0"
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError("กรุณาระบุยอดเงินเป็นตัวเลขที่ถูกต้อง / 请输入有效金额") from error
    if not result.is_finite() or result < 0:
        raise ValueError("ยอดเงินต้องเป็นตัวเลขที่ไม่ติดลบ / 金额不得为负数")
    return result.quantize(SATANG, rounding=ROUND_HALF_UP)


def invoice_withholding_3_percent(gross_including_vat, already_paid=0):
    """Calculate money due when an invoice TOTAL ALREADY INCLUDES VAT 7%.

    Base before VAT = gross/1.07, rounded to satang.
    VAT = gross - base, to reconcile exactly to the billed total.
    WHT 3% = base*0.03, rounded to satang.
    Remaining = gross - WHT - amount already paid (can be negative).
    """
    gross = amount(gross_including_vat)
    paid = amount(already_paid)
    base = (gross / (Decimal("1") + VAT_RATE)).quantize(
        SATANG, rounding=ROUND_HALF_UP
    )
    vat = gross - base
    withheld = (base * WHT_RATE).quantize(
        SATANG, rounding=ROUND_HALF_UP
    )
    after_wht = gross - withheld
    due = after_wht - paid
    return {
        "gross": gross,
        "tax_base": base,
        "vat": vat,
        "withheld": withheld,
        "net": after_wht,
        "paid": paid,
        "balance": due,
        "remaining": max(due, Decimal("0.00")),
        "overpaid": max(-due, Decimal("0.00")),
    }


def settlement_3_percent(tax_base, invoice_amount=None, already_paid=0):
    """Backward-compatible helper for callers supplying tax base separately."""
    base = amount(tax_base)
    gross = base if invoice_amount is None or str(invoice_amount).strip() == "" else amount(invoice_amount)
    paid = amount(already_paid)
    withheld = (base * WHT_RATE).quantize(SATANG, rounding=ROUND_HALF_UP)
    balance = gross - withheld - paid
    return {
        "tax_base": base, "invoice": gross, "withheld": withheld,
        "net": gross - withheld, "paid": paid,
        "balance": balance,
        "remaining": max(balance, Decimal("0.00")),
        "overpaid": max(-balance, Decimal("0.00")),
    }


def baht(value):
    return f"{value:,.2f} บาท（泰铢）"


def base_plus_vat_withholding_3_percent(base_before_vat, already_paid=0):
    """Forward calculation: add VAT 7% to the base, then withhold 3% of base.

    VAT and WHT are separately rounded to satang (half up). Both use the
    BEFORE-VAT base; WHT must never be calculated from the VAT-inclusive total.
    """
    base = amount(base_before_vat)
    paid = amount(already_paid)
    vat = (base * VAT_RATE).quantize(SATANG, rounding=ROUND_HALF_UP)
    gross = base + vat
    withheld = (base * WHT_RATE).quantize(SATANG, rounding=ROUND_HALF_UP)
    net = gross - withheld
    balance = net - paid
    return {
        "gross": gross,
        "tax_base": base,
        "vat": vat,
        "withheld": withheld,
        "net": net,
        "paid": paid,
        "balance": balance,
        "remaining": max(balance, Decimal("0.00")),
        "overpaid": max(-balance, Decimal("0.00")),
    }



def three_percent_adjustments(value):
    """Separate +3%, removing an included 3%, and WHT gross-up.

    Adding 3%: input * 1.03.
    WHT deduction of 3% from entered: input - (input * 0.03).
    Extracting an INCREASE of 3%: input / 1.03 (distinct).
    Recovering gross prior to 3% withholding: input / 0.97.
    All amounts use Decimal and ROUND_HALF_UP.
    """
    entered = amount(value)
    added = (entered * WHT_RATE).quantize(SATANG, rounding=ROUND_HALF_UP)
    included_base = (entered / (Decimal("1") + WHT_RATE)).quantize(
        SATANG, rounding=ROUND_HALF_UP
    )
    gross_up = (entered / (Decimal("1") - WHT_RATE)).quantize(
        SATANG, rounding=ROUND_HALF_UP
    )
    # Deduct exactly 3% FROM THE ENTERED AMOUNT (the requested 30,927.84
    # -> 30,000.00 example). This is different from extracting an included
    # markup (÷1.03), which we retain as a separately labelled calculation.
    deducted_3_percent = added
    deducted_total = entered - deducted_3_percent
    return {
        "entered": entered,
        "added_tax": added,
        "plus_total": entered + added,
        "deducted_3_percent": deducted_3_percent,
        "deducted_total": deducted_total,
        "included_base": included_base,
        "included_tax": entered - included_base,
        "gross_up": gross_up,
        "gross_up_withheld": gross_up - entered,
    }


class WithholdingCalculator(QDialog):
    """Three-tab invoice calculator, independent from DailyLog's other windows.

    Tab 1: The customer's invoice total already includes 7% VAT. Extract the
    pre-VAT base (divide by 1.07) and withhold 3% of that base.

    Tab 2: Start with the pre-VAT base. Add 7% VAT (rounded to satang) and
    then withhold 3% of the SAME pre-VAT base.

    Tab 3: +3%, extracting included 3%, and grossing up a net amount.\n\n    No tab makes a cloud request or touches saved Daily Logs.
    """
    LABELS = (
        ("gross", "ยอดรวมบิล (รวม VAT 7%) / 账单总额（含7%增值税）"),
        ("tax_base", "ฐานก่อน VAT 7% / 未税金额（不含7%增值税）"),
        ("vat", "ภาษีมูลค่าเพิ่ม 7% / 增值税7%"),
        ("withheld", "หัก ณ ที่จ่าย 3% / 预扣税3%"),
        ("net", "ยอดสุทธิหลังหัก 3% / 扣除3%预扣税后净额"),
        ("paid", "ลูกค้าชำระแล้ว / 客户已付款"),
        ("balance", "ส่วนต่างคงเหลือ / รับเกิน · 应付余额 / 多收款"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        # This dialog is a normal independent top-level window, not a modal
        # child that blocks mouse/keyboard input in DailyLog.exe.
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setModal(False)
        self.setWindowTitle("VAT Calculator 增值税计算器")
        self.resize(760, 510)
        self.setMinimumWidth(660)
        self.setStyleSheet(
            "QDialog { background: #111827; color: white; } "
            "QWidget#calculatorTab { background: #111827; } "
            "QLabel { color: #F9FAFB; } "
            "QLineEdit { background: #1F2937; color: white; "
            "border: 1px solid #64748B; border-radius: 5px; padding: 5px; } "
            "QTextEdit { background: #18212E; color: white; "
            "border: 1px solid #475569; border-radius: 6px; } "
            "QPushButton { background: #B91C1C; color: #FFFFFF; padding: 5px 8px; border: 1px solid #EF4444; border-radius: 5px; } "
            "QPushButton:hover { background: #DC2626; } "
            "QTabWidget::pane { border: 1px solid #475569; } "
            "QTabBar::tab { background: #334155; color: #FFFFFF; "
            "padding: 7px 9px; border: 1px solid #475569; } "
            "QTabBar::tab:selected { background: #DC2626; color: #FFFFFF; "
            "font-weight: 600; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 9, 10, 9)
        root.setSpacing(7)
        # Small in-memory ledgers for the checked amounts on tabs 1 and 2.
        self._saved_amounts = {}
        self._memory_controls = {}
        self._memory_tab_totals = {}
        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("withholdingModeTabs")
        root.addWidget(self.tabs)

        # ----- Partition 1: gross amount already includes VAT 7% -----
        existing = QWidget(self.tabs)
        existing.setObjectName("calculatorTab")
        existing_layout = QVBoxLayout(existing)
        existing_layout.setSpacing(7)
        note = QLabel(
            "ส่วนที่ 1 / 第1部分：กรอกยอดบิลที่รวม VAT 7% แล้ว / 输入含税账单总额\n"
            "ถอดฐานก่อน VAT แล้วหัก ณ ที่จ่าย 3% / 预扣税3% จากฐานนั้น / 从未税金额中扣除3%预扣税"
        )
        note.setWordWrap(True)
        existing_layout.addWidget(note)

        existing_form = QFormLayout()
        self.gross_input = QLineEdit()
        self.gross_input.setObjectName("grossIncludingVat")
        self.gross_input.setPlaceholderText("เช่น 5,000.00 / 例如 5,000.00")
        self.paid_input = QLineEdit()
        self.paid_input.setPlaceholderText("ลูกค้าจ่ายแล้ว / 已付款（留空为0）")
        existing_form.addRow("รวม VAT 7% / 含7%增值税:",
                             self._memory_row("gross", self.gross_input))
        existing_form.addRow("ชำระแล้ว / 已付款:",
                             self._memory_row("paid", self.paid_input))
        self.saved_tab1_total = self._memory_total_field("savedTab1Total")
        self._memory_tab_totals[1] = self.saved_tab1_total
        existing_form.addRow("รวมรายการที่ติ๊ก / 勾选金额累计:", self.saved_tab1_total)
        existing_layout.addLayout(existing_form)
        self.answer = self._make_result_area("invoiceSummary")
        existing_layout.addWidget(self.answer, 1)
        existing_buttons = QHBoxLayout()
        self.copy_button = QPushButton("คัดลอก / 复制")
        self.clear_button = QPushButton("ล้างค่า / 清空")
        close_existing = QPushButton("ปิด / 关闭")
        self.copy_button.clicked.connect(self.copy_result)
        self.clear_button.clicked.connect(self.clear)
        close_existing.clicked.connect(self.accept)
        existing_buttons.addWidget(self.clear_button)
        existing_buttons.addStretch()
        existing_buttons.addWidget(self.copy_button)
        existing_buttons.addWidget(close_existing)
        existing_layout.addLayout(existing_buttons)
        self.tabs.addTab(existing, "1. บิลรวม VAT / 含税账单")

        # ----- Partition 2: compute VAT 7% then withhold 3% -----
        forward = QWidget(self.tabs)
        forward.setObjectName("calculatorTab")
        forward_layout = QVBoxLayout(forward)
        forward_layout.setSpacing(7)
        forward_note = QLabel(
            "ส่วนที่ 2 / 第2部分：กรอกฐานก่อน VAT → เพิ่ม VAT 7% / 未税金额加计7%增值税\n"
            "จากนั้นหัก ณ ที่จ่าย 3% / 预扣税3% ของฐานก่อน VAT / 按未税金额扣除3%预扣税"
        )
        forward_note.setWordWrap(True)
        forward_layout.addWidget(forward_note)

        forward_form = QFormLayout()
        self.base_input = QLineEdit()
        self.base_input.setObjectName("baseBeforeVat")
        self.base_input.setPlaceholderText("เช่น 5,000.00 / 例如：未含增值税")
        self.forward_paid_input = QLineEdit()
        self.forward_paid_input.setPlaceholderText("ลูกค้าจ่ายแล้ว / 已付款（留空为0）")
        forward_form.addRow("ฐานก่อน VAT 7% / 未税金额（不含7%增值税）:",
                            self._memory_row("base", self.base_input))
        forward_form.addRow("ชำระแล้ว / 已付款:",
                            self._memory_row("forward_paid", self.forward_paid_input))
        self.saved_tab2_total = self._memory_total_field("savedTab2Total")
        self._memory_tab_totals[2] = self.saved_tab2_total
        forward_form.addRow("รวมรายการที่ติ๊ก / 勾选金额累计:", self.saved_tab2_total)
        forward_layout.addLayout(forward_form)
        self.forward_answer = self._make_result_area("forwardVatSummary")
        forward_layout.addWidget(self.forward_answer, 1)
        forward_buttons = QHBoxLayout()
        self.forward_copy_button = QPushButton("คัดลอก / 复制")
        self.forward_clear_button = QPushButton("ล้างค่า / 清空")
        close_forward = QPushButton("ปิด / 关闭")
        self.forward_copy_button.clicked.connect(self.copy_forward_result)
        self.forward_clear_button.clicked.connect(self.clear_forward)
        close_forward.clicked.connect(self.accept)
        forward_buttons.addWidget(self.forward_clear_button)
        forward_buttons.addStretch()
        forward_buttons.addWidget(self.forward_copy_button)
        forward_buttons.addWidget(close_forward)
        forward_layout.addLayout(forward_buttons)
        self.tabs.addTab(forward, "2. เพิ่ม VAT / หัก 3% · 加税扣税")

        # Tab 3 includes both meanings of "ถอด 3%" so users do not
        # confuse extracting included 3% (÷1.03) with net WHT (÷0.97).
        adjustment = QWidget(self.tabs)
        adjustment.setObjectName("calculatorTab")
        adjustment_layout = QVBoxLayout(adjustment)
        adjustment_layout.setSpacing(7)
        adjust_note = QLabel(
            "ส่วนที่ 3 / 第3部分：หัก 3% จากยอดที่กรอก / 从输入金额扣除3% (ตัวอย่าง 30,927.84 → 30,000.00) "
            "หรือบวก 3% และย้อนฐานราคาที่บวก 3% มาแล้ว / 加收3%或反推加收前金额（不含增值税）"
        )
        adjust_note.setWordWrap(True)
        adjustment_layout.addWidget(adjust_note)
        adjustment_form = QFormLayout()
        self.adjust_input = QLineEdit()
        self.adjust_input.setObjectName("threePercentAmount")
        self.adjust_input.setPlaceholderText("เช่น 1,000.00 / 例如 1,000.00")
        adjustment_form.addRow("ยอดเงิน / 金额:", self.adjust_input)
        adjustment_layout.addLayout(adjustment_form)
        self.adjust_answer = self._make_result_area("threePercentSummary")
        self.adjust_answer.setMinimumHeight(200)
        adjustment_layout.addWidget(self.adjust_answer, 1)
        adjustment_buttons = QHBoxLayout()
        self.adjust_copy_button = QPushButton("คัดลอก / 复制")
        self.adjust_clear_button = QPushButton("ล้างค่า / 清空")
        adjust_close = QPushButton("ปิด / 关闭")
        self.adjust_copy_button.clicked.connect(self.copy_adjust_result)
        self.adjust_clear_button.clicked.connect(self.clear_adjust)
        adjust_close.clicked.connect(self.accept)
        adjustment_buttons.addWidget(self.adjust_clear_button)
        adjustment_buttons.addStretch()
        adjustment_buttons.addWidget(self.adjust_copy_button)
        adjustment_buttons.addWidget(adjust_close)
        adjustment_layout.addLayout(adjustment_buttons)
        self.tabs.addTab(adjustment, "3. บวก / ถอด 3% · 加减3%")

        self._adjust_result = None
        self._adjust_plain_result = ""
        self._plain_result = ""
        self._result = None
        self._forward_plain_result = ""
        self._forward_result = None
        self.gross_input.textChanged.connect(self.recalculate)
        self.paid_input.textChanged.connect(self.recalculate)
        self.base_input.textChanged.connect(self.recalculate_forward)
        self.forward_paid_input.textChanged.connect(self.recalculate_forward)
        self.adjust_input.textChanged.connect(self.recalculate_adjust)
        self.recalculate()
        self.recalculate_forward()
        self.recalculate_adjust()

    @staticmethod
    def _memory_total_field(name):
        field = QLineEdit("0.00")
        field.setObjectName(name)
        field.setReadOnly(True)
        field.setToolTip("ยอดสะสมเฉพาะรายการที่ติ๊กไว้ / 已勾选金额累计")
        return field

    def _memory_row(self, key, field):
        """Keep a checked value in a separate running total, without changing VAT maths."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(field, 3)
        check = QCheckBox("✓ เก็บ")
        check.setObjectName(f"remember_{key}")
        check.setToolTip("ติ๊กเพื่อเพิ่มยอดในช่องสะสม; เอาติ๊กออกเพื่อลบรายการล่าสุด")
        layout.addWidget(check)
        saved = self._memory_total_field(f"remembered_{key}")
        saved.setFixedWidth(115)
        layout.addWidget(saved)
        self._saved_amounts[key] = []
        self._memory_controls[key] = (field, check, saved)
        check.toggled.connect(
            lambda checked, k=key: self._toggle_remembered_amount(k, checked)
        )
        field.textChanged.connect(
            lambda _text, k=key: self._memory_input_edited(k)
        )
        return row

    def _memory_input_edited(self, key):
        # Changing the number prepares the checkbox for saving another entry,
        # while leaving the previously saved entries in the ledger.
        check = self._memory_controls[key][1]
        if check.isChecked():
            check.blockSignals(True)
            check.setChecked(False)
            check.blockSignals(False)

    def _toggle_remembered_amount(self, key, checked):
        field, check, _saved = self._memory_controls[key]
        if checked:
            if not field.text().strip():
                check.blockSignals(True)
                check.setChecked(False)
                check.blockSignals(False)
                return
            try:
                value = amount(field.text())
            except ValueError as error:
                check.blockSignals(True)
                check.setChecked(False)
                check.blockSignals(False)
                QMessageBox.warning(self, "บันทึกยอด / 保存金额", str(error))
                return
            self._saved_amounts[key].append(value)
        elif self._saved_amounts[key]:
            self._saved_amounts[key].pop()
        self._refresh_remembered_amounts()

    def _refresh_remembered_amounts(self):
        for key, entries in self._saved_amounts.items():
            saved = self._memory_controls[key][2]
            saved.setText(f"{sum(entries, Decimal('0.00')):,.2f}")
            saved.setToolTip(
                "บันทึกแล้ว / 已保存: " +
                (" + ".join(f"{v:,.2f}" for v in entries) if entries else "ไม่มี / 无")
            )
        for tab_index, keys in (
            (1, ("gross", "paid")),
            (2, ("base", "forward_paid")),
        ):
            total_field = self._memory_tab_totals.get(tab_index)
            if total_field is not None:
                total = sum(
                    (value for key in keys for value in self._saved_amounts.get(key, ())),
                    Decimal("0.00"),
                )
                total_field.setText(f"{total:,.2f}")

    def _clear_memory(self, *keys):
        for key in keys:
            self._saved_amounts[key].clear()
            check = self._memory_controls[key][1]
            check.blockSignals(True)
            check.setChecked(False)
            check.blockSignals(False)
        self._refresh_remembered_amounts()

    @staticmethod
    def _make_result_area(name):
        area = QTextEdit()
        area.setObjectName(name)
        area.setReadOnly(True)
        area.setMinimumHeight(190)
        area.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        return area

    @classmethod
    def _format_summary(cls, area, data):
        plain = "\n".join(
            f"{title}: {baht(data[key])}" for key, title in cls.LABELS
        )
        lines = []
        for key, title in cls.LABELS:
            value = data[key]
            color = "#FF5252" if value < 0 else "#FDE047"
            notable_tax = key in {"vat", "withheld"}
            line_markup = (
                f'<span style="color:#F9FAFB;">{escape(title)}:</span> '
                f'<b style="color:{color};">{escape(baht(value))}</b>'
            )
            if notable_tax:
                line_markup = f"<u>{line_markup}</u>"
            lines.append(
                '<div style="margin:2px 0;">' + line_markup + '</div>'
            )
        area.setHtml(
            '<html><body style="font-size:11pt;background:#18212E;">'
            + "".join(lines) + "</body></html>"
        )
        return plain

    def recalculate(self):
        """Partition 1: keep the original VAT-inclusive calculation."""
        if not self.gross_input.text().strip():
            self._result = None
            self._plain_result = ""
            self.copy_button.setEnabled(False)
            self.answer.setPlainText(
                "กรอกยอดบิลที่มี VAT 7% แล้ว / 请输入含税金额，例如 5,000 บาท"
            )
            return
        try:
            data = invoice_withholding_3_percent(
                self.gross_input.text(), self.paid_input.text()
            )
        except ValueError as error:
            self._result = None
            self._plain_result = ""
            self.copy_button.setEnabled(False)
            self.answer.setPlainText(str(error))
            return
        self._result = data
        self.copy_button.setEnabled(True)
        self._plain_result = self._format_summary(self.answer, data)

    def recalculate_forward(self):
        """Partition 2: calculate and add VAT first, then deduct WHT."""
        if not self.base_input.text().strip():
            self._forward_result = None
            self._forward_plain_result = ""
            self.forward_copy_button.setEnabled(False)
            self.forward_answer.setPlainText(
                "กรอกฐานก่อน VAT / 请输入未税金额，例如 5,000 บาท เพื่อเพิ่ม VAT 7% / 加计增值税"
            )
            return
        try:
            data = base_plus_vat_withholding_3_percent(
                self.base_input.text(), self.forward_paid_input.text()
            )
        except ValueError as error:
            self._forward_result = None
            self._forward_plain_result = ""
            self.forward_copy_button.setEnabled(False)
            self.forward_answer.setPlainText(str(error))
            return
        self._forward_result = data
        self.forward_copy_button.setEnabled(True)
        self._forward_plain_result = self._format_summary(
            self.forward_answer, data
        )

    def recalculate_adjust(self):
        """Tab 3: +3%, included 3% and WHT gross-up without any VAT."""
        if not self.adjust_input.text().strip():
            self._adjust_result = None
            self._adjust_plain_result = ""
            self.adjust_copy_button.setEnabled(False)
            self.adjust_answer.setPlainText(
                "กรอกยอดเงิน / 请输入金额，例如 1,000 บาท เพื่อคำนวณบวกหรือถอด 3% / 加减3%"
            )
            return
        try:
            data = three_percent_adjustments(self.adjust_input.text())
        except ValueError as error:
            self._adjust_result = None
            self._adjust_plain_result = ""
            self.adjust_copy_button.setEnabled(False)
            self.adjust_answer.setPlainText(str(error))
            return
        self._adjust_result = data
        self.adjust_copy_button.setEnabled(True)
        sections = (
            ("ยอดตั้งต้น (ไม่รวม VAT 7%) / 初始金额（不含增值税）", (("entered", "ยอดมี 3% / ยอดเงินที่กรอก · 输入金额"),)),
            ("ถอด 3% แบบหัก ณ ที่จ่าย (คูณ 97%) / 扣除3%预扣税（×97%）", (
                ("deducted_3_percent", "ภาษีหัก ณ ที่จ่าย 3% / 预扣税3% / 3%预扣税额"),
                ("deducted_total", "ยอดถอด 3% / ยอดสุทธิหลังหัก · 扣税后净额"),
            )),
            ("บวก 3% ของฐาน (คูณ 1.03) / 加收3%（×1.03）", (
                ("added_tax", "ยอดบวกเพิ่ม 3% / 加收3%金额"),
                ("plus_total", "ยอดหลังบวก 3% / 加收后总额"),
            )),
            ("ถอดส่วนที่บวก 3% มาแล้ว (หาร 1.03 — คนละสูตร) / 反推已加收3%的基数（÷1.03）", (
                ("included_base", "ฐานราคาก่อนบวก 3% / 加收前基数"),
                ("included_tax", "จำนวน 3% ที่รวมมาแล้ว / 内含3%金额"),
            )),
            ("หายอดก่อนหัก 3% จากยอดสุทธิ (หาร 0.97) / 由净额反推税前金额（÷0.97）", (
                ("gross_up", "ยอดก่อนถูกหัก ณ ที่จ่าย / 预扣税前总额"),
                ("gross_up_withheld", "จำนวนเงินภาษี 3% / 3%预扣税额"),
            )),
        )
        plain_lines = []
        html_lines = []
        for heading, entries in sections:
            plain_lines.append(heading)
            html_lines.append(
                '<div style="color:#FFFFFF;font-weight:700;margin:5px 0 1px 0;">'
                + escape(heading) + '</div>'
            )
            for key, label in entries:
                value = data[key]
                plain_lines.append(f"  {label}: {baht(value)}")
                color = "#FF5252" if value < 0 else "#FDE047"
                row_markup = (
                    f'<span style="color:#F9FAFB;">{escape(label)}:</span> '
                    f'<b style="color:{color};">{escape(baht(value))}</b>'
                )
                if "3%" in label or "7%" in label:
                    row_markup = f"<u>{row_markup}</u>"
                html_lines.append(
                    '<div style="margin:1px 0;">' + row_markup + '</div>'
                )
            plain_lines.append("")
        self._adjust_plain_result = "\n".join(plain_lines).strip()
        self.adjust_answer.setHtml(
            '<html><body style="font-size:10pt;background:#18212E;">'
            + "".join(html_lines) + '</body></html>'
        )

    def copy_adjust_result(self):
        if self._adjust_result is not None:
            QApplication.clipboard().setText(self._adjust_plain_result)

    def clear_adjust(self):
        self.adjust_input.clear()
        self.adjust_input.setFocus()

    def copy_result(self):
        if self._result is not None:
            QApplication.clipboard().setText(self._plain_result)

    def copy_forward_result(self):
        if self._forward_result is not None:
            QApplication.clipboard().setText(self._forward_plain_result)

    def clear(self):
        self.gross_input.clear()
        self.paid_input.clear()
        self._clear_memory("gross", "paid")
        self.gross_input.setFocus()

    def clear_forward(self):
        self.base_input.clear()
        self.forward_paid_input.clear()
        self._clear_memory("base", "forward_paid")
        self.base_input.setFocus()
