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
from dailylog_finance import settlement_3_percent, WithholdingCalculator
from dailylog_forms import RED_PLATE_HEADER, RedPlateForm, serialize_red_plate, parse_red_plate
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
    calc = WithholdingCalculator()
    calc.tax_base.setText("10,000.00")
    calc.invoice.setText("10,700")
    calc.paid.setText("4,000")
    assert "6,400.00 บาท" in calc.answer.toPlainText()
    calc.copy_result()
    assert "300.00 บาท" in app.clipboard().text()
    calc.clear()
    assert not calc.copy_button.isEnabled()
    calc.close()


def example():
    return {
        "customer": "คุณตัวอย่าง",
        "vin": "lmgna000000100010",
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
    editor.reset(QDate(2026, 11, 2))
    assert editor.received_date.date() == QDate(2026, 11, 2)
    assert not editor.customer.text()
    editor.close()


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
    owner.title_input.setText("รับป้ายแดง")
    owner.save_log()
    saved = owner.cloud.added[-1]
    assert saved[0] == "2026-10-10"
    assert saved[2] == "รับป้ายแดง - คุณตัวอย่าง"
    assert parse_red_plate(saved[3])["customer"] == "คุณตัวอย่าง"

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
    editor.sc_name.setText("SC Srinakarin")
    save_btn = next(
        b for b in edit_dialog.findChildren(QPushButton)
        if b.text() == "Save"
    )
    save_btn.click()
    assert owner.cloud.updated
    assert parse_red_plate(owner.cloud.updated[-1][2])["sc_name"] == "SC Srinakarin"
    edit_dialog.close()
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
    test_main_add_and_edit(app)
    print("PASS: Decimal WHT, red-plate form serialization, real Add/Edit UI, legacy general logs.")
