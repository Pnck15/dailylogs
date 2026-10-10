"""Editable red-plate forms stored safely in the existing logs.description text.

No schema migration: logs already supports title + description. The first line
is a human-readable form identifier; all fields remain searchable and editable.
"""
from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox, QDateEdit, QFormLayout, QLabel, QLineEdit, QTextEdit, QWidget,
)

RED_PLATE_HEADER = "แบบฟอร์ม: ป้ายแดง"
RED_PLATE_FIELDS = (
    ("customer", "ชื่อลูกค้า"),
    ("vin", "เลข VIN"),
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
    for key, label in RED_PLATE_FIELDS[:3]:
        if not normalized[key]:
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
        form = QFormLayout(self)
        form.setContentsMargins(2, 2, 2, 2)
        self.customer = QLineEdit()
        self.customer.setPlaceholderText("ชื่อ - นามสกุลลูกค้า")
        self.vin = QLineEdit()
        self.vin.setPlaceholderText("เลขตัวถัง / VIN")
        self.received_date = QDateEdit()
        self.received_date.setCalendarPopup(True)
        self.received_date.setDisplayFormat("dd/MM/yyyy")
        self.received_date.setDate(QDate.currentDate())
        self.not_returned = QCheckBox("ยังไม่คืนป้ายแดง")
        self.not_returned.setChecked(True)
        self.returned_date = QDateEdit()
        self.returned_date.setDisplayFormat("dd/MM/yyyy")
        self.returned_date.setCalendarPopup(True)
        self.returned_date.setDate(QDate.currentDate())
        self.returned_date.setEnabled(False)
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
