import os
import sqlite3
from datetime import datetime

def app_data_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "MiniDailyLog", "DailyLogNotify")
    os.makedirs(path, exist_ok=True)
    return path

class NotificationHistory:
    def __init__(self):
        self.path = os.path.join(app_data_dir(), "notification_history.db")
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS notifications(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                source TEXT,
                title TEXT NOT NULL,
                message TEXT NOT NULL
            )""")

    def add(self, source, title, message):
        with sqlite3.connect(self.path) as db:
            db.execute(
                "INSERT INTO notifications(created_at,source,title,message) VALUES(?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"), source, title, message),
            )

    def recent(self, limit=200):
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row

            sql = (
                "SELECT id, created_at, source, title, message "
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
