"""Offline regression: a successful Notify update must reopen visibly."""
import ast
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/"dailylog_notify.py").read_text(encoding="utf-8")

class NotifyRelaunchTests(unittest.TestCase):
    def test_visible_after_update_autologin_and_recovery(self):
        ast.parse(SOURCE)
        self.assertIn('args.append("--after-update")',SOURCE)
        self.assertIn('if "--startup" not in sys.argv:',SOURCE)
        self.assertIn('self.receiver.login_saved()',SOURCE)
        self.assertIn('self.ensure_recovery_task()',SOURCE)
        self.assertIn('"DailyLogNotify-Recovery"',SOURCE)
        self.assertIn('"MINUTE", "/MO", "5"',SOURCE)
        self.assertIn('Qt.WidgetAttribute.WA_QuitOnClose, False',SOURCE)

if __name__=="__main__":
    unittest.main()
