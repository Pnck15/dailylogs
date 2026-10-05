from PySide6.QtCore import QObject, QThread, Signal, Slot

from cloud_db import CloudDB


class _CloudWorker(QObject):
    result = Signal(int, str, object)
    error = Signal(int, str, str)

    def __init__(self):
        super().__init__()
        self.db = None

    def _ensure_db(self):
        if self.db is None:
            self.db = CloudDB()
        return self.db

    @Slot(int, str, object)
    def execute(self, request_id, operation, args):
        try:
            db = self._ensure_db()
            args = args or []
            value = getattr(db, operation)(*args)
            self.result.emit(request_id, operation, value)
        except Exception as exc:
            self.error.emit(request_id, operation, str(exc))


class CloudService(QObject):
    """Serialize every Supabase operation on one dedicated worker thread."""

    request = Signal(int, str, object)
    result = Signal(int, str, object)
    error = Signal(int, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._next_id = 0
        self._thread = QThread(self)
        self._worker = _CloudWorker()
        self._worker.moveToThread(self._thread)
        self.request.connect(self._worker.execute)
        self._worker.result.connect(self.result)
        self._worker.error.connect(self.error)
        self._thread.start()

    def call(self, operation, *args):
        self._next_id += 1
        request_id = self._next_id
        self.request.emit(request_id, operation, list(args))
        return request_id

    def login(self, email, password):
        return self.call("login", email, password)

    def get_log_dates(self):
        return self.call("get_log_dates")

    def get_logs_for_date(self, log_date):
        return self.call("get_logs_for_date", log_date)

    def search_logs(self, keyword):
        return self.call("search_logs", keyword)

    def get_log(self, log_id):
        return self.call("get_log", log_id)

    def add_log(self, log_date, log_time, title, description):
        return self.call("add_log", log_date, log_time, title, description)

    def update_log(self, log_id, title, description):
        return self.call("update_log", log_id, title, description)

    def delete_log(self, log_id):
        return self.call("delete_log", log_id)

    def stop(self):
        if self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(3000)
