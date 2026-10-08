"""Deprecated compatibility shim.

DailyLogNotify no longer polls Google Apps Script directly.
The employee receiver uses notify_receiver.CentralNotifyReceiver instead.

This file intentionally contains no GAS URL handling and no HTTP requests.
"""
from PySide6.QtCore import QObject, Signal


class NotifyMonitorEngine(QObject):
    """Legacy API surface kept only to avoid import crashes in old callers."""

    event = Signal(str, str, str)
    summary_changed = Signal(int, int, int)
    status_changed = Signal(str)

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)
        self.settings = settings

    def start(self):
        self.status_changed.emit(
            "Direct GAS monitor disabled — use CentralNotifyReceiver"
        )

    def reload_urls(self):
        return None

    def poll_all(self, initial=False):
        return None

    def stop(self):
        return None
