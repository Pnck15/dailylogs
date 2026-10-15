"""Durable, per-PC display retention for DailyLog Notification panels.

This module intentionally does NOT import CloudDB/SQLite or execute any SQL.
It hides event timestamps locally; Daily Logs and Central notification_events
remain untouched. Admin-only Central retention uses a separate explicit RPC.
"""
import json
from datetime import datetime, timedelta, timezone

SETTINGS_KEY = "notifications/locally_hidden_time_ranges"


def to_utc(value):
    """Return a UTC-aware timestamp. Naive values are this PC's local time."""
    if isinstance(value, datetime):
        timestamp = value
    else:
        try:
            timestamp = datetime.fromisoformat(
                str(value or "").strip().replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.astimezone()
    return timestamp.astimezone(timezone.utc)


def window_for(mode, days=7, now=None):
    """Make one frozen time window; later notifications remain visible."""
    end = to_utc(now or datetime.now(timezone.utc))
    if end is None:
        raise ValueError("วันเวลาที่เลือกล้างไม่ถูกต้อง")
    if mode == "all":
        return None, end
    try:
        days = int(days)
    except (ValueError, TypeError) as exc:
        raise ValueError("จำนวนวันไม่ถูกต้อง") from exc
    if not 1 <= days <= 3650:
        raise ValueError("จำนวนวันต้องอยู่ระหว่าง 1–3650")
    cutoff = end - timedelta(days=days)
    if mode == "recent":
        return cutoff, end
    if mode == "older":
        return None, cutoff
    raise ValueError("ประเภทการล้างไม่ถูกต้อง")


class LocalNotificationVisibility:
    """Remember timestamp windows hidden by this PC, across app restarts."""

    def __init__(self, settings):
        self.settings = settings
        self.windows = []
        try:
            raw = json.loads(str(settings.value(SETTINGS_KEY, "[]") or "[]"))
            if isinstance(raw, list):
                for item in raw:
                    if not isinstance(item, dict):
                        continue
                    start = to_utc(item.get("start")) if item.get("start") else None
                    end = to_utc(item.get("end"))
                    if end and (start is None or start < end):
                        self.windows.append((start, end))
        except (ValueError, TypeError):
            # Invalid settings should not silently hide unrelated records.
            self.windows = []

    def hide(self, mode, days=7, now=None):
        start, end = window_for(mode, days, now=now)
        self.windows.append((start, end))
        self.settings.setValue(
            SETTINGS_KEY,
            json.dumps(
                [
                    {
                        "start": start_time.isoformat() if start_time else None,
                        "end": end_time.isoformat(),
                    }
                    for start_time, end_time in self.windows
                ],
                ensure_ascii=False,
            ),
        )
        self.settings.sync()
        if self.settings.status() != self.settings.Status.NoError:
            raise OSError("ไม่สามารถบันทึกการตั้งค่าการล้างประวัติในเครื่องนี้ได้")
        return start, end

    def visible(self, date_time):
        stamp = to_utc(date_time)
        if stamp is None:
            return True
        return not any(
            (start is None or start <= stamp) and stamp < end
            for start, end in self.windows
        )

    def filter_rows(self, rows):
        return [
            item for item in (rows or [])
            if self.visible(
                item.get("created_at") if isinstance(item, dict)
                else getattr(item, "timestamp", None)
            )
        ]
