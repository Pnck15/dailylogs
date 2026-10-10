"""SA status and merged-date regression tests, no GUI/network needed."""
import ast
import copy
import unittest
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_method(path, class_name, name):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    cls = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = copy.deepcopy(next(node for node in cls.body
                                if isinstance(node, ast.FunctionDef) and node.name == name))
    method.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    scope = {"datetime": datetime}
    exec(compile(module, str(path), "exec"), scope)
    return scope[name]


signature = load_method(
    "sale_api_monitor.py", "SaleAPIMonitor", "_row_data_signature"
)
update_button = load_method("main.py", "DailyLog", "update_sale_button")


class FakeButton:
    def __init__(self):
        self.text = ""
        self.tooltip = ""

    def setText(self, value):
        self.text = value

    def setToolTip(self, value):
        self.tooltip = value


class FakeWindow:
    update_sale_button = update_button

    def __init__(self):
        self.button = FakeButton()
        self.sale_last_success_at = {"SA": 0.0}
        self.sale_errors = {"SA": False}
        self.sale_enabled = {"SA": True}
        self._sale_busy = {"SA": False}
        self._sale_retry_waiting = {"SA": False}
        self.sale_api_urls = {"SA": "https://script.google.com/macros/s/example/exec"}
        self.sale_last_error = {"SA": ""}
        self.sale_last_elapsed = {"SA": 64.0}

    def _sale_button(self, branch):
        return self.button

    def _sale_title(self, branch):
        return "SA Sathorn"


class SAStatusTests(unittest.TestCase):
    def test_first_connection_is_yellow(self):
        window = FakeWindow()
        window._sale_busy["SA"] = True
        window.update_sale_button("SA")
        self.assertTrue(window.button.text.startswith("🟡"))

    def test_healthy_background_scan_stays_green(self):
        window = FakeWindow()
        window.sale_last_success_at["SA"] = datetime.now().timestamp()
        window._sale_busy["SA"] = True
        window.update_sale_button("SA")
        self.assertTrue(window.button.text.startswith("🟢"))
        self.assertIn("กำลังตรวจ", window.button.tooltip)

    def test_healthy_queue_wait_stays_green(self):
        window = FakeWindow()
        window.sale_last_success_at["SA"] = datetime.now().timestamp()
        window._sale_retry_waiting["SA"] = True
        window.update_sale_button("SA")
        self.assertTrue(window.button.text.startswith("🟢"))
        self.assertIn("รอคิว", window.button.tooltip)

    def test_stale_scan_wait_is_yellow(self):
        window = FakeWindow()
        window.sale_last_success_at["SA"] = (
            datetime.now() - timedelta(minutes=17)
        ).timestamp()
        window._sale_busy["SA"] = True
        window.update_sale_button("SA")
        self.assertTrue(window.button.text.startswith("🟡"))

    def test_actual_error_remains_red(self):
        window = FakeWindow()
        window.sale_last_success_at["SA"] = datetime.now().timestamp()
        window.sale_errors["SA"] = True
        window.sale_last_error["SA"] = "ReadTimeout"
        window.update_sale_button("SA")
        self.assertTrue(window.button.text.startswith("🔴"))
        self.assertIn("ReadTimeout", window.button.tooltip)


class SAMergedDateTests(unittest.TestCase):
    def make_row(self, date_key):
        return {
            "sheet": "10.2026",
            "row": 7,
            "appointment_date": date_key,
            "row_data": [
                {"column": "B", "header": "เวลานัดหมาย", "value": "09.00"},
                {"column": "C", "header": "ลำดับ", "value": "5"},
                # Physical D7 has no value; it inherits date from D3:D10.
                {"column": "D", "header": "วันที่", "value": ""},
                {"column": "E", "header": "ลูกค้า", "value": "ทดสอบ"},
            ],
        }

    def test_inherited_merged_d_change_is_detected(self):
        before = signature(self.make_row("2026-10-10"))
        after = signature(self.make_row("2026-10-11"))
        self.assertNotEqual(before, after)

    def test_identical_merged_group_no_false_edit(self):
        self.assertEqual(
            signature(self.make_row("2026-10-10")),
            signature(self.make_row("2026-10-10")),
        )

    def test_sale_rows_unchanged(self):
        row = {"row": 2, "row_data": [{"column": "D", "value": "A"}]}
        self.assertEqual(signature(row), signature(dict(row, appointment_date="X")))


if __name__ == "__main__":
    unittest.main()
