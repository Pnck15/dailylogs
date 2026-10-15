"""Offline Qt/Supabase regression for DailyLog JWT expiration.

No live Supabase credentials are read. No database, files, users, or Logs are
modified. Covers proactive refresh, precise PGRST303 retry, and safe non-retry
of ambiguous writes (network failures cannot be replayed automatically).
"""
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QCoreApplication
from cloud_db import CloudDB
from cloud_worker import _CloudWorker, is_expired_jwt_error


class FakeAPIError(Exception):
    def __init__(self, message, code):
        self.message = message
        self.code = code
        super().__init__(f"{{'message': '{message}', 'code': '{code}'}}")


class FakeAuth:
    def __init__(self, uid="test-user-id", expiration=3600):
        self.user = SimpleNamespace(id=uid)
        self.current = SimpleNamespace(
            user=self.user, access_token="offline-access",
            refresh_token="offline-refresh", expires_at=time.time() + expiration,
        )
        self.refresh_count = 0
        self.get_count = 0
        self.fail_refresh = None

    def get_session(self):
        self.get_count += 1
        return self.current

    def refresh_session(self):
        self.refresh_count += 1
        if self.fail_refresh is not None:
            raise self.fail_refresh
        self.current = SimpleNamespace(
            user=self.user,
            access_token=f"offline-refreshed-{self.refresh_count}",
            refresh_token=f"offline-rotated-{self.refresh_count}",
            expires_at=time.time() + 3600,
        )
        return SimpleNamespace(session=self.current)


def make_db(expiration=3600):
    db = CloudDB.__new__(CloudDB)
    auth = FakeAuth(expiration=expiration)
    db.client = SimpleNamespace(auth=auth)
    db.user = auth.user
    db.session = auth.current
    db.workspace_id = "offline-workspace"
    db.email = "example@invalid.test"
    db.username = "tester"
    return db, auth


def test_refresh_auth_session():
    db, auth = make_db()
    result = db.ensure_session_fresh()
    assert result is auth.current
    assert auth.refresh_count == 0, "Do not rotate healthy refresh tokens"
    assert db.session is auth.current

    db, auth = make_db(expiration=60)
    before = db.session
    result = db.ensure_session_fresh()
    assert auth.refresh_count == 1
    assert result is auth.current and db.session is result
    assert db.session is not before

    db.ensure_session_fresh(force=True)
    assert auth.refresh_count == 2

    db, auth = make_db(expiration=60)
    auth.fail_refresh = FakeAPIError("Invalid Refresh Token", "invalid_grant")
    try:
        db.ensure_session_fresh()
    except RuntimeError as error:
        assert "Login" in str(error)
    else:
        raise AssertionError("Invalid refresh must require manual login")
    assert auth.refresh_count == 1


class SimulatedDB:
    def __init__(self, failures=None):
        self.failures = list(failures or [])
        self.refresh_calls = []
        self.calls = 0
        self.rows = []

    def ensure_session_fresh(self, force=False):
        self.refresh_calls.append(bool(force))

    def add_log(self, log_date, log_time, title, description):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        self.rows.append((log_date, title, description))
        return {"id": 25}


def run_worker(db):
    worker = _CloudWorker()
    worker.db = db
    completed, rejected = [], []
    worker.result.connect(
        lambda request_id, operation, value: completed.append(
            (request_id, operation, value)
        )
    )
    worker.error.connect(
        lambda request_id, operation, error: rejected.append(
            (request_id, operation, error)
        )
    )
    worker.execute(4, "add_log", [
        "2026-10-15", "11:14:00", "รับรถ", "test description"
    ])
    return completed, rejected


def test_retry_exclusively_after_confirmed_jwt_expiration():
    error = FakeAPIError("JWT expired", "PGRST303")
    assert is_expired_jwt_error(error)
    assert not is_expired_jwt_error(
        FakeAPIError("JWT issued at future", "PGRST303")
    )
    assert not is_expired_jwt_error(
        FakeAPIError("PostgREST is busy", "PGRST303")
    )

    db = SimulatedDB([error])
    success, rejected = run_worker(db)
    assert not rejected
    assert len(success) == 1
    assert db.refresh_calls == [False, True]
    assert db.calls == 2
    assert len(db.rows) == 1, "JWT denial must never double-insert Daily Logs"

    # No replay when the server might already have accepted an INSERT.
    for failure in [
        TimeoutError("ReadTimeout after insert"),
        OSError("Network disconnected"),
        FakeAPIError("JWT issued at future", "PGRST303"),
        FakeAPIError("permission denied for logs", "42501"),
    ]:
        db = SimulatedDB([failure])
        success, rejected = run_worker(db)
        assert not success
        assert len(rejected) == 1
        assert db.calls == 1, "Ambiguous writes MUST NOT be retried"
        assert db.refresh_calls == [False]
        assert db.rows == []


def test_refreshed_session_failed_does_not_repeat_write():
    class CannotRefresh(SimulatedDB):
        def ensure_session_fresh(self, force=False):
            super().ensure_session_fresh(force)
            if force:
                raise RuntimeError("Refresh unavailable, Login again")

    db = CannotRefresh([FakeAPIError("JWT expired", "PGRST303")])
    success, rejected = run_worker(db)
    assert success == []
    assert len(rejected) == 1
    assert db.calls == 1
    assert db.refresh_calls == [False, True]


if __name__ == "__main__":
    application = QCoreApplication.instance() or QCoreApplication(sys.argv)
    test_refresh_auth_session()
    test_retry_exclusively_after_confirmed_jwt_expiration()
    test_refreshed_session_failed_does_not_repeat_write()
    print("PASS: JWT proactive refresh, PGRST303 one-time retry, no duplicate/ambiguous Cloud Log writes.")
