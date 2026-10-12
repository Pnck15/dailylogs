"""Offline Windows QA: tax, red-plate Add/Edit, existing general logs.

Runs after build_notify.ps1's main counterpart creates .venv with PySide6.
Never connects Supabase or changes the user's data.
"""
import os
import sys
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QStackedWidget, QWidget, QPushButton
from dailylog_finance import invoice_withholding_3_percent, settlement_3_percent, WithholdingCalculator
from dailylog_forms import RED_PLATE_HEADER, RedPlateForm, serialize_red_plate, parse_red_plate, split_log_plate, with_log_plate, STRUCTURED_FORM_SPECS, StructuredLogForm, serialize_structured_log, parse_structured_log
from main import DailyLog


def test_finance(app):
    result = settlement_3_percent("10,000", "10,700.00", "4,000.00")
    assert result["withheld"] == Decimal("300.00")
    assert result["net"] == Decimal("10400.00")
    assert result["remaining"] == Decimal("6400.00")
    assert result["overpaid"] == Decimal("0.00")
    assert settlement_3_percent("33.33")["withheld"] == Decimal("1.00")
    assert settlement_3_percent("1,000", "1,070", "1,100")["overpaid"] == Decimal("60.00")
    for illegal in ("-1", "NaN", "abc", "Infinity"):
        try:
            settlement_3_percent(illegal)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Invalid amount accepted: {illegal}")
    gross = invoice_withholding_3_percent("5,000")
    assert gross["gross"] == Decimal("5000.00")
    assert gross["tax_base"] == Decimal("4672.90")
    assert gross["vat"] == Decimal("327.10")
    assert gross["withheld"] == Decimal("140.19")
    assert gross["net"] == Decimal("4859.81")
    assert gross["remaining"] == Decimal("4859.81")
    assert gross["tax_base"] + gross["vat"] == gross["gross"]
    negative = invoice_withholding_3_percent("5000", "5001")
    assert negative["balance"] == Decimal("-141.19")
    assert negative["overpaid"] == Decimal("141.19")
    calc = WithholdingCalculator()
    assert calc.width() <= 450
    calc.gross_input.setText("5,000.00")
    assert "4,859.81" in calc.answer.toPlainText()
    assert "#fde047" in calc.answer.toHtml().lower()
    calc.paid_input.setText("5,001")
    assert "-141.19" in calc.answer.toPlainText()
    assert "#ff5252" in calc.answer.toHtml().lower()
    calc.copy_result()
    assert "140.19 บาท" in app.clipboard().text()
    calc.clear()
    assert not calc.copy_button.isEnabled()
    calc.close()


def example():
    return {
        "customer": "คุณตัวอย่าง",
        "vin": "lmgna000000100010",
        "plate": "6 ขอ 7577",
        "received_date": "2026-10-10",
        "returned_date": "",
        "sc_name": "SC Sathorn",
        "notes": "หมายเหตุบรรทัดแรก\nข้อมูลเพิ่มเติม",
    }


def test_red_plate_serialization(app):
    data = example()
    text = serialize_red_plate(data)
    assert text.startswith(RED_PLATE_HEADER + "\n")
    assert "ยังไม่คืน" in text
    assert "LMGNA000000100010" in text
    parsed = parse_red_plate(text)
    assert parsed["customer"] == data["customer"]
    assert parsed["vin"] == data["vin"].upper()
    assert parsed["plate"] == "6 ขอ 7577"
    assert parsed["returned_date"] == ""
    assert parsed["notes"] == data["notes"]
    assert parse_red_plate("Ordinary Daily Log details") is None
    bad = dict(data, returned_date="2026-10-09")
    try:
        serialize_red_plate(bad)
    except ValueError as e:
        assert "วันที่คืน" in str(e)
    else:
        raise AssertionError("Return before issue date must be rejected")
    editor = RedPlateForm()
    editor.set_values(parsed)
    assert editor.not_returned.isChecked()
    assert editor.values()["notes"] == data["notes"]
    assert "2026" in editor.received_date.text()
    assert all(char not in editor.received_date.text() for char in "๐๑๒๓๔๕๖๗๘๙")
    assert "#ffffff" in editor.not_returned.styleSheet().lower()
    assert split_log_plate("บันทึกเดิม") == ("", "บันทึกเดิม")
    assert split_log_plate(with_log_plate("รายละเอียด", "กข 1234")) == (
        "กข 1234", "รายละเอียด"
    )
    editor.reset(QDate(2026, 11, 2))
    assert editor.received_date.date() == QDate(2026, 11, 2)
    assert not editor.customer.text()
    editor.close()


