import os
import requests
from PySide6.QtCore import QSettings

ORG = "MiniDailyLog"
APP = "DailyLogNotify"

class NotificationChannels:
    def __init__(self):
        self.settings = QSettings(ORG, APP)

    def line_enabled(self):
        return self.settings.value("line/enabled", False, type=bool)

    def set_line_enabled(self, enabled):
        self.settings.setValue("line/enabled", bool(enabled))

    def line_token(self):
        return str(self.settings.value("line/channel_access_token", "") or "").strip()

    def line_target(self):
        return str(self.settings.value("line/target_id", "") or "").strip()

    def save_line(self, enabled, token, target_id):
        self.settings.setValue("line/enabled", bool(enabled))
        self.settings.setValue("line/channel_access_token", token.strip())
        self.settings.setValue("line/target_id", target_id.strip())
        self.settings.sync()

    def send_line(self, message):
        if not self.line_enabled():
            return False, "LINE is disabled"
        token = self.line_token()
        target = self.line_target()
        if not token or not target:
            return False, "LINE token or target ID is missing"
        r = requests.post(
            "https://api.line.me/v2/bot/message/push",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"to": target, "messages": [{"type": "text", "text": str(message)[:5000]}]},
            timeout=(5, 15),
        )
        if not r.ok:
            return False, f"LINE HTTP {r.status_code}: {r.text[:300]}"
        return True, "LINE message sent"
