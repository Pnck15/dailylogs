"""Editable red-plate forms stored safely in the existing logs.description text.

No schema migration: logs already supports title + description. The first line
is a human-readable form identifier; all fields remain searchable and editable.
"""
from PySide6.QtCore import QDate, QLocale
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDateEdit, QFormLayout, QLabel, QLineEdit, QTextEdit, QWidget,
)

def style_form_selector(selector: QComboBox):
    """Readable button-like form selector for both Add and Edit screens."""
    selector.setObjectName("dailyLogFormSelector")
    selector.setMinimumWidth(152)
    selector.setStyleSheet("""
        QComboBox#dailyLogFormSelector {
            background: #1E293B;
            color: #FFFFFF;
            border: 2px solid #93C5FD;
            border-radius: 6px;
            padding: 5px 10px;
            font-weight: 600;
        }
        QComboBox#dailyLogFormSelector:hover,
        QComboBox#dailyLogFormSelector:focus {
            border-color: #FDE047;
            background-color: #334155;
        }
        QComboBox#dailyLogFormSelector QAbstractItemView {
            background-color: #1E293B;
            color: #FFFFFF;
            selection-background-color: #2563EB;
            selection-color: #FFFFFF;
        }
    """)
    return selector


RED_PLATE_HEADER = "แบบฟอร์ม: ป้ายแดง"
RED_PLATE_FIELDS = (
    ("customer", "ชื่อลูกค้า"),
    ("vin", "เลข VIN"),
    ("plate", "เลขทะเบียน"),
    ("received_date", "วันที่รับป้ายแดง"),
    ("returned_date", "วันที่คืนป้ายแดง"),
    ("sc_name", "ชื่อ SC"),
    ("notes", "หมายเหตุ"),
)
RED_PLATE_LABEL_TO_KEY = {label: key for key, label in RED_PLATE_FIELDS}


def serialize_red_plate(values):
    """Build readable, searchable text without storing extra private copies."""
    normalized = {key: str(values.get(key, "") or "").strip()
                  for key, _ in RED_PLATE_FIELDS}
    for key, label in RED_PLATE_FIELDS:
        if key in ('customer', 'vin', 'received_date') and not normalized[key]:
            raise ValueError(f"กรุณากรอก {label}")
    date = QDate.fromString(normalized["received_date"], "yyyy-MM-dd")
    if not date.isValid():
        raise ValueError("วันที่รับป้ายแดงไม่ถูกต้อง")
    if normalized["returned_date"]:
        returned = QDate.fromString(normalized["returned_date"], "yyyy-MM-dd")
        if not returned.isValid():
            raise ValueError("วันที่คืนป้ายแดงไม่ถูกต้อง")
        if returned < date:
            raise ValueError("วันที่คืนป้ายแดงต้องไม่ก่อนวันที่รับป้ายแดง")
    normalized["vin"] = normalized["vin"].upper()
    notes = normalized["notes"].splitlines()
    normalized["notes"] = notes[0] if notes else ""
    lines = [RED_PLATE_HEADER]
    for key, label in RED_PLATE_FIELDS:
        value = normalized[key]
        if key == "returned_date" and not value:
            value = "ยังไม่คืน"
        lines.append(f"{label}: {value}")
        if key == "notes" and len(notes) > 1:
            lines.extend(f"  {line}" for line in notes[1:])
    return "\n".join(lines)


PLATE_PREFIX = "เลขทะเบียน: "


def split_log_plate(description):
    """Read new general-log plate metadata; leave legacy logs unchanged."""
    text = str(description or "")
    head, separator, remainder = text.partition("\n")
    if head.startswith(PLATE_PREFIX):
        return head[len(PLATE_PREFIX):].strip(), remainder if separator else ""
    return "", text


def with_log_plate(description, plate):
    """Save license plate in existing searchable description; no schema change."""
    _, plain = split_log_plate(description)
    value = str(plate or "").strip()
    return PLATE_PREFIX + value + ("\n" + plain if plain else "") if value else plain


def parse_red_plate(description):
    lines = str(description or "").splitlines()
    if not lines or lines[0].strip() != RED_PLATE_HEADER:
        return None
    values = {key: "" for key, _ in RED_PLATE_FIELDS}
    last_key = None
    for line in lines[1:]:
        if line.startswith("  ") and last_key == "notes":
            values["notes"] += "\n" + line[2:]
            continue
        if ":" not in line:
            continue
        label, text = line.split(":", 1)
        key = RED_PLATE_LABEL_TO_KEY.get(label.strip())
        if key is None:
            continue
        value = text.strip()
        values[key] = "" if key == "returned_date" and value == "ยังไม่คืน" else value
        last_key = key
    return values


