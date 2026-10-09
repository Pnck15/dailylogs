"""Release discovery and verified downloads, independent of the Qt UI."""
import hashlib
import os
import re
import tempfile
from pathlib import Path

import requests

REPO = "Pnck15/dailylogs"
HEADERS = {"User-Agent": "DailyLogNotify-Updater", "Cache-Control": "no-cache"}


def version(value):
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(value)):
        raise ValueError("Invalid release version")
    return tuple(map(int, value.split(".")))


def fetch_update(current):
    response = requests.get(f"https://api.github.com/repos/{REPO}/releases?per_page=100",
                            headers=HEADERS, timeout=(5, 15))
    response.raise_for_status()
    candidates = []
    for release in response.json():
        tag = str(release.get("tag_name", ""))
        if release.get("draft") or release.get("prerelease"):
            continue
        if re.fullmatch(r"notify-v\d+\.\d+\.\d+", tag):
            candidates.append((version(tag[8:]), release))
    if not candidates:
        return {"available": False}
    _, release = max(candidates, key=lambda item: item[0])
    tag = release["tag_name"]
    prefix = f"https://github.com/{REPO}/releases/download/{tag}/"
    assets = {item["name"]: item for item in release.get("assets", [])}
    manifest_url = assets.get("notify-version.json", {}).get("browser_download_url")
    if manifest_url != prefix + "notify-version.json":
        raise ValueError("Release manifest missing or invalid")
    response = requests.get(manifest_url, headers=HEADERS, timeout=(5, 15))
    response.raise_for_status()
    data = response.json()
    latest = data.get("version", "")
    if latest != tag[8:]:
        raise ValueError("Release tag and manifest version differ")
    for url_key, hash_key, name in [
        ("download_url", "sha256", "DailyLogNotify.exe"),
        ("updater_download_url", "updater_sha256", "DailyLogUpdater.exe"),
    ]:
        # Older manifests do not describe the updater; keep them readable.
        if url_key == "updater_download_url" and not data.get(url_key):
            continue
        if data.get(url_key) != prefix + name or name not in assets:
            raise ValueError(f"Invalid release asset: {name}")
        if not re.fullmatch(r"[a-fA-F0-9]{64}", str(data.get(hash_key, ""))):
            raise ValueError(f"Missing SHA256: {name}")
    data.update(available=version(latest) > version(current), latest=latest)
    return data


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_verified(url, expected_hash, destination):
    """Replace the cached file only after a complete, verified PE download."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and file_hash(destination) == expected_hash.lower():
        return str(destination)
    fd, temporary = tempfile.mkstemp(prefix=".notify-download-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            with requests.get(url, headers=HEADERS, timeout=(10, 180), stream=True) as response:
                response.raise_for_status()
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        out.write(chunk)
        with open(temporary, "rb") as file:
            if file.read(2) != b"MZ":
                raise ValueError("Downloaded file is not a Windows executable")
        if file_hash(temporary) != expected_hash.lower():
            raise ValueError("Downloaded file SHA256 does not match")
        os.replace(temporary, destination)
        return str(destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def prepare_update(data, app_dir):
    """Keep the running app alive while fetching both required executables."""
    app_dir = Path(app_dir)
    updater = app_dir / "DailyLogUpdater.exe"
    if data.get("updater_download_url"):
        download_verified(data["updater_download_url"], data["updater_sha256"], updater)
    if data.get("available"):
        if not updater.is_file():
            raise FileNotFoundError("DailyLogUpdater.exe not found")
        data["prepared_file"] = download_verified(
            data["download_url"], data["sha256"], app_dir / ".notify-update" / "DailyLogNotify.exe")
    return data
