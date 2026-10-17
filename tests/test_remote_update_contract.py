"""Offline contracts for targeted admin Notify update and GAS status fallback.

No credentials, network, or database mutations. CI also runs live PySide6
smoke tests on Windows after compiling the executables.
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


class ForceUpdateContractTests(unittest.TestCase):
    def test_desktop_sources_parse(self):
        for path in ("main.py", "cloud_db.py", "notify_receiver.py",
                     "dailylog_notify.py", "sale_api_monitor.py"):
            with self.subTest(path=path):
                ast.parse(read(path), filename=path)

    def test_admin_only_session_target(self):
        main = read("main.py")
        cloud = read("cloud_db.py")
        self.assertIn("notifyForceUpdateSelected", main)
        self.assertIn("request_notify_force_update", cloud)
        self.assertIn('"admin"', cloud)
        self.assertIn("get_notify_force_update_status", cloud)
        self.assertIn('row.get("online")', main)
        self.assertIn('row.get("updater_ready")', main)

    def test_device_claim_and_throttle_bypass(self):
        receiver = read("notify_receiver.py")
        notify = read("dailylog_notify.py")
        self.assertIn("claim_notify_force_update", receiver)
        self.assertIn("force_update_requested.emit", receiver)
        self.assertIn("report_notify_force_update", receiver)
        self.assertIn("self.check_for_updates(force=True, request_id=request_id)", notify)
        self.assertIn("not manual and not force", notify)
        self.assertIn("self._pending_force_update_request", notify)
        self.assertIn('"no_update"', notify)
        self.assertIn('"updating"', notify)

    def test_redplate_status_not_ping(self):
        monitor = read("sale_api_monitor.py")
        worker = read("supabase/functions/dailylog-monitor-worker/index.ts")
        self.assertIn('"Unsupported action" in message', monitor)
        self.assertIn('"status", read_timeout=15', monitor)
        self.assertIn("showRedPlateApiKey()", monitor)
        self.assertIn("red_plate_cursor", worker)
        self.assertIn("payload.has_more === true", worker)
        self.assertIn("red-plate-seq", worker)


if __name__ == "__main__":
    unittest.main()
