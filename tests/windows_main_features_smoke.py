"""Offline Windows QA: tax, red-plate Add/Edit, existing general logs.

Runs after build_notify.ps1's main counterpart creates .venv with PySide6.
Never connects Supabase or changes the user's data.
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QStackedWidget, QWidget, QPushButton, QLineEdit, QLabel, QListWidget, QTextEdit, QMessageBox, QCheckBox
from dailylog_finance import invoice_withholding_3_percent, base_plus_vat_withholding_3_percent, settlement_3_percent, three_percent_adjustments, WithholdingCalculator
from dailylog_forms import RED_PLATE_HEADER, RedPlateForm, serialize_red_plate, parse_red_plate, split_log_plate, with_log_plate, STRUCTURED_FORM_SPECS, StructuredLogForm, serialize_structured_log, parse_structured_log
from main import DailyLog, session_hidden_after_24h
from dailylog_notification_history import NotificationLogsDialog, PAGE_SIZE
from cloud_db import CloudDB


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
    # Two distinct parts: pre-tax -> VAT -> WHT, or VAT-inclusive -> WHT.
    forward = base_plus_vat_withholding_3_percent("5,000.00")
    assert forward["tax_base"] == Decimal("5000.00")
    assert forward["vat"] == Decimal("350.00")
    assert forward["gross"] == Decimal("5350.00")
    assert forward["withheld"] == Decimal("150.00")
    assert forward["net"] == Decimal("5200.00")
    assert forward["remaining"] == Decimal("5200.00")
    with_paid = base_plus_vat_withholding_3_percent("5,000", "5,500")
    assert with_paid["balance"] == Decimal("-300.00")
    assert with_paid["overpaid"] == Decimal("300.00")
    small = base_plus_vat_withholding_3_percent("123.45")
    assert small["vat"] == Decimal("8.64")
    assert small["withheld"] == Decimal("3.70")
    for illegal in ("-1", "NaN", "Infinity", "test"):
        try:
            base_plus_vat_withholding_3_percent(illegal)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid pre-VAT total accepted")
    # Standalone 3% tab handles two different mathematical meanings of
    # "ถอด 3%" and a separate withholding gross-up calculation.
    # Requested WHT deduction: 30,927.84 - ROUND(30,927.84 * 3%)
    # = 30,000.00. This is NOT an inverse markup (divide by 1.03).
    wht_example = three_percent_adjustments("30,927.84")
    assert wht_example["entered"] == Decimal("30927.84")
    assert wht_example["deducted_3_percent"] == Decimal("927.84")
    assert wht_example["deducted_total"] == Decimal("30000.00")
    assert wht_example["included_base"] != wht_example["deducted_total"]
    third = three_percent_adjustments("1,000")
    assert third["entered"] == Decimal("1000.00")
    assert third["added_tax"] == Decimal("30.00")
    assert third["plus_total"] == Decimal("1030.00")
    assert third["included_base"] == Decimal("970.87")
    assert third["included_tax"] == Decimal("29.13")
    assert third["gross_up"] == Decimal("1030.93")
    assert third["gross_up_withheld"] == Decimal("30.93")
    assert third["included_base"] + third["included_tax"] == third["entered"]
    assert third["gross_up"] - third["gross_up_withheld"] == third["entered"]
    assert three_percent_adjustments("0")["gross_up"] == Decimal("0.00")
    small_three = three_percent_adjustments("33.33")
    assert small_three["added_tax"] == Decimal("1.00")
    for invalid in ("-1", "NaN", "Infinity", "word"):
        try:
            three_percent_adjustments(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("Three-percent tool accepted invalid amount")

    calc = WithholdingCalculator()
    assert calc.width() <= 450
    assert calc.tabs.count() == 3
    assert not calc.isModal()
    assert bool(calc.windowFlags() & Qt.WindowType.Window)
    calc.gross_input.setText("5,000.00")
    assert "4,859.81" in calc.answer.toPlainText()
    assert "#fde047" in calc.answer.toHtml().lower()
    calc.paid_input.setText("5,001")
    assert "-141.19" in calc.answer.toPlainText()
    assert "#ff5252" in calc.answer.toHtml().lower()
    calc.copy_result()
    assert "140.19 บาท" in app.clipboard().text()

    # Partition 2 must be independently editable/copyable from Partition 1.
    calc.tabs.setCurrentIndex(1)
    calc.base_input.setText("5,000")
    assert "5,200.00 บาท" in calc.forward_answer.toPlainText()
    assert "350.00 บาท" in calc.forward_answer.toPlainText()
    calc.forward_copy_button.click()
    assert "150.00 บาท" in app.clipboard().text()
    calc.forward_paid_input.setText("5,500")
    assert "-300.00" in calc.forward_answer.toPlainText()
    assert "#ff5252" in calc.forward_answer.toHtml().lower()
    calc.clear_forward()
    assert not calc.forward_copy_button.isEnabled()

    # Partition 3 must be copyable, editable, and independent from tabs 1/2.
    calc.tabs.setCurrentIndex(2)
    calc.adjust_input.setText("1,000")
    result_text = calc.adjust_answer.toPlainText()
    assert "1,030.00 บาท" in result_text
    assert "970.87 บาท" in result_text
    assert "1,030.93 บาท" in result_text
    assert "970.00 บาท" in result_text
    assert "30.00 บาท" in result_text
    assert "29.13 บาท" in result_text
    assert "30.93 บาท" in result_text
    assert "#fde047" in calc.adjust_answer.toHtml().lower()
    calc.adjust_copy_button.click()
    copied = app.clipboard().text()
    assert "หาร 1.03" in copied
    assert "หาร 0.97" in copied
    assert "1,030.93 บาท" in copied
    calc.adjust_input.setText("30,927.84")
    assert "30,000.00 บาท" in calc.adjust_answer.toPlainText()
    assert "927.84 บาท" in calc.adjust_answer.toPlainText()
    calc.adjust_copy_button.click()
    assert "30,000.00 บาท" in app.clipboard().text()
    calc.adjust_input.setText("not-money")
    assert not calc.adjust_copy_button.isEnabled()
    calc.adjust_input.setText("500")
    assert calc.adjust_copy_button.isEnabled()
    calc.clear_adjust()
    assert not calc.adjust_copy_button.isEnabled()
    assert not calc.adjust_input.text().strip()
    # Switching back must not reset the original calculation.
    calc.tabs.setCurrentIndex(0)
    assert "140.19 บาท" in calc.answer.toPlainText()
    calc.clear()
    assert not calc.copy_button.isEnabled()
    calc.close()


def test_calculator_standalone_window(app):
    # Nonmodal opening must leave DailyLog's controls interactive.
    owner = DailyLog.__new__(DailyLog)
    QWidget.__init__(owner)
    owner.show()
    app.processEvents()
    try:
        assert owner.isEnabled()
        assert not hasattr(owner, "_calculator_dialog")
        owner.open_withholding_calculator()
        app.processEvents()
        dialog = owner._calculator_dialog
        assert dialog.parent() is None, "Calculator must own its Windows taskbar window"
        assert dialog.isVisible()
        assert not dialog.isModal()
        assert owner.isEnabled(), "Calculator must not disable the DailyLog window"
        dialog.tabs.setCurrentIndex(1)
        dialog.base_input.setText("1,000")
        assert "1,040.00 บาท" in dialog.forward_answer.toPlainText()
        dialog.tabs.setCurrentIndex(2)
        dialog.adjust_input.setText("1,000")
        assert "1,030.93 บาท" in dialog.adjust_answer.toPlainText()
        assert owner.isEnabled(), "The standalone three-percent tab must be non-modal"

        # Reopening via the header shortcut must reuse, not duplicate it.
        owner.open_withholding_calculator()
        app.processEvents()
        assert owner._calculator_dialog is dialog
        dialog.close()
        app.processEvents()
        assert not dialog.isVisible()
        assert owner.isVisible()
        owner.open_withholding_calculator()
        app.processEvents()
        assert dialog.isVisible()
    finally:
        dialog = getattr(owner, "_calculator_dialog", None)
        if dialog is not None:
            dialog.close()
            dialog.deleteLater()
        owner.hide()
        owner.deleteLater()

    import inspect
    header = inspect.getsource(DailyLog.__init__)
    assert "self.save_background_button" not in header
    assert "self.calculator_shortcut_button" in header
    assert 'self.save_background' in inspect.getsource(DailyLog.show_settings_menu)


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
            "plate": "6 ขอ 7577",
            "vin": "lmgna000000012345", "received_date": "2026-10-12",
            "payment_date": "", "payment_method": "โอนเงิน",
            "notes": "รับรถ\nสภาพสมบูรณ์",
        },
        "customer_payment": {
            "ro": "RO12345", "vin": "lmgna000000012345",
            "plate": "8 กท 1234",
            "customer": "คุณตัวอย่าง", "payer": "เจ้าของรถ",
            "payment_date": "2026-10-12", "payment_method": "QR Code",
            "notes": "ชำระครบ",
        },
    }
    for key, fields in example_values.items():
        form = StructuredLogForm(key)
        form.set_values(fields)
        stored = serialize_structured_log(
            key, {**form.values(), "plate": fields["plate"]}
        )
        mode, restored = parse_structured_log(stored)
        assert mode == key
        assert restored["vin"] == fields["vin"].upper()
        assert restored["plate"] == fields["plate"]
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
        owner.plate_input.setText("7 กท 7777")
        owner.save_log()
        saved = owner.cloud.added[-1]
        assert saved[2].startswith(STRUCTURED_FORM_SPECS[form_key]["title"])
        mode, restored = parse_structured_log(saved[3])
        assert mode == form_key
        assert restored["payment_method"] == props["payment_method"]
        assert restored["plate"] == "7 กท 7777"
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
        assert "7 กท 7777" in [
            box.text() for box in dialog.findChildren(QLineEdit)
        ]
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


def test_notification_history_db_read_only():
    class FakeQuery:
        def __init__(self):
            self.calls = []
        def select(self, *args):
            self.calls.append(("select", args))
            return self
        def eq(self, *args):
            self.calls.append(("eq", args))
            return self
        def neq(self, *args):
            self.calls.append(("neq", args))
            return self
        def order(self, *args, **kwargs):
            self.calls.append(("order", args, kwargs))
            return self
        def range(self, a, b):
            self.calls.append(("range", a, b))
            return self
        def execute(self):
            return SimpleNamespace(data=[{"id": 5, "title": "test"}])
    class FakeSupabase:
        def __init__(self):
            self.tables = []
            self.query = FakeQuery()
        def table(self, name):
            self.tables.append(name)
            return self.query

    db = CloudDB.__new__(CloudDB)
    db.user = object()
    db.session = object()
    db.workspace_id = "test-workspace"
    db.client = FakeSupabase()
    result = db.get_notification_history_page(2, 100)
    assert result == [{"id": 5, "title": "test"}]
    assert db.client.tables == ["notification_events"], (
        "Opening Notification Logs MUST NEVER query or delete Daily Logs"
    )
    assert ("range", 200, 299) in db.client.query.calls
    assert ("eq", ("workspace_id", "test-workspace")) in db.client.query.calls
    assert ("neq", ("notification_type", "history_purge")) in db.client.query.calls
    assert db.get_notification_history_page(0, 10000)
    assert ("range", 0, 99) in db.client.query.calls


def test_notification_history_and_offline_sessions(app):
    """Offline Qt test: no login, zero Supabase calls, no destructive writes."""
    now = datetime(2026, 10, 15, 5, 0, tzinfo=timezone.utc)
    old = (now - timedelta(hours=25)).isoformat()
    recent = (now - timedelta(hours=23)).isoformat()
    assert session_hidden_after_24h(
        {"online": False, "last_seen_at": old}, now
    )
    assert not session_hidden_after_24h(
        {"online": True, "last_seen_at": old}, now
    )
    assert not session_hidden_after_24h(
        {"online": False, "last_seen_at": recent}, now
    )
    assert session_hidden_after_24h(
        {"online": False, "session_updated_at": old}, now
    )
    assert not session_hidden_after_24h(
        {"online": False, "last_seen_at": "not-a-date"}, now
    )

    class FakeCloud:
        def __init__(self):
            self.calls = []
        def call(self, name, *args):
            self.calls.append((name, args))
            return len(self.calls)

    class MemoryNotification:
        def __init__(self):
            self.title = "แจ้งเตือนล่าสุด"
            self.message = "ข้อความที่เก็บในหน่วยความจำ\nเลือก Copy ได้"
            self.timestamp = now
            self.sheet = "SA Sathorn"
            self.notification_type = "edit"

    owner = DailyLog.__new__(DailyLog)
    QWidget.__init__(owner)
    owner._cloud_pending = {}
    owner.cloud = FakeCloud()
    owner.notification_presenter = SimpleNamespace(
        notifications=[MemoryNotification()]
    )
    try:
        owner.open_notification_logs()
        app.processEvents()
        dialog = owner._notification_history_dialog
        assert dialog is not None and dialog.isVisible()
        assert not dialog.isModal()
        assert dialog.items.count() == 1
        assert "หน่วยความจำ" in dialog.detail.toPlainText()
        assert owner.cloud.calls == [
            ("get_notification_history_page", (0, PAGE_SIZE))
        ]
        assert owner._cloud_pending[1] == (
            "notification_history_page", dialog
        )
        rows = [{
            "id": id_, "title": f"Notice {id_}",
            "message": "รายละเอียดแจ้งเตือน\nแถวที่เปลี่ยน", "source": "SA Sathorn",
            "notification_type": "edit", "created_at": "2026-10-15T04:30:00Z",
        } for id_ in range(PAGE_SIZE)]
        dialog.set_rows(rows)
        assert dialog.items.count() == PAGE_SIZE
        assert dialog.next.isEnabled()
        assert "Notice 0" in dialog.detail.toPlainText()
        dialog.next.click()
        assert owner.cloud.calls[-1] == (
            "get_notification_history_page", (1, PAGE_SIZE)
        )
        dialog.set_rows([{
            "id": PAGE_SIZE, "source": "Sale Deli Sathorn",
            "title": "Notice 100", "message": "VIN test",
            "notification_type": "new", "created_at": "2026-10-14T09:00:00Z",
        }])
        assert dialog.previous.isEnabled()
        assert not dialog.next.isEnabled()
        assert "VIN test" in dialog.detail.toPlainText()
        dialog.set_error("Temporary Internet outage")
        assert "Internet outage" in dialog.status.text()
        assert "VIN test" in dialog.detail.toPlainText()
        cursor = dialog.detail.textCursor()
        cursor.select(cursor.SelectionType.Document)
        dialog.detail.setTextCursor(cursor)
        dialog.detail.copy()
        assert "VIN test" in app.clipboard().text()
        menu = dialog.detail.createStandardContextMenu()
        assert menu is not None
        menu.deleteLater()
        assert dialog.previous.isEnabled()

        # Only offline stale rows disappear from the default Admin UI.
        sessions = QDialog(owner)
        sessions._session_list = QListWidget(sessions)
        sessions._details = QTextEdit(sessions)
        sessions._logout_button = QPushButton(sessions)
        sessions._status = QLabel(sessions)
        sessions._show_stale_check = QCheckBox(sessions)
        sessions._show_stale_check.setChecked(False)
        session_rows = [
            {"session_id": "online-id", "online": True,
             "device_registered": True, "last_seen_at": old},
            {"session_id": "stale-id", "online": False,
             "device_registered": True,
             "last_seen_at": (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()},
            {"session_id": "current-id", "online": False,
             "device_registered": True,
             "last_seen_at": datetime.now(timezone.utc).isoformat()},
        ]
        owner._render_notify_sessions(sessions, session_rows)
        assert sessions._session_list.count() == 2
        assert "stale-id" not in sessions._session_rows
        sessions._show_stale_check.setChecked(True)
        owner._render_notify_sessions(sessions, session_rows)
        assert sessions._session_list.count() == 3
        sessions.hide()
        sessions.deleteLater()
        dialog.close()
    finally:
        owner.hide()
        owner.deleteLater()


def test_admin_central_history_guard():
    """No Supabase operations: enforce authorization before creating request."""
    class OfflineClient:
        def __init__(self):
            self.calls = []
        def rpc(self, name, args):
            self.calls.append((name, args))
            return self
        def execute(self):
            return type("Result", (), {"data": {
                "scope": "yesterday", "deleted_events": 0, "marker_id": 1
            }})()

    db = CloudDB.__new__(CloudDB)
    db.user = object()
    db.session = object()
    db.workspace_id = "offline-test"
    db.client = OfflineClient()
    db.role = "member"
    try:
        db.purge_notification_history("all")
    except PermissionError:
        pass
    else:
        raise AssertionError("Member must not delete Central Events")
    assert db.client.calls == []

    db.role = "admin"
    try:
        db.purge_notification_history("forever")
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid range must be rejected")
    assert db.client.calls == []
    result = db.purge_notification_history("yesterday")
    assert result["marker_id"] == 1
    assert db.client.calls == [
        ("purge_notification_history", {"p_scope": "yesterday"})
    ]


def test_multi_notify_and_retention_ui(app):
    owner = DailyLog.__new__(DailyLog)
    QWidget.__init__(owner)
    dialog = QDialog(owner)
    dialog._multi_list = QListWidget(dialog)
    dialog._multi_details = QTextEdit(dialog)
    dialog._multi_status = QLabel(dialog)
    dialog._multi_rows = {}
    dialog.show()
    app.processEvents()
    fresh = datetime.now(timezone.utc).isoformat()
    owner._render_multi_notify(dialog, [
        {
            "source_key": "sa_sathorn",
            "source_name": "SA Sathorn",
            "enabled": True,
            "last_success_at": fresh,
            "last_error": None,
        },
        {
            "source_key": "sale_sathorn",
            "source_name": "Sale Deli Sathorn",
            "enabled": True,
            "last_success_at": fresh,
            "last_error": "GAS timeout",
        },
        {
            "source_key": "extra",
            "source_name": "Extra Source",
            "enabled": False,
            "last_success_at": None,
            "last_error": None,
        },
    ])
    assert dialog._multi_list.count() == 3
    assert dialog._multi_list.item(0).text().startswith("🟢")
    assert dialog._multi_list.item(1).text().startswith("🔴")
    assert dialog._multi_list.item(2).text().startswith("⚪")
    assert "GAS timeout" in dialog._multi_rows["sale_sathorn"]["last_error"]
    dialog.close()

    class FakeCloud:
        def __init__(self):
            self.calls = []
        def call(self, name, *args):
            self.calls.append((name, *args))
            return 8
    owner.cloud = FakeCloud()
    owner._cloud_pending = {}
    def choose_thirty_days(dlg):
        combo = dlg.findChild(QComboBox, "centralHistoryRetentionRange")
        assert combo is not None and combo.count() == 3
        assert combo.itemData(0) == "older_than_7_days"
        assert combo.itemData(1) == "older_than_30_days"
        assert combo.itemData(2) == "all"
        assert "#ffffff" in combo.styleSheet().lower()
        combo.setCurrentIndex(1)
        return QDialog.DialogCode.Accepted

    # Exercise the ACTUAL selection UI, without performing a database write.
    with patch("main.QDialog.exec", new=choose_thirty_days), patch(
        "main.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        owner.open_central_history_cleanup()
    assert owner.cloud.calls == [
        ("purge_notification_history", "older_than_30_days")
    ]
    assert owner._cloud_pending[8] == (
        "central_history_purge", "older_than_30_days"
    )
    with patch.object(
        DailyLog, "_choose_central_history_scope",
        return_value="older_than_7_days",
    ), patch(
        "main.QMessageBox.question",
        return_value=QMessageBox.StandardButton.No,
    ):
        owner.open_central_history_cleanup()
    assert len(owner.cloud.calls) == 1, "Cancel must not call deletion RPC"

    import inspect
    collapse = inspect.getsource(DailyLog.toggle_window)
    for forbidden in (
        "self.sale_alert_button.hide()",
        "self.sa_notify_button.hide()",
        "self.menu_button.hide()",
        "self.multi_notify_button.hide()",
        "self.calculator_shortcut_button.hide()",
    ):
        assert forbidden not in collapse, "Collapsed header must remain usable"
    import pathlib
    sql = (
        pathlib.Path(__file__).resolve().parents[1] /
        "supabase/central_notification_retention.sql"
    ).read_text(encoding="utf-8")
    assert "DELETE FROM public.notification_events" in sql
    assert "DELETE FROM public.logs" not in sql
    assert "TRUNCATE public.logs" not in sql
    assert "older_than_30_days" in sql
    assert "older_than_7_days" in sql
    owner.hide()
    owner.deleteLater()


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    test_finance(app)
    test_calculator_standalone_window(app)
    test_notification_history_and_offline_sessions(app)
    test_notification_history_db_read_only()
    test_red_plate_serialization(app)
    test_new_form_serialization(app)
    test_main_add_and_edit(app)
    test_admin_central_history_guard()
    test_multi_notify_and_retention_ui(app)
    print("PASS: WHT 30927.84 -> 30000, paginated Notification Logs, offline fallback, hide stale sessions, forms.")
