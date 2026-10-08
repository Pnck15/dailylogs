"""Single Google Apps Script client for DailyLog monitors.

Architecture:
- main.py owns one SaleAPIMonitor instance per source.
- sheet_monitor.py never calls GAS.
- This class handles URL normalization, overlap protection, retry/backoff,
  timeout control, timing diagnostics, JSON validation, and payload parsing.
"""
from datetime import date, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import json
import re
import threading
import time

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

    for fmt in (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d/%m/%y",
        "%m/%d/%Y",
        "%d-%m-%Y",
        "%d-%m-%y",
    ):
        try:
            parsed = datetime.strptime(text[:10], fmt).date()
            if parsed.year > 2400:
                parsed = parsed.replace(
                    year=parsed.year - 543
                )
            return parsed
        except ValueError:
            pass

    normalized = re.sub(r"\s+", " ", text)
    for month_name, month_number in _THAI_MONTHS.items():
        if month_name not in normalized:
            continue

        match = re.search(
            r"(\d{1,2})\s+"
            + re.escape(month_name)
            + r"\s+(\d{2,4})",
            normalized,
        )

        if not match:
            continue

        day = int(match.group(1))
        year = int(match.group(2))

        if year < 100:
            year += 2000

        if year > 2400:
            year -= 543

        try:
            return date(
                year,
                month_number,
                day,
            )
        except ValueError:
            return None

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
    ):
        try:
            parsed = datetime.strptime(
                text,
                fmt,
            ).date()

            if parsed.year > 2400:
                parsed = parsed.replace(
                    year=parsed.year - 543
                )

            return parsed
        except ValueError:
            pass

    return None


