"""History schema upgrade must never remove or rewrite existing records."""
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import notify_history


class HistoryMigrationTests(unittest.TestCase):
    def test_adds_source_key_without_deleting_old_records(self):
        with tempfile.TemporaryDirectory() as folder:
            db_path = Path(folder) / "notification_history.db"
            with closing(sqlite3.connect(db_path)) as db, db:
                db.execute(
                    "CREATE TABLE notifications("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "created_at TEXT NOT NULL,"
                    "source TEXT,"
                    "title TEXT NOT NULL,"
                    "message TEXT NOT NULL)"
                )
                db.execute(
                    "INSERT INTO notifications(created_at,source,title,message)"
                    " VALUES(?,?,?,?)",
                    (
                        "2026-10-10T13:00:00",
                        "Sale Deli Sathorn",
                        "Existing event",
                        "Original content must survive",
                    ),
                )

            with patch.object(notify_history, "app_data_dir", return_value=folder):
                history = notify_history.NotificationHistory()
                existing = history.all()
                self.assertEqual(len(existing), 1)
                self.assertEqual(existing[0]["message"], "Original content must survive")
                self.assertEqual(existing[0]["source_key"], "")

                history.add(
                    "SA Sathorn",
                    "New event",
                    "Accepted",
                    source_key="sa_sathorn",
                )
                saved = history.all()
                self.assertEqual(len(saved), 2)
                self.assertEqual(saved[0]["source_key"], "sa_sathorn")
                self.assertEqual(saved[1]["message"], "Original content must survive")

                # Migration must be idempotent after restarting the app.
                restarted = notify_history.NotificationHistory()
                self.assertEqual(len(restarted.all()), 2)
                self.assertEqual(restarted.all()[1]["source_key"], "")

    def test_new_database_supports_old_add_call(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(notify_history, "app_data_dir", return_value=folder):
                history = notify_history.NotificationHistory()
                history.add("Sale Deli Sathorn", "Legacy call", "message")
                result = history.recent()
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]["source_key"], "")
                self.assertEqual(result[0]["message"], "message")


if __name__ == "__main__":
    unittest.main()
