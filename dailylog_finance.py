"""Thai invoice breakdown: VAT included 7%, withholding 3% of VAT-exclusive base."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QVBoxLayout,
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
        raise ValueError("กรุณาระบุยอดเงินเป็นตัวเลขที่ถูกต้อง") from error
    if not result.is_finite() or result < 0:
        raise ValueError("ยอดเงินต้องเป็นตัวเลขที่ไม่ติดลบ")
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
    return f"{value:,.2f} บาท"


class WithholdingCalculator(QDialog):
    """Compact, standalone invoice calculator with no Supabase writes."""
    LABELS = (
        ("gross", "ยอดรวมบิล (รวม VAT 7%)"),
        ("tax_base", "ฐานก่อน VAT 7%"),
        ("vat", "ภาษีมูลค่าเพิ่ม 7%"),
        ("withheld", "หัก ณ ที่จ่าย 3%"),
        ("net", "ยอดสุทธิหลังหัก 3%"),
        ("paid", "ลูกค้าชำระแล้ว"),
        ("balance", "ส่วนต่างคงเหลือ / รับเกิน"),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("คำนวณบิล VAT 7% / หัก ณ ที่จ่าย 3%")
        self.resize(430, 365)
        self.setMinimumWidth(405)
        self.setStyleSheet(
            "QDialog { background: #111827; color: white; } "
            "QLabel { color: white; } "
            "QLineEdit { background: #1F2937; color: white; "
            "border: 1px solid #64748B; border-radius: 5px; padding: 5px; } "
            "QTextEdit { background: #18212E; color: white; "
            "border: 1px solid #475569; border-radius: 6px; } "
            "QPushButton { padding: 5px 8px; }"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(11, 9, 11, 9)
        root.setSpacing(7)
        intro = QLabel(
            "กรอกยอดเต็มของบิลที่รวม VAT 7% แล้ว\n"
            "ระบบคำนวณภาษีหัก ณ ที่จ่าย 3% จากฐานก่อน VAT"
        )
        intro.setWordWrap(True)
        root.addWidget(intro)
        form = QFormLayout()
        self.gross_input = QLineEdit()
        self.gross_input.setObjectName("grossIncludingVat")
        self.gross_input.setPlaceholderText("เช่น 5,000.00")
        self.paid_input = QLineEdit()
        self.paid_input.setPlaceholderText("ลูกค้าจ่ายแล้ว (ถ้ายังไม่ได้จ่าย เว้นว่าง)")
        form.addRow("รวม VAT 7%:", self.gross_input)
        form.addRow("ชำระแล้ว:", self.paid_input)
        root.addLayout(form)

        self.answer = QTextEdit()
        self.answer.setObjectName("invoiceSummary")
        self.answer.setReadOnly(True)
        self.answer.setMinimumHeight(182)
        self.answer.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        root.addWidget(self.answer, 1)
        buttons = QHBoxLayout()
        self.copy_button = QPushButton("คัดลอก")
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
        self._plain_result = ""
        self._result = None
        self.gross_input.textChanged.connect(self.recalculate)
        self.paid_input.textChanged.connect(self.recalculate)
        self.recalculate()

    def recalculate(self):
        if not self.gross_input.text().strip():
            self._result = None
            self.copy_button.setEnabled(False)
            self._plain_result = ""
            self.answer.setPlainText("กรอกยอดรวมบิลที่มี VAT 7% แล้ว เช่น 5,000 บาท")
            return
        try:
            result = invoice_withholding_3_percent(
                self.gross_input.text(), self.paid_input.text()
            )
        except ValueError as error:
            self._result = None
            self._plain_result = ""
            self.copy_button.setEnabled(False)
            self.answer.setPlainText(str(error))
            return

        self._result = result
        self.copy_button.setEnabled(True)
        self._plain_result = "\n".join(
            f"{title}: {baht(result[key])}" for key, title in self.LABELS
        )
        html_lines = []
        for key, title in self.LABELS:
            value = result[key]
            color = "#FF5252" if value < 0 else "#FDE047"
            html_lines.append(
                f'<div style="margin:2px 0;">'
                f'<span style="color:#F9FAFB;">{escape(title)}:</span> '
                f'<b style="color:{color};">{escape(baht(value))}</b></div>'
            )
        self.answer.setHtml(
            '<html><body style="font-size:11pt;background:#18212E;">'
            + "".join(html_lines) + "</body></html>"
        )

    def copy_result(self):
        if self._result is not None:
            QApplication.clipboard().setText(self._plain_result)

    def clear(self):
        self.gross_input.clear()
        self.paid_input.clear()
        self.gross_input.setFocus()
