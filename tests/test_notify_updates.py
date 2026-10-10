import ast
import hashlib
import logging
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

try:
    import requests
except ImportError:
    sys.modules["requests"] = types.SimpleNamespace(get=Mock())

import notify_updates as updates
import updater

root = Path(__file__).resolve().parents[1]
source = ast.parse((root / "dailylog_notify.py").read_text(encoding="utf-8"))
CURRENT_VERSION = next(
    node.value.value
    for node in source.body
    if isinstance(node, ast.Assign)
    and any(isinstance(target, ast.Name) and target.id == "APP_VERSION" for target in node.targets)
)

PE = b"MZ" + b"x" * (110 * 1024)
HASH = hashlib.sha256(PE).hexdigest()
PREFIX = f"https://github.com/Pnck15/dailylogs/releases/download/notify-v{CURRENT_VERSION}/"


def response(data=None, payload=PE):
    result = Mock()
    result.json.return_value = data
    result.iter_content.return_value = [payload]
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    return result


def release(tag=None, **kwargs):
    tag = tag or f"notify-v{CURRENT_VERSION}"
    return dict(tag_name=tag, assets=[
        {"name": name, "browser_download_url": PREFIX + name}
        for name in ["notify-version.json", "DailyLogNotify.exe", "DailyLogUpdater.exe"]
    ], **kwargs)


def manifest():
    return dict(version=CURRENT_VERSION, download_url=PREFIX + "DailyLogNotify.exe", sha256=HASH,
                updater_download_url=PREFIX + "DailyLogUpdater.exe", updater_sha256=HASH)


class ReleaseTests(unittest.TestCase):
    def test_selects_highest_stable_version_among_mixed_releases(self):
        releases = [release("notify-v1.4.0"), release("v9.0.0"),
                    release("notify-v8.0.0", prerelease=True),
                    release("notify-v9.0.0", draft=True), release()]
        with patch.object(updates.requests, "get", side_effect=[response(releases), response(manifest())]):
            self.assertTrue(updates.fetch_update("1.5.0")["available"])

    def test_equal_version_still_describes_updater_repair(self):
        with patch.object(updates.requests, "get", side_effect=[response([release()]), response(manifest())]):
            result = updates.fetch_update(CURRENT_VERSION)
        self.assertFalse(result["available"])
        self.assertIn("updater_sha256", result)

    def test_rejects_wrong_tag_hash_and_asset_url(self):
        for field, value in [("version", "99.0.0"), ("sha256", ""),
                             ("download_url", "https://example.com/app.exe")]:
            data = manifest()
            data[field] = value
            with self.subTest(field=field), patch.object(updates.requests, "get",
                    side_effect=[response([release()]), response(data)]):
                with self.assertRaises(ValueError):
                    updates.fetch_update("1.5.0")

    def test_bad_download_does_not_replace_existing_helper(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "DailyLogUpdater.exe"
            path.write_bytes(b"old helper")
            with patch.object(updates.requests, "get", return_value=response(payload=b"MZwrong")):
                with self.assertRaises(ValueError):
                    updates.download_verified(PREFIX + path.name, HASH, path)
            self.assertEqual(path.read_bytes(), b"old helper")
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_downloads_helper_and_prepares_exe_before_handoff(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(updates.requests, "get",
                side_effect=[response(), response()]):
            data = manifest()
            data["available"] = True
            result = updates.prepare_update(data, folder)
            self.assertEqual(Path(result["prepared_file"]).read_bytes(), PE)
            self.assertEqual((Path(folder) / "DailyLogUpdater.exe").read_bytes(), PE)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.target = (Path(self.folder.name) / "DailyLogNotify.exe").resolve()
        self.target.write_bytes(b"MZold")
        self.wait = patch.object(updater, "wait_for_process").start()
        self.launch = patch.object(updater.subprocess, "Popen").start()
        self.addCleanup(patch.stopall)
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    def test_network_failure_restarts_old_app_with_startup_argument(self):
        with patch.object(updater.requests, "get", side_effect=OSError("offline")):
            self.assertEqual(updater.install_update(123, self.target, PREFIX + self.target.name,
                                                   HASH, ["--startup"]), 5)
        self.assertEqual(self.target.read_bytes(), b"MZold")
        self.launch.assert_called_once_with([str(self.target), "--startup"], close_fds=True)

    def test_bad_hash_preserves_and_restarts_previous_app(self):
        with patch.object(updater.requests, "get", return_value=response()):
            self.assertEqual(updater.install_update(123, self.target, PREFIX + self.target.name,
                                                   "0" * 64), 5)
        self.assertEqual(self.target.read_bytes(), b"MZold")
        self.launch.assert_called_once()

    def test_installs_verified_prepared_file_without_network(self):
        prepared = Path(self.folder.name) / "prepared.exe"
        prepared.write_bytes(PE)
        with patch.object(updater.requests, "get") as get:
            self.assertEqual(updater.install_update(123, self.target, str(prepared), HASH), 0)
            get.assert_not_called()
        self.assertEqual(self.target.read_bytes(), PE)
        self.assertEqual(self.target.with_suffix(".old.exe").read_bytes(), b"MZold")

    def test_failed_new_exe_launch_restores_previous_version(self):
        self.launch.side_effect = [OSError("cannot start"), Mock()]
        with patch.object(updater.requests, "get", return_value=response()):
            self.assertEqual(updater.install_update(123, self.target, PREFIX + self.target.name, HASH), 5)
        self.assertEqual(self.target.read_bytes(), b"MZold")
        self.assertEqual(self.launch.call_count, 2)

    def test_parent_timeout_keeps_running_app_untouched(self):
        self.wait.side_effect = TimeoutError()
        self.assertEqual(updater.install_update(123, self.target, PREFIX + self.target.name, HASH), 7)
        self.launch.assert_not_called()
        self.assertEqual(self.target.read_bytes(), b"MZold")


if __name__ == "__main__":
    unittest.main()
