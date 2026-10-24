"""Recognize authorized read-only Google spreadsheet URLs.

A Google Sheets URL is a *locator*, not a credential. A private workbook is
readable only through a separately deployed Gateway GAS account with access.
"""
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit
import re

_FILE_ID = re.compile(r"^[A-Za-z0-9_-]{15,}$")
_DOCUMENT = re.compile(r"^/spreadsheets/d/([A-Za-z0-9_-]{15,})(?:/|$)")
_DRIVE = re.compile(r"^/file/d/([A-Za-z0-9_-]{15,})(?:/|$)")


def is_viewer_file_url(url):
    parts = urlsplit(str(url or "").strip())
    return bool(
        parts.scheme == "https"
        and (
            (parts.hostname == "docs.google.com" and _DOCUMENT.search(parts.path))
            or (parts.hostname == "drive.google.com" and _DRIVE.search(parts.path))
        )
    )


def viewer_target(url):
    """Return id, gid, optional tab without contacting the source workbook."""
    parts = urlsplit(str(url or "").strip())
    if not is_viewer_file_url(url):
        raise ValueError("ต้องใส่ลิงก์ Google Sheets หรือ Drive Excel ที่ถูกต้อง")
    match = _DOCUMENT.search(parts.path) or _DRIVE.search(parts.path)
    file_id = match.group(1)
    options = dict(parse_qsl(parts.query, keep_blank_values=True))
    fragment = dict(parse_qsl(parts.fragment, keep_blank_values=True))
    gid = options.get("gid") or fragment.get("gid") or ""
    tab = options.get("tab") or fragment.get("tab") or ""
    if gid and not re.fullmatch(r"\d{1,15}", gid):
        raise ValueError("gid ของ Google Sheets ไม่ถูกต้อง")
    if len(tab) > 120:
        raise ValueError("ชื่อแท็บยาวเกินไป")
    return {"id": file_id, "gid": gid, "tab": tab}


def with_viewer_tab(url, tab):
    """Save the optional Excel sheet name in the original URL query."""
    parts = urlsplit(str(url or "").strip())
    if not is_viewer_file_url(url):
        raise ValueError("ไม่ใช่ Google Sheets/Drive Viewer URL")
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    if str(tab or "").strip():
        params["tab"] = str(tab).strip()
    else:
        params.pop("tab", None)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))


def make_viewer_gateway_url(gateway_url, sheet_url):
    """Retain the secret token in gateway URL; append the validated target."""
    gateway = urlsplit(str(gateway_url or "").strip())
    if not (
        gateway.scheme == "https"
        and gateway.hostname == "script.google.com"
        and gateway.path.rstrip("/").endswith("/exec")
    ):
        raise ValueError(
            "ตั้งค่า Viewer Gateway Web App URL (/exec?token=...) "
            "ใน Main Notification Sources ก่อน"
        )
    params = dict(parse_qsl(gateway.query, keep_blank_values=True))
    if not params.get("token"):
        raise ValueError("Viewer Gateway URL ยังไม่มี Secret Token")
    params.update(viewer_target(sheet_url))
    params.pop("action", None)
    return urlunsplit((
        gateway.scheme, gateway.netloc, gateway.path, urlencode(params), ""
    ))
