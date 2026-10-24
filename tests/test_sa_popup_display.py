"""Presentation-only SA message filtering; imports no Qt or live service."""
import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "dailylog_notify.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
FUNCTION = next(
    node for node in TREE.body
    if isinstance(node, ast.FunctionDef)
    and node.name == "clean_sa_notification_message"
)
MODULE = ast.fix_missing_locations(ast.Module(body=[FUNCTION], type_ignores=[]))
SCOPE = {"re": re}
exec(compile(MODULE, "<display-cleaner>", "exec"), SCOPE)
clean = SCOPE["clean_sa_notification_message"]


class SaMessageCleanerTests(unittest.TestCase):
    def test_sa_reminder_hides_internal_values(self):
        original = (
            "เวลานัดหมาย 预约时间: 13:30\n"
            "วันที่ 日期: 2026-10-10\n"
            "Merged D: D89:D97\n"
            "รายละเอียดแจ้ง:\n"
            "B - เวลานัดหมาย 预约时间: 13:30\n"
            "C - ลำดับ 序号: 7\n"
            "E - ลูกค้า: ตัวอย่าง\n"
            "F - ทะเบียน: 6 ขอ 7577"
        )
        result = clean(original)
        self.assertNotIn("Merged D:", result)
        self.assertNotIn("ลำดับ 序号:", result)
        self.assertIn("เวลานัดหมาย 预约时间: 13:30", result)
        self.assertIn("F - ทะเบียน: 6 ขอ 7577", result)
        self.assertIn("E - ลูกค้า:", result)

    def test_date_label_hides_column_d_technical_name(self):
        message = "วันที่นัดหมาย (Column D): 2026-10-12\nเวลานัดหมาย: 13:30"
        clean_message = clean(message)
        self.assertIn("วันที่นัดหมาย: 2026-10-12", clean_message)
        self.assertIn("เวลานัดหมาย: 13:30", clean_message)
        self.assertNotIn("(Column D)", clean_message)

    def test_old_merged_date_label_is_simplified(self):
        result = clean(
            "D - วันที่นัดหมาย (Merged D): 2026-10-09 → 2026-10-10"
        )
        self.assertEqual(
            result, "D - วันที่นัดหมาย: 2026-10-09 → 2026-10-10"
        )

    def test_non_sa_source_not_modified_by_dispatch(self):
        self.assertIn('== "sa_sathorn"', SOURCE)
        self.assertIn("message = clean_sa_notification_message(message)", SOURCE)
        self.assertIn("if (\n            str(source_key or \"\").strip().lower()", SOURCE)

    def test_popup_closes_in_twenty_two_seconds(self):
        self.assertIn("22 * 1000", SOURCE)
        self.assertNotIn("ปิดอัตโนมัติใน 23 วินาที", SOURCE)
        self.assertNotIn("เลือกข้อความแล้ว Ctrl+C ได้", SOURCE)
        self.assertNotIn("ปิดอัตโนมัติใน 10 นาที", SOURCE)
        self.assertNotIn("ปิดอัตโนมัติใน 3 นาที", SOURCE)


    def test_x_is_connected_to_explicit_dismiss(self):
        self.assertIn(
            "close_button.clicked.connect(self.dismiss)",
            SOURCE,
        )
        self.assertIn("self._auto_close_timer.stop()", SOURCE)
        self.assertIn("self.reject()", SOURCE)

    def test_history_ui_filters_source_without_deleting_rows(self):
        self.assertIn("source_allowed=self._source_allowed", SOURCE)
        self.assertIn("or self.source_allowed(", SOURCE)
        self.assertIn("source_key=source_key", SOURCE)

    def test_compact_dark_popup_and_only_history_action(self):
        self.assertIn('close_button.setObjectName("notifyPopupCloseButton")', SOURCE)
        self.assertIn("background-color: #DC2626", SOURCE)
        self.assertNotIn('copy_button = QPushButton(', SOURCE)
        self.assertIn("def copy_all(self):", SOURCE)
        self.assertIn("self.setFixedSize(335, 160)", SOURCE)
        self.assertIn("self.setWindowOpacity(0.76)", SOURCE)
        self.assertIn("root.setContentsMargins(8, 3, 8, 5)", SOURCE)
        self.assertIn("title_label.setFixedHeight(18)", SOURCE)
        self.assertIn("title_font.setPixelSize(10)", SOURCE)
        self.assertIn("history_button.setFixedHeight(20)", SOURCE)
        self.assertIn("self.message_box.setMinimumHeight(64)", SOURCE)
        self.assertIn("close_button.setFixedSize(17, 17)", SOURCE)
        self.assertIn('history_button.setObjectName("notifyPopupHistoryButton")', SOURCE)
        self.assertIn('history_button = QPushButton("เปิดดูการแก้ไขตาราง")', SOURCE)


if __name__ == "__main__":
    unittest.main()
