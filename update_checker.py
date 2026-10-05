import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests


class UpdateChecker:
    """Check the public release manifest and report a newer DailyLog version."""

    def __init__(self, current_version: str):
        self.current_version = str(current_version or "0.0.0").strip()

        # Folder where DailyLog.exe is located.
        self.app_dir = Path(
            sys.executable if getattr(sys, "frozen", False) else __file__
        ).resolve().parent

        # Folder containing bundled PyInstaller resources.
        if getattr(sys, "frozen", False):
            self.resource_dir = Path(sys._MEIPASS)
        else:
            self.resource_dir = Path(__file__).resolve().parent

    @staticmethod
    def _version_tuple(value: str):
        parts = []

        for item in str(value or "0").strip().lstrip("vV").split("."):
            digits = "".join(ch for ch in item if ch.isdigit())
            parts.append(int(digits or 0))

        while len(parts) < 3:
            parts.append(0)

        return tuple(parts[:3])

    def _load_config(self):
        path = self.resource_dir / "update_config.json"

        if not path.exists():
            return {}

        with path.open("r", encoding="utf-8-sig") as file:
            return json.load(file)

    def _load_manifest(self):
        config = self._load_config()

        manifest_url = os.getenv(
            "DAILYLOG_UPDATE_MANIFEST_URL",
            str(config.get("manifest_url", "")),
        ).strip()

        if manifest_url:
            parsed = urlparse(manifest_url)

            if parsed.scheme not in {"http", "https"}:
                raise ValueError(
                    "manifest_url ต้องเป็น http:// หรือ https://"
                )

            response = requests.get(
                manifest_url,
                timeout=(5, 15),
                headers={
                    "Cache-Control": "no-cache",
                    "User-Agent": "DailyLog-Updater",
                },
            )

            response.raise_for_status()

            return response.json()

        # Local fallback manifest.
        local_manifest = self.resource_dir / "update_manifest.json"

        if not local_manifest.exists():
            return {}

        with local_manifest.open("r", encoding="utf-8-sig") as file:
            return json.load(file)

    def check(self):
        manifest = self._load_manifest()

        latest = str(manifest.get("version", "")).strip()

        if not latest:
            return {"available": False}

        return {
            "available": (
                self._version_tuple(latest)
                > self._version_tuple(self.current_version)
            ),
            "current_version": self.current_version,
            "latest_version": latest,
            "download_url": str(
                manifest.get("download_url", "")
            ).strip(),
            "sha256": str(
                manifest.get("sha256", "")
            ).strip().lower(),
            "release_notes": manifest.get("release_notes") or [],
            "published_at": str(
                manifest.get("published_at", "")
            ).strip(),
        }