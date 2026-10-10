from PySide6.QtCore import QObject, QRunnable, Signal, Slot, QThreadPool


class WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(str)


class Worker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.signals.finished.emit(result)
        except Exception as exc:
            self.signals.error.emit(str(exc))


def run_async(owner, fn, on_finished, on_error=None, *args, **kwargs):
    worker = Worker(fn, *args, **kwargs)
    if not hasattr(owner, "_workers"):
        owner._workers = []
    owner._workers.append(worker)

    def finished(result):
        try:
            on_finished(result)
        finally:
            if worker in owner._workers:
                owner._workers.remove(worker)

    worker.signals.finished.connect(finished)

    def failed(message):
        try:
            if on_error:
                on_error(message)
        finally:
            if worker in owner._workers:
                owner._workers.remove(worker)

    worker.signals.error.connect(failed)

    QThreadPool.globalInstance().start(worker)
    return worker