def test_new_form_serialization(app):
    example_values = {
        "vehicle_receipt": {
            "sc_name": "SC Sathorn", "customer": "คุณตัวอย่าง",
            "vin": "lmgna000000012345", "received_date": "2026-10-12",
            "payment_date": "", "payment_method": "โอนเงิน",
            "notes": "รับรถ\nสภาพสมบูรณ์",
        },
        "customer_payment": {
            "ro": "RO12345", "vin": "lmgna000000012345",
            "customer": "คุณตัวอย่าง", "payer": "เจ้าของรถ",
            "payment_date": "2026-10-12", "payment_method": "QR Code",
            "notes": "ชำระครบ",
        },
    }
    for key, fields in example_values.items():
        form = StructuredLogForm(key)
        form.set_values(fields)
        stored = serialize_structured_log(key, form.values())
        mode, restored = parse_structured_log(stored)
        assert mode == key
        assert restored["vin"] == fields["vin"].upper()
        assert restored["notes"] == fields["notes"]
        assert restored["payment_method"] == fields["payment_method"]
        assert STRUCTURED_FORM_SPECS[key]["title"] in stored.splitlines()[0]
        if key == "vehicle_receipt":
            assert restored["payment_date"] == ""
            form.widgets["payment_date"].setDate(QDate(2026, 10, 14))
            form.date_enabled["payment_date"].setChecked(False)
            assert form.values()["payment_date"] == "2026-10-14"
        assert parse_structured_log("Ordinary old log") == (None, None)
        form.close()
    bad = dict(example_values["customer_payment"], ro="")
    try:
        serialize_structured_log("customer_payment", bad)
    except ValueError as error:
        assert "RO" in str(error)
    else:
        raise AssertionError("RO field is required")


class FakeCloud:
    def __init__(self):
        self.added = []
        self.updated = []

    def add_log(self, *args):
        self.added.append(args)
        return 111

    def update_log(self, *args):
        self.updated.append(args)
        return 112


