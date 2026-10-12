import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

def app_data_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "MiniDailyLog", "DailyLogNotify")
    os.makedirs(path, exist_ok=True)
    return path

class NotificationHistory:
    def __init__(self):
        self.path = os.path.join(app_data_dir(), "notification_history.db")
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS notifications(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                source TEXT,
                title TEXT NOT NULL,
                message TEXT NOT NULL
            )""")
            # Additive migration: existing history remains untouched.
            columns = {
                item[1]
                for item in db.execute("PRAGMA table_info(notifications)")
            }
            if "source_key" not in columns:
                db.execute(
                    "ALTER TABLE notifications "
                    "ADD COLUMN source_key TEXT NOT NULL DEFAULT ''"
                )

    def add(self, source, title, message, source_key="", event_created_at=""):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "INSERT INTO notifications("
                "created_at,source,title,message,source_key"
                ") VALUES(?,?,?,?,?)",
                (
                    str(event_created_at or "").strip()
                    or datetime.now().isoformat(timespec="seconds"),
                    source,
                    title,
                    message,
                    str(source_key or "").strip(),
                ),
            )

    def recent(self, limit=200):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.row_factory = sqlite3.Row

            sql = (
                "SELECT id, created_at, source, title, message, source_key "
                "FROM notifications "
                "ORDER BY id DESC"
            )

            if limit is None:
                rows = db.execute(
                    sql
                ).fetchall()
            else:
                rows = db.execute(
                    sql + " LIMIT ?",
                    (int(limit),),
                ).fetchall()

            return [
                dict(row)
                for row in rows
            ]

    def all(self):
        return self.recent(
            limit=None
        )

    def clear_all(self):
        """Delete this PC's local history only, after UI confirmation.

        Never unlink the SQLite file or touch Central/Supabase history.
        """
        with closing(sqlite3.connect(self.path)) as db, db:
            cursor = db.execute("DELETE FROM notifications")
            return max(cursor.rowcount, 0)


    @staticmethod
    def _event_time(value):
        """Old rows use PC-local Bangkok time; new rows retain UTC event time."""
        from datetime import datetime, timedelta, timezone
        bangkok = timezone(timedelta(hours=7))
        try:
            stamp = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except ValueError:
            return None
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=bangkok)
        return stamp.astimezone(timezone.utc)

    def clear_period(self, start_at=None, end_at=None):
        """Delete events in [start,end), never touches the Central database.

        Rows added by new EXEs use original server created_at, while legacy
        rows use their local saved timestamp in Thailand.
        """
        from datetime import datetime, timezone
        start = self._event_time(start_at) if start_at else None
        end = self._event_time(end_at) if end_at else datetime.now(timezone.utc)
        if end is None or (start is not None and start >= end):
            raise ValueError("ช่วงเวลาที่ต้องการล้างไม่ถูกต้อง")
        with closing(sqlite3.connect(self.path)) as db, db:
            matches = []
            for entry_id, stamp in db.execute(
                "SELECT id, created_at FROM notifications"
            ):
                event_time = self._event_time(stamp)
                if event_time is None:
                    # Conservative: skip unparseable timestamps except all.
                    if start is None:
                        matches.append((entry_id,))
                    continue
                if event_time < end and (start is None or event_time >= start):
                    matches.append((entry_id,))
            if matches:
                db.executemany("DELETE FROM notifications WHERE id=?", matches)
            return len(matches)
