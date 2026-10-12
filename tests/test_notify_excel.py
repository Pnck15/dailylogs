"""XLSX export and safety, no Qt or third-party spreadsheet dependency."""
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from notify_excel import make_history_xlsx

S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


class HistoryExcelTests(unittest.TestCase):
    def test_valid_xlsx_preserves_bilingual_text_and_never_inserts_formulas(self):
        records = [
            {
                "created_at": "2026-10-12T14:32:00",
                "source": "SA Sathorn",
                "title": "แก้ไขข้อมูล วันที่ 日期",
                "message": "เวลา: 13:30\n=HYPERLINK(\"http://example.invalid\")\nVIN 漢字",
                "source_key": "sa_sathorn",
            },
            {
                "created_at": "2026-10-12T14:35:00",
                "source": "SA Sathorn",
                "title": "New row",
                "message": "หมายเหตุ: Testing & <tags>",
                "source_key": "sa_sathorn",
            },
        ]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history.xlsx"
            self.assertEqual(make_history_xlsx(path, records), 2)
            self.assertTrue(path.is_file())
            with ZipFile(path) as archive:
                self.assertIsNone(archive.testzip())
                self.assertIn("xl/styles.xml", archive.namelist())
                root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
                rows = root.findall(f".//{{{S}}}sheetData/{{{S}}}row")
                self.assertEqual(len(rows), 3)
                self.assertEqual(
                    [c.attrib.get("t") for row in rows for c in row],
                    ["inlineStr"] * 15,
                )
                self.assertFalse(root.findall(f".//{{{S}}}f"),
                                 "Spreadsheet must not evaluate Sheet-provided text as a formula")
                text = " ".join(
                    node.text or "" for node in root.findall(f".//{{{S}}}t")
                )
                self.assertIn("แก้ไขข้อมูล", text)
                self.assertIn("=HYPERLINK", text)
                self.assertIn("Testing & <tags>", text)
                self.assertEqual(
                    root.find(f".//{{{S}}}autoFilter").get("ref"), "A1:E3"
                )

    def test_empty_is_rejected_and_no_file_written(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "empty.xlsx"
            with self.assertRaises(ValueError):
                make_history_xlsx(path, [])
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
