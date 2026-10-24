"""Pure offline validation of Google Viewer URL routing."""
import sys
import unittest
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from viewer_sources import (
    is_viewer_file_url, viewer_target, with_viewer_tab,
    make_viewer_gateway_url,
)


class ViewerSourceTests(unittest.TestCase):
    def test_google_sheet_gid(self):
        source="https://docs.google.com/spreadsheets/d/1aC1NFxBfqDg4zkC1-y-vDYmIUpqTqegb/edit?gid=1356814487#gid=1356814487"
        self.assertTrue(is_viewer_file_url(source))
        self.assertEqual(viewer_target(source)["gid"],"1356814487")
        result=make_viewer_gateway_url(
            "https://script.google.com/macros/s/abc123/exec?token=my_secret",source
        )
        params=parse_qs(urlsplit(result).query)
        self.assertEqual(params["token"],["my_secret"])
        self.assertEqual(params["id"],["1aC1NFxBfqDg4zkC1-y-vDYmIUpqTqegb"])
        self.assertEqual(params["gid"],["1356814487"])

    def test_xlsx_tab(self):
        url="https://docs.google.com/spreadsheets/d/1aC1NFxBfqDg4zkC1-y-vDYmIUpqTqegb/edit?gid=1947537691"
        target=viewer_target(with_viewer_tab(url,"04-红牌ชีตnew"))
        self.assertEqual(target["tab"],"04-红牌ชีตnew")

    def test_deny_untrusted_urls(self):
        gateway="https://script.google.com/macros/s/x/exec?token=secret"
        for url in (
            "https://example.com/spreadsheets/d/1aC1NFxBfqDg4zkC1-y-vDYmIUpqTqegb/edit",
            "https://docs.google.com.evil.example/spreadsheets/d/1aC1NFxBfqDg4zkC1-y-vDYmIUpqTqegb/edit",
            "https://docs.google.com/spreadsheets/d/NOT_VALID/edit",
        ):
            self.assertFalse(is_viewer_file_url(url))
            with self.assertRaises(ValueError):
                make_viewer_gateway_url(gateway,url)
        with self.assertRaises(ValueError):
            make_viewer_gateway_url("https://script.google.com/macros/s/x/exec","https://docs.google.com/spreadsheets/d/1aC1NFxBfqDg4zkC1-y-vDYmIUpqTqegb/edit")


if __name__=="__main__":
    unittest.main()
