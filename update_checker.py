import json
import os
import re
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

            # DailyLog and DailyLogNotify share one GitHub Releases page.
            # GitHub's /releases/latest endpoint may therefore point to a
            # notify-v... release which has no version.json for DailyLog.
            # Resolve the newest main-app vX.Y.Z release explicitly.
            match = re.match(
                r"^https://github\.com/([^/]+)/([^/]+)/releases/latest/download/version\.json$",
                manifest_url,
                flags=re.IGNORECASE,
            )

            if match:
                owner, repo = match.groups()

                releases_response = requests.get(
                    (
                        f"https://api.github.com/repos/"
                        f"{owner}/{repo}/releases?per_page=30"
                    ),
                    timeout=(5, 15),
                    headers={
                        "Accept": "application/vnd.github+json",
                        "Cache-Control": "no-cache",
                        "User-Agent": "DailyLog-Updater",
                    },
                )
                releases_response.raise_for_status()

                releases = releases_response.json()

                if isinstance(releases, list):
                    main_release = next(
                        (
                            item
                            for item in releases
                            if isinstance(item, dict)
                            and not item.get("draft")
                            and not item.get("prerelease")
                            and re.match(
                                r"^v\d+(?:\.\d+){1,3}$",
                                str(item.get("tag_name", "")),
                                flags=re.IGNORECASE,
                            )
                        ),
                        None,
                    )

                    if main_release:
                        asset = next(
                            (
                                item
                                for item in main_release.get("assets", [])
                                if isinstance(item, dict)
                                and item.get("name") == "version.json"
                            ),
                            None,
                        )

                        if asset:
                            asset_url = str(
                                asset.get("browser_download_url", "")
                                or ""
                            ).strip()

                            if asset_url:
                                manifest_response = requests.get(
                                    asset_url,
                                    timeout=(5, 15),
                                    headers={
                                        "Cache-Control": "no-cache",
                                        "User-Agent": "DailyLog-Updater",
                                    },
                                )
                                manifest_response.raise_for_status()
                                return manifest_response.json()

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