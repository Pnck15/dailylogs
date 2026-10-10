"""Verify the published DailyLog release and hashes through public GitHub endpoints."""
import ast
import hashlib
import os
from pathlib import Path

import requests

REPO = "Pnck15/dailylogs"
root = Path(__file__).resolve().parents[1]
source = ast.parse((root / "main.py").read_text(encoding="utf-8"))
version = next(
    node.value.value
    for node in source.body
    if isinstance(node, ast.Assign)
    and any(isinstance(target, ast.Name) and target.id == "APP_VERSION" for target in node.targets)
)
tag = f"v{version}"
headers = {"Accept": "application/vnd.github+json", "User-Agent": "DailyLog-Release-Verify/1.0"}
token = os.getenv("GH_TOKEN", "").strip()
if token:
    headers["Authorization"] = f"Bearer {token}"

release_response = requests.get(
    f"https://api.github.com/repos/{REPO}/releases/tags/{tag}",
    headers=headers,
    timeout=(5, 20),
)
release_response.raise_for_status()
release = release_response.json()
assets = {item["name"]: item for item in release["assets"]}

manifest_response = requests.get(
    assets["version.json"]["browser_download_url"],
    headers={"User-Agent": headers["User-Agent"], "Cache-Control": "no-cache"},
    timeout=(5, 20),
)
manifest_response.raise_for_status()
manifest = manifest_response.json()

assert manifest["version"] == version
assert release["target_commitish"] == manifest["source_commit"], "Release source commit mismatch"

for name, field in [
    ("DailyLog.exe", "sha256"),
    ("DailyLogUpdater.exe", "updater_sha256"),
]:
    asset = assets[name]
    assert asset["state"] == "uploaded" and asset["size"] > 100 * 1024
    digest = asset.get("digest")
    if digest:
        assert digest == "sha256:" + manifest[field], f"Asset SHA256 mismatch: {name}"
    else:
        binary = requests.get(asset["browser_download_url"], timeout=(5, 60)).content
        assert hashlib.sha256(binary).hexdigest() == manifest[field]

print(f"Public DailyLog {version} release verified; executable hashes and source commit match.")