def test_main_add_and_edit(app):
    # A QWidget with only the Add/Edit page dependencies, no real cloud auth.
    owner = DailyLog.__new__(DailyLog)
    QWidget.__init__(owner)
    owner.selected_date = QDate(2026, 10, 10)
    owner.expanded_height = 280
    owner.expanded_width = 580
    owner.is_collapsed = False
    owner.pages = QStackedWidget()
    owner._cloud_pending = {}
    owner.cloud = FakeCloud()
    owner.add_page = owner.create_add_page()
    owner.pages.addWidget(owner.add_page)
    owner.open_add_page()
    assert owner.log_form_selector.currentData() == "general"
    assert owner.log_add_stack.currentIndex() == 0
    assert owner.log_form_selector.objectName() == "dailyLogFormSelector"
    assert "#ffffff" in owner.log_form_selector.styleSheet().lower()

    # Existing general logs keep their free-text form and storage format.
    owner.title_input.setText("งานทั่วไป")
    owner.description_input.setPlainText("บันทึกเดิม")
    owner.save_log()
    assert owner.cloud.added[-1][2:] == ("งานทั่วไป", "บันทึกเดิม")

    # Change the selector located BESIDE Title, no new database columns.
    owner.log_form_selector.setCurrentIndex(1)
    assert owner.log_add_stack.currentIndex() == 1
    assert owner.height() > owner.expanded_height
    owner.red_plate_form.set_values(example())
    owner.plate_input.setText("6 ขอ 7577")
    owner.title_input.setText("รับป้ายแดง")
    owner.save_log()
    saved = owner.cloud.added[-1]
    assert saved[0] == "2026-10-10"
    assert saved[2] == "รับป้ายแดง - คุณตัวอย่าง"
    assert parse_red_plate(saved[3])["customer"] == "คุณตัวอย่าง"
    assert parse_red_plate(saved[3])["plate"] == "6 ขอ 7577"

    log = (33, "2026-10-10", "10:00:00", saved[2], saved[3], "sc")
    owner._open_edit_dialog(33, log)
    app.processEvents()
    edit_dialog = next(
        dlg for dlg in owner.findChildren(QDialog)
        if dlg.windowTitle() == "Edit Log" and dlg.isVisible()
    )
    editor = edit_dialog.findChild(RedPlateForm)
    assert editor is not None
    assert editor.customer.text() == "คุณตัวอย่าง"
    edit_selector = next(
        combo for combo in edit_dialog.findChildren(QComboBox)
        if combo.objectName() == "dailyLogFormSelector"
    )
    assert edit_selector.currentData() == "red_plate"
    assert "#ffffff" in edit_selector.styleSheet().lower()
    editor.sc_name.setText("SC Srinakarin")
    save_btn = next(
        b for b in edit_dialog.findChildren(QPushButton)
        if b.text() == "Save"
    )
    save_btn.click()
    assert owner.cloud.updated
    assert parse_red_plate(owner.cloud.updated[-1][2])["sc_name"] == "SC Srinakarin"
    assert parse_red_plate(owner.cloud.updated[-1][2])["plate"] == "6 ขอ 7577"
    edit_dialog.close()

    # The two new forms must work through the actual Add Log page and
    # preserve their markers when edited in a separate dialog.
    for index, (form_key, props) in enumerate([
        ("vehicle_receipt", {
            "sc_name": "SC Sathorn", "customer": "คุณทดสอบ",
            "vin": "lmgna000011112222", "received_date": "2026-10-12",
            "payment_date": "", "payment_method": "เงินสด",
            "notes": "รับรถเรียบร้อย",
        }),
        ("customer_payment", {
            "ro": "RO56789", "vin": "lmgna000011112222",
            "customer": "คุณทดสอบ", "payer": "ฝ่ายบัญชี",
            "payment_date": "2026-10-12", "payment_method": "บัตรเครดิต",
            "notes": "จ่ายยอดครบ",
        }),
    ]):
        owner.open_add_page()
        expected_idx = list(STRUCTURED_FORM_SPECS).index(form_key) + 2
        owner.log_form_selector.setCurrentIndex(expected_idx)
        assert owner.log_add_stack.currentIndex() == expected_idx
        owner.structured_forms[form_key].set_values(props)
        owner.save_log()
        saved = owner.cloud.added[-1]
        assert saved[2].startswith(STRUCTURED_FORM_SPECS[form_key]["title"])
        mode, restored = parse_structured_log(saved[3])
        assert mode == form_key
        assert restored["payment_method"] == props["payment_method"]
        log = (70 + index, "2026-10-12", "15:00:00", saved[2], saved[3], "sc")
        owner._open_edit_dialog(70 + index, log)
        app.processEvents()
        dialog = next(
            d for d in owner.findChildren(QDialog)
            if d.windowTitle() == "Edit Log" and d.isVisible()
        )
        field = next(
            w for w in dialog.findChildren(StructuredLogForm)
            if w.form_key == form_key
        )
        field.widgets["notes"].setPlainText("แก้ไขบันทึกแล้ว")
        button = next(
            b for b in dialog.findChildren(QPushButton) if b.text() == "Save"
        )
        button.click()
        updated = owner.cloud.updated[-1][2]
        mode, restored = parse_structured_log(updated)
        assert mode == form_key and restored["notes"] == "แก้ไขบันทึกแล้ว"
        dialog.hide()

    # This intentionally partial QWidget only initializes Add/Edit dependencies;
    # don't invoke DailyLog.closeEvent, which belongs to the full app and
    # requires running monitor timers. There is no network/login in this test.
    owner.hide()
    owner.deleteLater()


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    test_finance(app)
    test_red_plate_serialization(app)
    test_new_form_serialization(app)
    test_main_add_and_edit(app)
    print("PASS: VAT invoice, Add/Edit of red plate, vehicle receipt and customer payment templates.")