class SaleAPIMonitor:
    """One GAS connection per data source.

    Supports:
    * Legacy Sale feed: {rows:[...]} or {data:[...]}
    * Structured GAS: {changes:[{type,sheet,row,...}]}
    """

    def __init__(
        self,
        url,
        timeout=120,
        connect_timeout=8,
        retry_backoff=3.0,
    ):
        self.url = self._normalize_url(url)

        # One polling interval is 5 minutes, so an individual scan should
        # finish comfortably below that interval.
        self.timeout = max(
            15,
            int(timeout),
        )
        self.connect_timeout = max(
            3,
            int(connect_timeout),
        )
        self.retry_backoff = max(
            0.5,
            float(retry_backoff),
        )

        self.last_changes = []
        self.last_payload = {}
        self.latest_rows = []
        self._delivery_snapshot = None
        self._snapshot_scope = None

        self.last_elapsed_seconds = 0.0
        self.last_action = ""
        self.last_attempts = 0

        self._request_lock = threading.Lock()

    @staticmethod
    def _normalize_url(url):
        text = str(
            url or ""
        ).strip()

        if (
            text.startswith("[")
            and "](" in text
            and text.endswith(")")
        ):
            text = (
                text.split("](", 1)[1][:-1]
                .strip()
            )

        text = (
            text
            .strip("<> ")
            .replace(
                "https:https://",
                "https://",
                1,
            )
        )

        if not text:
            return ""

        parts = urlsplit(text)

        if parts.scheme not in (
            "http",
            "https",
        ):
            raise ValueError(
                "Apps Script URL ต้องขึ้นต้นด้วย https://"
            )

        if parts.netloc != "script.google.com":
            raise ValueError(
                "URL ต้องเป็น Google Apps Script Web App "
                "(script.google.com)"
            )

        if not (
            parts.path.rstrip("/")
            .endswith("/exec")
        ):
            raise ValueError(
                "Apps Script Web App URL ต้องลงท้ายด้วย /exec"
            )

        return text

    def _action_url(
        self,
        action="changes",
    ):
        if not self.url:
            raise ValueError(
                "ไม่ได้กำหนด Apps Script Web App URL"
            )

        parts = urlsplit(
            self.url
        )

        query = dict(
            parse_qsl(
                parts.query,
                keep_blank_values=True,
            )
        )

        query["action"] = action
        query["_dl_ts"] = str(
            int(
                time.time()
                * 1000
            )
        )

        return urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                parts.path,
                urlencode(query),
                parts.fragment,
            )
        )

    @staticmethod
    def _is_retryable_status(status):
        return (
            status == 429
            or 500 <= status <= 599
        )

    def _request_json(
        self,
        action,
        read_timeout=None,
        max_retries=1,
    ):
        if not self._request_lock.acquire(
            blocking=False
        ):
            raise RuntimeError(
                "มีคำขอไป Apps Script ของช่องทางนี้กำลังทำงานอยู่แล้ว "
                "จึงไม่ส่งคำขอซ้อน"
            )

        started = time.monotonic()

        try:
            url = self._action_url(
                action
            )

            timeout = (
                self.timeout
                if read_timeout is None
                else max(
                    5,
                    int(read_timeout),
                )
            )

            attempts = (
                max(
                    0,
                    int(max_retries),
                )
                + 1
            )

            last_error = None

            for attempt in range(
                1,
                attempts + 1,
            ):
                self.last_attempts = attempt
                self.last_action = action

                attempt_started = (
                    time.monotonic()
                )

                try:
                    response = requests.get(
                        url,
                        headers={
                            "Accept":
                                "application/json",
                            "User-Agent":
                                "DailyLog-Notifier/2.0",
                            "Cache-Control":
                                "no-cache",
                        },
                        timeout=(
                            self.connect_timeout,
                            timeout,
                        ),
                        allow_redirects=True,
                    )

                except requests.exceptions.ReadTimeout as exc:
                    # Do not retry read timeout automatically. GAS may still
                    # be executing server-side and a second request could
                    # overlap with the first one.
                    elapsed = (
                        time.monotonic()
                        - attempt_started
                    )
                    raise RuntimeError(
                        "Google Apps Script ใช้เวลานานเกินกำหนด "
                        f"({elapsed:.1f}/{timeout} วินาที) "
                        "จึงยกเลิกคำขอเพื่อป้องกัน request ซ้อน"
                    ) from exc

                except (
                    requests.exceptions.ConnectTimeout,
                    requests.exceptions.ConnectionError,
                ) as exc:
                    last_error = exc

                    if attempt < attempts:
                        time.sleep(
                            self.retry_backoff
                            * attempt
                        )
                        continue

                    raise RuntimeError(
                        "เชื่อมต่อ Google Apps Script ไม่สำเร็จ "
                        f"หลังลอง {attempt} ครั้ง: {exc}"
                    ) from exc

                except requests.exceptions.SSLError as exc:
                    raise RuntimeError(
                        "SSL/TLS ของ Apps Script "
                        f"เชื่อมต่อไม่สำเร็จ: {exc}"
                    ) from exc

                except requests.exceptions.RequestException as exc:
                    raise RuntimeError(
                        f"เรียก Apps Script ไม่สำเร็จ: {exc}"
                    ) from exc

                status = response.status_code
                raw = response.content.decode(
                    "utf-8-sig",
                    errors="replace",
                )

                if (
                    self._is_retryable_status(
                        status
                    )
                    and attempt < attempts
                ):
                    last_error = RuntimeError(
                        f"HTTP {status}"
                    )
                    time.sleep(
                        self.retry_backoff
                        * attempt
                    )
                    continue

                if status == 404:
                    raise RuntimeError(
                        "[GAS_404] Apps Script Web App URL นี้หา Deployment ไม่พบ "
                        "หรือ Deployment เดิมถูกแทนที่/ลบไปแล้ว "
                        "ให้เปิด Apps Script > Deploy > Manage deployments "
                        "แล้วคัดลอก Web app URL ที่ลงท้าย /exec มาใส่ใหม่"
                    )

                if (
                    status < 200
                    or status >= 300
                ):
                    preview = (
                        raw[:300]
                        .replace(
                            "\n",
                            " ",
                        )
                    )
                    raise RuntimeError(
                        "Apps Script ตอบกลับ "
                        f"HTTP {status}: {preview}"
                    )

                try:
                    payload = json.loads(
                        raw
                    )
                except json.JSONDecodeError as exc:
                    preview = (
                        raw[:400]
                        .replace(
                            "\n",
                            " ",
                        )
                    )
                    lowered = (
                        preview.lower()
                    )

                    if (
                        "<html" in lowered
                        or "<!doctype" in lowered
                    ):
                        raise RuntimeError(
                            "Apps Script Web App ตอบกลับเป็นหน้า HTML "
                            "แทน JSON (ตรวจ Deployment, สิทธิ์การเข้าถึง "
                            "และต้องใช้ URL /exec)"
                        ) from exc

                    raise RuntimeError(
                        f"คำตอบไม่ใช่ JSON: {preview}"
                    ) from exc

                if not isinstance(
                    payload,
                    dict,
                ):
                    raise RuntimeError(
                        "รูปแบบคำตอบ API ไม่ถูกต้อง: "
                        "ต้องเป็น JSON object"
                    )

                if (
                    payload.get("success") is False
                    or payload.get("ok") is False
                ):
                    error_message = str(
                        payload.get("message")
                        or payload.get("error")
                        or "API แจ้งว่าไม่สำเร็จ"
                    )

                    # A GAS lock/busy response is temporary.
                    if (
                        payload.get("busy") is True
                        and attempt < attempts
                    ):
                        last_error = RuntimeError(
                            error_message
                        )
                        time.sleep(
                            self.retry_backoff
                            * attempt
                        )
                        continue

                    if payload.get("busy") is True:
                        raise RuntimeError(
                            "[GAS_BUSY] "
                            + error_message
                        )

                    raise RuntimeError(
                        error_message
                    )

                elapsed = (
                    time.monotonic()
                    - started
                )

                self.last_elapsed_seconds = (
                    elapsed
                )

                payload["_http_status"] = (
                    status
                )
                payload["_final_url"] = (
                    response.url
                )
                payload["_action"] = (
                    action
                )
                payload["_attempts"] = (
                    attempt
                )
                payload["_elapsed_seconds"] = (
                    round(
                        elapsed,
                        3,
                    )
                )

                return payload

            if last_error is not None:
                raise RuntimeError(
                    str(
                        last_error
                    )
                )

            raise RuntimeError(
                "เรียก Apps Script ไม่สำเร็จ"
            )

        finally:
            self._request_lock.release()

    def ping(self):
        """Fast connectivity test; GAS must support action=ping."""
        try:
            payload = self._request_json(
                "ping",
                read_timeout=15,
                max_retries=2,
            )
        except RuntimeError as exc:
            message = str(exc)
            if "Unknown action: ping" in message:
                raise RuntimeError(
                    "GAS Deployment นี้เป็นเวอร์ชันเก่าและยังไม่รองรับ "
                    "action=ping กรุณา Deploy Code.gs เวอร์ชันใหม่ "
                    "แล้วใช้ URL /exec เดิม"
                ) from exc
            raise

        if payload.get(
            "action"
        ) not in (
            None,
            "ping",
        ):
            raise RuntimeError(
                "Apps Script ตอบกลับได้ "
                "แต่ไม่ใช่ ping response"
            )

        return payload

    @staticmethod
    def _row_data_column(
        values,
        column,
    ):
        row_data = values.get(
            "row_data"
        )

        if not isinstance(
            row_data,
            list,
        ):
            return ""

        wanted = str(
            column or ""
        ).strip().upper()

        for item in row_data:
            if not isinstance(
                item,
                dict,
            ):
                continue

            current = str(
                item.get(
                    "column",
                    "",
                )
                or ""
            ).strip().upper()

            if current == wanted:
                return str(
                    item.get(
                        "value",
                        "",
                    )
                    or ""
                ).strip()

        return ""

    @classmethod
    def _row_identity(
        cls,
        values,
        fallback_row,
    ):
        row = values.get(
            "row",
            fallback_row,
        )

        sheet = str(
            values.get(
                "sheet",
                "",
            )
            or ""
        ).strip()

        if sheet:
            sequence = (
                cls._row_data_column(
                    values,
                    "C",
                )
            )
            plate = (
                cls._row_data_column(
                    values,
                    "F",
                )
            )

            if sequence or plate:
                return (
                    f"{sheet}|C={sequence}|F={plate}"
                )

            return (
                f"{sheet}|ROW={row}"
            )

        vin = str(
            values.get(
                "vin",
                "",
            )
            or ""
        ).strip()

        if vin:
            return (
                f"VIN={vin}"
            )

        return (
            f"ROW={row}"
        )

    @staticmethod
    def _row_data_signature(
        values,
    ):
        row_data = values.get(
            "row_data"
        )

        if isinstance(
            row_data,
            list,
        ):
            normalized = []

            for item in row_data:
                if not isinstance(
                    item,
                    dict,
                ):
                    continue

                normalized.append(
                    (
                        str(
                            item.get(
                                "column",
                                "",
                            )
                            or ""
                        ).strip(),
                        str(
                            item.get(
                                "header",
                                "",
                            )
                            or ""
                        ).strip(),
                        str(
                            item.get(
                                "value",
                                "",
                            )
                            or ""
                        ).strip(),
                    )
                )

            return tuple(
                normalized
            )

        return tuple(
            str(
                values.get(
                    field,
                    "",
                )
                or ""
            )
            for field in (
                "model",
                "vin",
                "customer",
                "sale",
                "pay_day",
                "delivery_date",
            )
        )

    def check(
        self,
        initial=False,
    ):
        payload = self._request_json(
            "changes",
            read_timeout=self.timeout,
            max_retries=1,
        )

        self.last_payload = payload

        rows = payload.get(
            "rows"
        )

        if not isinstance(
            rows,
            list,
        ):
            rows = payload.get(
                "data"
            )

        if isinstance(
            rows,
            list,
        ):
            normalized = []

            for index, item in enumerate(
                rows,
                start=2,
            ):
                if not isinstance(
                    item,
                    dict,
                ):
                    continue

                values = dict(
                    item
                )

                row_number = values.get(
                    "row",
                    index,
                )

                values["row"] = row_number

                normalized.append(
                    (
                        row_number,
                        values,
                    )
                )

            self.latest_rows = [
                values
                for _, values
                in normalized
            ]

            current = {
                self._row_identity(
                    values,
                    row,
                ): values
                for row, values
                in normalized
            }

            added = []
            changed = []
            deleted = []

            scope = (
                str(
                    payload.get(
                        "version",
                        "",
                    )
                    or ""
                )
                + "|"
                + str(
                    payload.get(
                        "mode",
                        "rows",
                    )
                    or "rows"
                )
                + "|"
                + str(
                    payload.get(
                        "today",
                        "",
                    )
                    or ""
                )
            )

            previous = (
                self._delivery_snapshot
                if self._snapshot_scope
                == scope
                else None
            )

            if previous is not None:
                for key, values in current.items():
                    old = previous.get(
                        key
                    )

                    if old is None:
                        added.append(
                            (
                                values.get(
                                    "row"
                                ),
                                values,
                            )
                        )

                    elif (
                        self._row_data_signature(
                            old
                        )
                        != self._row_data_signature(
                            values
                        )
                    ):
                        changed.append(
                            (
                                values.get(
                                    "row"
                                ),
                                old,
                                values,
                            )
                        )

                for key, old in previous.items():
                    if key not in current:
                        deleted.append(
                            (
                                old.get(
                                    "row"
                                ),
                                old,
                            )
                        )

            self._delivery_snapshot = (
                current
            )
            self._snapshot_scope = scope
            self.last_changes = []

            return {
                "count":
                    payload.get(
                        "count",
                        len(normalized),
                    ),
                "changes": [],
                "added": added,
                "changed": changed,
                "deleted": deleted,
                "success":
                    payload.get(
                        "success",
                        True,
                    ),
                "structured": False,
                "_elapsed_seconds":
                    payload.get(
                        "_elapsed_seconds",
                        0,
                    ),
                "_attempts":
                    payload.get(
                        "_attempts",
                        1,
                    ),
            }

        changes = payload.get(
            "changes",
            [],
        )

        if changes is None:
            changes = []

        if not isinstance(
            changes,
            list,
        ):
            raise RuntimeError(
                "ฟิลด์ changes ต้องเป็นรายการ (array)"
            )

        self.last_changes = changes

        structured_rows = []

        for event in changes:
            if (
                not isinstance(
                    event,
                    dict,
                )
                or event.get(
                    "type"
                )
                != "delivery_today"
            ):
                continue

            today_fields = (
                event.get(
                    "today_fields"
                )
                if isinstance(
                    event.get(
                        "today_fields"
                    ),
                    list,
                )
                else []
            )

            structured_rows.append({
                "row":
                    event.get(
                        "row",
                        "",
                    ),
                "model":
                    event.get(
                        "model",
                        "",
                    ),
                "customer":
                    event.get(
                        "customer",
                        "",
                    ),
                "delivery_date":
                    next(
                        (
                            item.get(
                                "value",
                                "",
                            )
                            for item in today_fields
                            if isinstance(
                                item,
                                dict,
                            )
                        ),
                        "",
                    ),
                "_structured_event":
                    event,
            })

        self.latest_rows = (
            structured_rows
        )

        return {
            "count":
                payload.get(
                    "count",
                    len(changes),
                ),
            "changes": changes,
            "added": [],
            "changed": [],
            "deleted": [],
            "success":
                payload.get(
                    "success",
                    True,
                ),
            "structured": True,
            "_elapsed_seconds":
                payload.get(
                    "_elapsed_seconds",
                    0,
                ),
            "_attempts":
                payload.get(
                    "_attempts",
                    1,
                ),
        }

    def get_due_today(
        self,
        today=None,
    ):
        today = today or date.today()

        result = []

        for values in self.latest_rows:
            pay_day = values.get(
                "pay_day",
                "",
            )
            delivery_date = values.get(
                "delivery_date",
                "",
            )

            due_fields = []

            if (
                _parse_date(
                    pay_day
                )
                == today
            ):
                due_fields.append(
                    "Pay Day"
                )

            if (
                _parse_date(
                    delivery_date
                )
                == today
            ):
                due_fields.append(
                    "Delivery Date"
                )

            if due_fields:
                result.append(
                    (
                        values.get(
                            "row",
                            "",
                        ),
                        {
                            **values,
                            "due_fields":
                                due_fields,
                        },
                    )
                )

        return result
