"""Verified standalone VATCalculator.exe updates from DailyLog GitHub releases.

Uses a separate vat_version within the main app release manifest; never
follows unrelated Notify releases, unknown domains, or unsigned asset paths.
"""
import re
from pathlib import Path
import requests
from notify_updates import download_verified

REPO = "Pnck15/dailylogs"
HEADERS = {"User-Agent": "DailyLog-VAT-Updater", "Cache-Control": "no-cache"}


def _version(value):
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", str(value or "")):
        raise ValueError("Invalid vat version")
    return tuple(int(s) for s in str(value).split("."))


def fetch_vat_update(current):
    response = requests.get(
        f"https://api.github.com/repos/{REPO}/releases?per_page=50",
        headers=HEADERS, timeout=(5, 18)
    )
    response.raise_for_status()
    candidates = []
    for item in response.json():
        if not isinstance(item, dict) or item.get("draft") or item.get("prerelease"):
            continue
        tag = str(item.get("tag_name") or "")
        if re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
            candidates.append(( _version(tag[1:]), item))
    if not candidates:
        return {"available": False}
    _, latest = max(candidates, key=lambda pair:pair[0])
    tag = latest["tag_name"]
    prefix = f"https://github.com/{REPO}/releases/download/{tag}/"
    assets = {a.get("name"):a for a in latest.get("assets",[]) if isinstance(a,dict)}
    manifest_asset = assets.get("version.json", {})
    if manifest_asset.get("browser_download_url") != prefix + "version.json":
        raise ValueError("GitHub main release manifest missing")
    manifest_response = requests.get(
        prefix + "version.json", headers=HEADERS, timeout=(5, 18)
    )
    manifest_response.raise_for_status()
    info = manifest_response.json()
    if str(info.get("version")) != tag[1:]:
        raise ValueError("Release main version mismatch")
    fv = str(info.get("vat_version") or "").strip()
    if not fv:
        # Pre-standalone main releases are intentionally not updatable.
        return {"available": False}
    for name,url_field,sha_field in (
        ("VATCalculator.exe","vat_download_url","vat_sha256"),
        ("DailyLogUpdater.exe","updater_download_url","updater_sha256"),
    ):
        asset = assets.get(name, {})
        url = prefix + name
        digest = str(info.get(sha_field) or "")
        if asset.get("browser_download_url") != url or info.get(url_field) != url:
            raise ValueError(f"Release asset URL invalid: {name}")
        if not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
            raise ValueError(f"SHA256 missing: {name}")
        if asset.get("digest") and str(asset["digest"]).lower() != "sha256:"+digest.lower():
            raise ValueError(f"GitHub asset digest mismatch: {name}")
    info["available"] = _version(fv) > _version(current)
    info["latest"] = fv
    return info


def prepare_vat_update(info, directory):
    """Stage verified updater and EXE while VATCalculator is still running."""
    if not info.get("available"):
        return info
    directory = Path(directory)
    updater = directory / "DailyLogUpdater.exe"
    download_verified(
        info["updater_download_url"],
        info["updater_sha256"], updater,
    )
    prepared = download_verified(
        info["vat_download_url"], info["vat_sha256"],
        directory / ".vat-update" / "VATCalculator.exe",
    )
    info["prepared_file"] = prepared
    return info
