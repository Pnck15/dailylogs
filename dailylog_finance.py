"""Withholding-tax arithmetic and the DailyLog 3% settlement calculator."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from PySide6.QtWidgets import (
    QApplication, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTextEdit, QVBoxLayout,
)

RATE_3_PERCENT = Decimal("0.03")
SATANG = Decimal("0.01")


def amount(value):
    """Parse a nonnegative THB amount without floating-point rounding."""
    value = str(value or "0").strip().replace(",", "")
    if not value:
        value = "0"
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError("กรุณาระบุยอดเงินเป็นตัวเลขที่ถูกต้อง") from error
    if not result.is_finite() or result < 0:
        raise ValueError("ยอดเงินต้องเป็นตัวเลขที่ไม่ติดลบ")
    return result.quantize(SATANG, rounding=ROUND_HALF_UP)


def settlement_3_percent(tax_base, invoice_amount=None, already_paid=0):
    """Tax base is before VAT; invoice is actual amount billed (may include VAT).

    withholding = base * 3%
    to_collect = invoice - withholding - customer_paid
    Positive to_collect is a remaining balance, negative is overpayment.
    """
    base = amount(tax_base)
    billed = base if invoice_amount is None or str(invoice_amount).strip() == "" else amount(invoice_amount)
    paid = amount(already_paid)
    withheld = (base * RATE_3_PERCENT).quantize(SATANG, rounding=ROUND_HALF_UP)
    net = billed - withheld
    balance = net - paid
    return {
        "tax_base": base,
        "invoice": billed,
        "withheld": withheld,
        "net": net,
        "paid": paid,
        "balance": balance,
        "remaining": max(balance, Decimal("0.00")),
        "overpaid": max(-balance, Decimal("0.00")),
    }


def baht(number):
    return f"{number:,.2f} บาท"


class WithholdingCalculator(QDialog):
    """Independent calculator; never touches CloudDB or creates a log."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("เครื่องคิดเลขหัก ณ ที่จ่าย 3%")
        self.resize(480, 420)
        root = QVBoxLayout(self)
        lead = QLabel(
            "หัก ณ ที่จ่าย 3% คิดจากฐานก่อน VAT\n"
            "ช่องยอดเรียกเก็บ ใช้ยอดใบแจ้งหนี้จริงที่ลูกค้าต้องชำระ"
        )
        lead.setWordWrap(True)
        root.addWidget(lead)
        inputs = QFormLayout()
        self.tax_base = QLineEdit()
        self.tax_base.setPlaceholderText("ฐานภาษีก่อน VAT เช่น 10,000.00")
        self.invoice = QLineEdit()
        self.invoice.setPlaceholderText("ยอดเรียกเก็บ (ว่าง = ใช้ฐานภาษี)")
        self.paid = QLineEdit()
        self.paid.setPlaceholderText("ชำระแล้ว (ว่าง = 0)")
        inputs.addRow("ฐานคำนวณ 3%:", self.tax_base)
        inputs.addRow("ยอดเรียกเก็บลูกค้า:", self.invoice)
        inputs.addRow("ลูกค้าชำระแล้ว:", self.paid)
        root.addLayout(inputs)
        self.answer = QTextEdit()
        self.answer.setReadOnly(True)
        self.answer.setMinimumHeight(145)
        root.addWidget(self.answer)
        buttons = QHBoxLayout()
        self.copy_button = QPushButton("คัดลอกผลลัพธ์")
        self.clear_button = QPushButton("ล้างค่า")
        close_button = QPushButton("ปิด")
        self.copy_button.clicked.connect(self.copy_result)
        self.clear_button.clicked.connect(self.clear)
        close_button.clicked.connect(self.accept)
        buttons.addWidget(self.clear_button)
        buttons.addStretch()
        buttons.addWidget(self.copy_button)
        buttons.addWidget(close_button)
        root.addLayout(buttons)
        for field in (self.tax_base, self.invoice, self.paid):
            field.textChanged.connect(self.recalculate)
        self.recalculate()

    def recalculate(self):
        if not self.tax_base.text().strip():
            self.copy_button.setEnabled(False)
            self.answer.setPlainText("ใส่ฐานคำนวณ 3% เพื่อดูยอดหักและส่วนต่าง")
            return
        try:
            values = settlement_3_percent(
                self.tax_base.text(), self.invoice.text(), self.paid.text()
            )
        except ValueError as error:
            self.copy_button.setEnabled(False)
            self.answer.setPlainText(str(error))
            return
        self.copy_button.setEnabled(True)
        lines = [
            f"ฐานก่อน VAT: {baht(values['tax_base'])}",
            f"ยอดเรียกเก็บลูกค้า: {baht(values['invoice'])}",
            f"ภาษีหัก ณ ที่จ่าย 3%: {baht(values['withheld'])}",
            f"ยอดสุทธิหลังหัก 3%: {baht(values['net'])}",
            f"ชำระแล้ว: {baht(values['paid'])}",
            f"ยอดคงเหลือต้องเก็บ: {baht(values['remaining'])}",
            f"รับเงินเกิน: {baht(values['overpaid'])}",
        ]
        self.answer.setPlainText("\n".join(lines))

    def copy_result(self):
        if self.copy_button.isEnabled():
            QApplication.clipboard().setText(self.answer.toPlainText())

    def clear(self):
        self.tax_base.clear()
        self.invoice.clear()
        self.paid.clear()
        self.tax_base.setFocus()
