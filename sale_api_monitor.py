"""Client for Sale Delivery row feeds and SA change-monitor feeds."""
from datetime import date, datetime
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import json
import re
import requests


_THAI_MONTHS = {
    "ม.ค.": 1, "มกราคม": 1,
    "ก.พ.": 2, "กุมภาพันธ์": 2,
    "มี.ค.": 3, "มีนาคม": 3,
    "เม.ย.": 4, "เมษายน": 4,
    "พ.ค.": 5, "พฤษภาคม": 5,
    "มิ.ย.": 6, "มิถุนายน": 6,
    "ก.ค.": 7, "กรกฎาคม": 7,
    "ส.ค.": 8, "สิงหาคม": 8,
    "ก.ย.": 9, "กันยายน": 9,
    "ต.ค.": 10, "ตุลาคม": 10,
    "พ.ย.": 11, "พฤศจิกายน": 11,
    "ธ.ค.": 12, "ธันวาคม": 12,
}


def _parse_date(value):
    """Parse common Google Sheets display-date formats to a date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text in ("-", "—"):
        return None

    # ISO and common numeric formats.
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%m/%d/%Y", "%d-%m-%Y", "%d-%m-%y"):
        try:
            parsed = datetime.strptime(text[:10], fmt).date()
            if parsed.year > 2400:
                parsed = parsed.replace(year=parsed.year - 543)
            return parsed
        except ValueError:
            pass

    # Thai month names, e.g. 3 ต.ค. 2569 or 3 ตุลาคม 2569.
    normalized = re.sub(r"\s+", " ", text)
    for month_name, month_number in _THAI_MONTHS.items():
        if month_name in normalized:
            match = re.search(r"(\d{1,2})\s+" + re.escape(month_name) + r"\s+(\d{2,4})", normalized)
            if match:
                day, year = int(match.group(1)), int(match.group(2))
                if year < 100:
                    year += 2000
                if year > 2400:
                    year -= 543
                try:
                    return date(year, month_number, day)
                except ValueError:
                    return None

    # Date-time display values where the date is the leading portion.
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt).date()
            if parsed.year > 2400:
                parsed = parsed.replace(year=parsed.year - 543)
            return parsed
        except ValueError:
            pass
    return None


class SaleAPIMonitor:
    """Supports two GAS response types:

    * Sale Delivery: {rows:[{row, model, vin, customer, sale, pay_day, delivery_date}]}
    * Structured GAS: {changes:[{type,sheet,row,customer,model,changes,today_fields,row_data}]}
    """
    def __init__(self, url, timeout=300):
        self.url = self._normalize_url(url)
        self.timeout = timeout
        self.last_changes = []
        self.last_payload = {}
        self.latest_rows = []
        self._delivery_snapshot = None

    @staticmethod
    def _normalize_url(url):
        text = str(url or "").strip()
        # Accept URLs pasted from Markdown or copied with surrounding < >.
        if text.startswith("[") and "](" in text and text.endswith(")"):
            text = text.split("](", 1)[1][:-1].strip()
        text = text.strip("<> ").replace("https:https://", "https://", 1)
        if not text:
            return ""
        parts = urlsplit(text)
        if parts.scheme not in ("http", "https"):
            raise ValueError("Apps Script URL ต้องขึ้นต้นด้วย https://")
        if parts.netloc != "script.google.com":
            raise ValueError("URL ต้องเป็น Google Apps Script Web App (script.google.com)")
        if not parts.path.rstrip("/").endswith("/exec"):
            raise ValueError("Apps Script Web App URL ต้องลงท้ายด้วย /exec")
        return text

    def _action_url(self):
        if not self.url:
            raise ValueError("ไม่ได้กำหนด Apps Script Web App URL")
        parts = urlsplit(self.url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        # Sale Delivery GAS ignores this parameter; SA GAS requires it.
        query["action"] = "changes"
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    def check(self, initial=False):
        url = self._action_url()
        try:
            response = requests.get(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "DailyLog-Notifier/1.2",
                    "Cache-Control": "no-cache",
                },
                timeout=(10, self.timeout),
                allow_redirects=True,
            )
        except requests.exceptions.ConnectTimeout as exc:
            raise RuntimeError(
                "เชื่อมต่อ Google Apps Script ไม่สำเร็จ: connect timeout"
            ) from exc
        except requests.exceptions.ReadTimeout as exc:
            raise RuntimeError(
                f"Google Apps Script ยังไม่ตอบกลับภายใน {self.timeout} วินาที"
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(
                f"เรียก Apps Script ไม่สำเร็จ: {exc}"
            ) from exc

        status = response.status_code
        raw = response.content.decode("utf-8-sig", errors="replace")

        if status < 200 or status >= 300:
            preview = raw[:300].replace("\n", " ")
            raise RuntimeError(
                f"Apps Script ตอบกลับ HTTP {status}: {preview}"
            )

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            preview = raw[:400].replace("\n", " ")
            lowered = preview.lower()
            if "<html" in lowered or "<!doctype" in lowered:
                raise RuntimeError(
                    "Apps Script Web App ตอบกลับเป็นหน้า HTML แทน JSON "
                    "(ตรวจ Deployment/สิทธิ์การเข้าถึง และต้องใช้ URL /exec)"
                ) from exc
            raise RuntimeError(f"คำตอบไม่ใช่ JSON: {preview}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("รูปแบบคำตอบ API ไม่ถูกต้อง: ต้องเป็น JSON object")
        if payload.get("success") is False or payload.get("ok") is False:
            raise RuntimeError(str(payload.get("message") or payload.get("error") or "API แจ้งว่าไม่สำเร็จ"))

        self.last_payload = payload
        # The Sale Delivery GAS returns the same records in rows and data.
        rows = payload.get("rows")
        if not isinstance(rows, list):
            rows = payload.get("data")
        if isinstance(rows, list):
            normalized = []
            for index, item in enumerate(rows, start=2):
                if not isinstance(item, dict):
                    continue
                values = dict(item)
                row_number = values.get("row", index)
                values["row"] = row_number
                normalized.append((row_number, values))
            self.latest_rows = [values for _, values in normalized]

            current = {str(row): values for row, values in normalized}
            added, changed, deleted = [], [], []
            previous = self._delivery_snapshot
            if previous is not None:
                for key, values in current.items():
                    old = previous.get(key)
                    if old is None:
                        added.append((values.get("row"), values))
                    elif any(old.get(field, "") != values.get(field, "") for field in
                             ("model", "vin", "customer", "sale", "pay_day", "delivery_date")):
                        changed.append((values.get("row"), old, values))
                for key, old in previous.items():
                    if key not in current:
                        deleted.append(old.get("row"))
            self._delivery_snapshot = current
            self.last_changes = []
            return {
                "count": payload.get("count", len(normalized)),
                "changes": [],
                "added": added,
                "changed": changed,
                "deleted": deleted,
                "success": payload.get("success", True),
                "structured": False,
            }

        changes = payload.get("changes", [])
        if changes is None:
            changes = []
        if not isinstance(changes, list):
            raise RuntimeError("ฟิลด์ changes ต้องเป็นรายการ (array)")
        self.last_changes = changes
        structured_rows = []
        for event in changes:
            if not isinstance(event, dict) or event.get("type") != "delivery_today":
                continue
            today_fields = event.get("today_fields") if isinstance(event.get("today_fields"), list) else []
            structured_rows.append({
                "row": event.get("row", ""),
                "model": event.get("model", ""),
                "customer": event.get("customer", ""),
                "delivery_date": next((x.get("value", "") for x in today_fields if isinstance(x, dict)), ""),
                "_structured_event": event,
            })
        self.latest_rows = structured_rows
        return {
            "count": payload.get("count", len(changes)),
            "changes": changes,
            "added": [],
            "changed": [],
            "deleted": [],
            "success": payload.get("success", True),
            "structured": True,
        }

    def get_due_today(self, today=None):
        """Return each delivery row whose Pay Day and/or Delivery Date is today."""
        today = today or date.today()
        result = []
        for values in self.latest_rows:
            pay_day = values.get("pay_day", "")
            delivery_date = values.get("delivery_date", "")
            due_fields = []
            if _parse_date(pay_day) == today:
                due_fields.append("Pay Day")
            if _parse_date(delivery_date) == today:
                due_fields.append("Delivery Date")
            if due_fields:
                result.append((values.get("row", ""), {**values, "due_fields": due_fields}))
        return result

