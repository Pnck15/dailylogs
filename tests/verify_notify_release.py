"""Verify the published files through the same public endpoint clients use."""
import ast
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
import requests
from notify_updates import fetch_update, REPO, HEADERS

source = ast.parse((root / "dailylog_notify.py").read_text(encoding="utf-8"))
current = next(node.value.value for node in source.body if isinstance(node, ast.Assign)
               and any(isinstance(target, ast.Name) and target.id == "APP_VERSION" for target in node.targets))
data = fetch_update("0.0.0")
assert data["available"] and data["latest"] == current, "Published version does not match the app"
response = requests.get(f"https://api.github.com/repos/{REPO}/releases/tags/notify-v{current}",
                        headers=HEADERS, timeout=(5, 15))
response.raise_for_status()
release = response.json()
assert not release["draft"] and not release["prerelease"]
assert release["target_commitish"] == data["source_commit"], "Release source commit mismatch"
assets = {item["name"]: item for item in release["assets"]}
for name, field in [("DailyLogNotify.exe", "sha256"), ("DailyLogUpdater.exe", "updater_sha256")]:
    asset = assets[name]
    assert asset["state"] == "uploaded" and asset["size"] > 100 * 1024
    assert asset["digest"] == "sha256:" + data[field], f"Asset SHA256 mismatch: {name}"
print(f"Public Notify {current} release discovered; both executable hashes match the manifest.")