class RedPlateForm(QWidget):
    """Shared entry widget for Add Log and editing saved red-plate logs."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("redPlateForm")
        self.setStyleSheet("""
            QWidget#redPlateForm {
                background-color: #1E293B;
                border: 1px solid #64748B;
                border-radius: 7px;
            }
            QWidget#redPlateForm QLabel, QWidget#redPlateForm QCheckBox {
                color: #FFFFFF;
                background: transparent;
            }
            QWidget#redPlateForm QLineEdit,
            QWidget#redPlateForm QTextEdit,
            QWidget#redPlateForm QDateEdit {
                color: #FFFFFF;
                background-color: #334155;
                border: 1px solid #64748B;
                border-radius: 4px;
                padding: 3px;
            }
            QWidget#redPlateForm QDateEdit:disabled {
                color: #CBD5E1;
                background-color: #475569;
            }
        """)
        form = QFormLayout(self)
        form.setContentsMargins(9, 7, 9, 7)
        self.customer = QLineEdit()
        self.customer.setPlaceholderText("ชื่อ - นามสกุลลูกค้า")
        self.vin = QLineEdit()
        self.vin.setPlaceholderText("เลขตัวถัง / VIN")
        self.received_date = QDateEdit()
        self.received_date.setCalendarPopup(True)
        self.received_date.setLocale(
            QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
        )
        self.received_date.setDisplayFormat("dd/MM/yyyy")
        self.received_date.setDate(QDate.currentDate())
        self.not_returned = QCheckBox("ยังไม่คืนป้ายแดง")
        self.not_returned.setChecked(True)
        self.returned_date = QDateEdit()
        self.returned_date.setLocale(
            QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
        )
        self.returned_date.setDisplayFormat("dd/MM/yyyy")
        self.returned_date.setCalendarPopup(True)
        self.returned_date.setDate(QDate.currentDate())
        self.returned_date.setEnabled(False)
        for date_box in (self.received_date, self.returned_date):
            calendar = date_box.calendarWidget()
            if calendar is not None:
                calendar.setLocale(
                    QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
                )
                calendar.setStyleSheet("QCalendarWidget { color: #111827; background-color: #FFFFFF; }")
        self.not_returned.setStyleSheet(
            "QCheckBox { color: #FFFFFF; background: transparent; }"
        )
        self.not_returned.toggled.connect(
            lambda checked: self.returned_date.setEnabled(not checked)
        )
        self.sc_name = QLineEdit()
        self.sc_name.setPlaceholderText("ชื่อ SC ผู้รับผิดชอบ")
        self.notes = QTextEdit()
        self.notes.setPlaceholderText("หมายเหตุ (ถ้ามี)")
        self.notes.setMaximumHeight(78)
        form.addRow("ชื่อลูกค้า *", self.customer)
        form.addRow("เลข VIN *", self.vin)
        form.addRow("วันที่รับป้ายแดง *", self.received_date)
        form.addRow("สถานะคืนป้าย", self.not_returned)
        form.addRow("วันที่คืน", self.returned_date)
        form.addRow("ชื่อ SC", self.sc_name)
        form.addRow("หมายเหตุ", self.notes)

    def set_received_date(self, selected_date):
        if isinstance(selected_date, QDate) and selected_date.isValid():
            self.received_date.setDate(selected_date)
            self.returned_date.setDate(selected_date)

    def reset(self, selected_date=None):
        self.customer.clear()
        self.vin.clear()
        self.sc_name.clear()
        self.notes.clear()
        self.not_returned.setChecked(True)
        self.set_received_date(selected_date or QDate.currentDate())

    def set_values(self, values):
        values = dict(values or {})
        self.customer.setText(values.get("customer", ""))
        self.vin.setText(values.get("vin", ""))
        self.sc_name.setText(values.get("sc_name", ""))
        self.notes.setPlainText(values.get("notes", ""))
        received = QDate.fromString(
            values.get("received_date", ""), "yyyy-MM-dd"
        )
        if received.isValid():
            self.received_date.setDate(received)
        returned = QDate.fromString(
            values.get("returned_date", ""), "yyyy-MM-dd"
        )
        self.not_returned.setChecked(not returned.isValid())
        if returned.isValid():
            self.returned_date.setDate(returned)

    def values(self):
        return {
            "customer": self.customer.text().strip(),
            "vin": self.vin.text().strip(),
            "received_date": self.received_date.date().toString("yyyy-MM-dd"),
            "returned_date": (
                "" if self.not_returned.isChecked()
                else self.returned_date.date().toString("yyyy-MM-dd")
            ),
            "sc_name": self.sc_name.text().strip(),
            "notes": self.notes.toPlainText().strip(),
        }


# Structured receipt/payment logs intentionally share existing logs.title and
# logs.description. No database migration or deletion of older entries.
STRUCTURED_FORM_SPECS = {
    "vehicle_receipt": {
        "header": "แบบฟอร์ม: รับรถ",
        "title": "รับรถ",
        "fields": (
            ("sc_name", "ชื่อ SC", "text"),
            ("customer", "ชื่อลูกค้า", "text"),
            ("vin", "เลข VIN", "text"),
            ("received_date", "วันที่", "date"),
            ("payment_date", "จ่ายเงินวันไหน", "date_optional"),
            ("payment_method", "ช่องทางจ่าย", "payment"),
            ("notes", "หมายเหตุ", "notes"),
        ),
        "required": ("sc_name", "customer", "vin"),
    },
    "customer_payment": {
        "header": "แบบฟอร์ม: ลูกค้าจ่ายเงิน",
        "title": "ลูกค้าจ่ายเงิน",
        "fields": (
            ("ro", "เลข RO", "text"),
            ("vin", "เลข VIN", "text"),
            ("customer", "ชื่อลูกค้า", "text"),
            ("payer", "ชื่อคนจ่ายเงิน", "text"),
            ("payment_date", "จ่ายเงินวันไหน", "date"),
            ("payment_method", "ช่องทางจ่าย", "payment"),
            ("notes", "หมายเหตุ", "notes"),
        ),
        "required": ("ro", "vin", "customer"),
    },
}


def serialize_structured_log(form_key, values):
    """Serialize additional forms with a stable marker and safe note lines."""
    spec = STRUCTURED_FORM_SPECS.get(form_key)
    if spec is None:
        raise ValueError("ไม่พบประเภทแบบฟอร์ม")
    normalized = {
        key: str((values or {}).get(key) or "").strip()
        for key, _, _ in spec["fields"]
    }
    for key in spec["required"]:
        if not normalized[key]:
            label = next(label for field, label, _ in spec["fields"] if field == key)
            raise ValueError(f"กรุณากรอก {label}")
    for key, label, field_type in spec["fields"]:
        if field_type == "date" and not normalized[key]:
            raise ValueError(f"กรุณากรอก {label}")
        if field_type in ("date", "date_optional") and normalized[key]:
            if not QDate.fromString(normalized[key], "yyyy-MM-dd").isValid():
                raise ValueError(f"{label} ไม่ถูกต้อง")
    normalized["vin"] = normalized.get("vin", "").upper()
    lines = [spec["header"]]
    for key, label, _ in spec["fields"]:
        pieces = normalized[key].splitlines()
        lines.append(f"{label}: {pieces[0] if pieces else ''}")
        lines.extend("  " + text for text in pieces[1:])
    return "\n".join(lines)


def parse_structured_log(description):
    """Return (form_key, values) or (None, None) for general/legacy logs."""
    lines = str(description or "").splitlines()
    if not lines:
        return None, None
    for form_key, spec in STRUCTURED_FORM_SPECS.items():
        if lines[0].strip() != spec["header"]:
            continue
        values = {key: "" for key, _, _ in spec["fields"]}
        label_to_key = {label: key for key, label, _ in spec["fields"]}
        last_key = None
        for line in lines[1:]:
            if line.startswith("  ") and last_key:
                values[last_key] += "\n" + line[2:]
                continue
            if ": " not in line:
                continue
            label, text = line.split(": ", 1)
            last_key = label_to_key.get(label.strip())
            if last_key is not None:
                values[last_key] = text.strip()
        return form_key, values
    return None, None


class StructuredLogForm(QWidget):
    """One reusable Add/Edit widget for both vehicle and payment forms."""
    def __init__(self, form_key, parent=None):
        super().__init__(parent)
        if form_key not in STRUCTURED_FORM_SPECS:
            raise ValueError("ไม่พบประเภทแบบฟอร์ม")
        self.form_key = form_key
        self.spec = STRUCTURED_FORM_SPECS[form_key]
        self.widgets = {}
        self.date_enabled = {}
        self.setObjectName("structuredLogForm")
        self.setStyleSheet("""
            QWidget#structuredLogForm { background-color:#1E293B;
                border:1px solid #64748B; border-radius:6px; }
            QWidget#structuredLogForm QLabel { color:#FFFFFF; background:transparent; }
            QWidget#structuredLogForm QLineEdit,
            QWidget#structuredLogForm QDateEdit,
            QWidget#structuredLogForm QComboBox,
            QWidget#structuredLogForm QTextEdit {
                color:#FFFFFF; background-color:#334155;
                border:1px solid #64748B; border-radius:4px; padding:3px;
            }
            QWidget#structuredLogForm QCheckBox {
                color:#FFFFFF; background:transparent;
            }
        """)
        layout = QFormLayout(self)
        layout.setContentsMargins(9, 7, 9, 7)
        for key, label, field_type in self.spec["fields"]:
            if field_type in ("date", "date_optional"):
                picker = QDateEdit(self)
                picker.setCalendarPopup(True)
                picker.setLocale(
                    QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
                )
                picker.setDisplayFormat("dd/MM/yyyy")
                picker.setDate(QDate.currentDate())
                picker.calendarWidget().setLocale(
                    QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
                )
                self.widgets[key] = picker
                if field_type == "date_optional":
                    row = QWidget(self)
                    parts = QHBoxLayout(row)
                    parts.setContentsMargins(0, 0, 0, 0)
                    check = QCheckBox("ยังไม่กำหนด", row)
                    check.setChecked(True)
                    check.setStyleSheet("QCheckBox { color:#FFFFFF; }")
                    picker.setEnabled(False)
                    check.toggled.connect(
                        lambda checked, date=picker: date.setEnabled(not checked)
                    )
                    parts.addWidget(picker, 1)
                    parts.addWidget(check)
                    self.date_enabled[key] = check
                    layout.addRow(label, row)
                else:
                    layout.addRow(label, picker)
            elif field_type == "payment":
                field = QComboBox(self)
                field.setEditable(True)
                field.addItems(["", "เงินสด", "โอนเงิน", "บัตรเครดิต", "QR Code", "อื่นๆ"])
                field.setCurrentText("")
                self.widgets[key] = field
                layout.addRow(label, field)
            elif field_type == "notes":
                field = QTextEdit(self)
                field.setMaximumHeight(75)
                field.setPlaceholderText("รายละเอียดเพิ่มเติม (ถ้ามี)")
                self.widgets[key] = field
                layout.addRow(label, field)
            else:
                field = QLineEdit(self)
                field.setPlaceholderText(label)
                self.widgets[key] = field
                layout.addRow(label + (" *" if key in self.spec["required"] else ""), field)

    def reset(self, selected_date=None):
        selected_date = selected_date if isinstance(selected_date, QDate) and selected_date.isValid() else QDate.currentDate()
        for key, _, field_type in self.spec["fields"]:
            widget = self.widgets[key]
            if field_type in ("date", "date_optional"):
                widget.setDate(selected_date)
                if key in self.date_enabled:
                    self.date_enabled[key].setChecked(True)
            elif field_type == "notes":
                widget.clear()
            elif field_type == "payment":
                widget.setCurrentText("")
            else:
                widget.clear()

    def set_values(self, values):
        values = dict(values or {})
        for key, _, field_type in self.spec["fields"]:
            widget = self.widgets[key]
            value = str(values.get(key) or "")
            if field_type in ("date", "date_optional"):
                date = QDate.fromString(value, "yyyy-MM-dd")
                if key in self.date_enabled:
                    self.date_enabled[key].setChecked(not date.isValid())
                if date.isValid():
                    widget.setDate(date)
            elif field_type == "notes":
                widget.setPlainText(value)
            elif field_type == "payment":
                widget.setCurrentText(value)
            else:
                widget.setText(value)

    def values(self):
        result = {}
        for key, _, field_type in self.spec["fields"]:
            widget = self.widgets[key]
            if field_type in ("date", "date_optional"):
                result[key] = (
                    "" if key in self.date_enabled and self.date_enabled[key].isChecked()
                    else widget.date().toString("yyyy-MM-dd")
                )
            elif field_type == "notes":
                result[key] = widget.toPlainText().strip()
            elif field_type == "payment":
                result[key] = widget.currentText().strip()
            else:
                result[key] = widget.text().strip()
        return result
