"""Dependency-free XLSX export of DailyLogNotify's locally visible history.

Writes Office Open XML using only Python's standard library, preserving
untrusted Sheet cell text as inline strings (never evaluated as formulas).
"""
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

ET.register_namespace("", S)
ET.register_namespace("r", R)
HEADERS = ("วันที่เวลา", "Source", "หัวข้อแจ้งเตือน", "รายละเอียดแจ้งเตือน", "Source Key")
KEYS = ("created_at", "source", "title", "message", "source_key")


def _safe(value):
    text = str(value or "")
    # XML 1.0 disallows control bytes, and Excel cell limit is 32767 chars.
    text = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]", "", text)
    return text[:32767]


def _col(num):
    letters = ""
    while num:
        num, rest = divmod(num - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def make_history_xlsx(path, records):
    """Export only the already-filtered records handed in by HistoryDialog."""
    records = list(records or [])
    if not records:
        raise ValueError("ไม่มีประวัติแจ้งเตือนที่แสดงอยู่ให้ส่งออก")
    dest = Path(path).expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    ws = ET.Element(f"{{{S}}}worksheet")
    views = ET.SubElement(ws, f"{{{S}}}sheetViews")
    view = ET.SubElement(views, f"{{{S}}}sheetView", workbookViewId="0")
    ET.SubElement(view, f"{{{S}}}pane", ySplit="1", topLeftCell="A2",
                  activePane="bottomLeft", state="frozen")
    cols = ET.SubElement(ws, f"{{{S}}}cols")
    for number, width in enumerate((22, 22, 34, 76, 22), 1):
        ET.SubElement(cols, f"{{{S}}}col", min=str(number),
                      max=str(number), width=str(width), customWidth="1")
    data = ET.SubElement(ws, f"{{{S}}}sheetData")
    for idx, record in enumerate([dict(zip(KEYS, HEADERS))] + records, 1):
        row = ET.SubElement(data, f"{{{S}}}row", r=str(idx))
        if idx == 1:
            row.set("ht", "28")
            row.set("customHeight", "1")
        for pos, field in enumerate(KEYS, 1):
            cell = ET.SubElement(
                row, f"{{{S}}}c", r=f"{_col(pos)}{idx}", t="inlineStr",
                s="1" if idx == 1 else "2" if idx % 2 == 0 else "0",
            )
            inline = ET.SubElement(cell, f"{{{S}}}is")
            text_node = ET.SubElement(inline, f"{{{S}}}t")
            text_node.set(XML_SPACE, "preserve")
            text_node.text = _safe(record.get(field, ""))
    ET.SubElement(ws, f"{{{S}}}autoFilter", ref=f"A1:E{len(records)+1}")
    ET.SubElement(ws, f"{{{S}}}pageMargins", left="0.3", right="0.3",
                  top="0.5", bottom="0.5", header="0.3", footer="0.3")

    book = ET.Element(f"{{{S}}}workbook", {f"{{{R}}}dummy": ""})
    book.attrib.pop(f"{{{R}}}dummy")
    tabs = ET.SubElement(book, f"{{{S}}}sheets")
    ET.SubElement(
        tabs, f"{{{S}}}sheet",
        {"name": "Notification History", "sheetId": "1", f"{{{R}}}id": "rId1"},
    )

    styles = """<?xml version="1.0" encoding="UTF-8"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
 <fonts count="2"><font><sz val="11"/><name val="Aptos"/></font>
 <font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Aptos"/></font></fonts>
 <fills count="4"><fill><patternFill patternType="none"/></fill>
 <fill><patternFill patternType="gray125"/></fill>
 <fill><patternFill patternType="solid"><fgColor rgb="FF1E3A5F"/><bgColor indexed="64"/></patternFill></fill>
 <fill><patternFill patternType="solid"><fgColor rgb="FFF0F5FC"/><bgColor indexed="64"/></patternFill></fill></fills>
 <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
 <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
 <cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"><alignment vertical="top" wrapText="1"/></xf>
 <xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0"><alignment vertical="center" wrapText="1"/></xf>
 <xf numFmtId="0" fontId="0" fillId="3" borderId="0" xfId="0"><alignment vertical="top" wrapText="1"/></xf></cellXfs>
 <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
 </styleSheet>"""

    rels = ET.Element(f"{{{PKG}}}Relationships")
    ET.SubElement(rels, f"{{{PKG}}}Relationship", Id="rId1",
                  Type=R+"/worksheet", Target="worksheets/sheet1.xml")
    ET.SubElement(rels, f"{{{PKG}}}Relationship", Id="rId2",
                  Type=R+"/styles", Target="styles.xml")
    base_rels = ET.Element(f"{{{PKG}}}Relationships")
    ET.SubElement(base_rels, f"{{{PKG}}}Relationship", Id="rId1",
                  Type=R+"/officeDocument", Target="xl/workbook.xml")

    types = ET.Element(f"{{{CT}}}Types")
    ET.SubElement(types, f"{{{CT}}}Default",
                  Extension="rels", ContentType="application/vnd.openxmlformats-package.relationships+xml")
    ET.SubElement(types, f"{{{CT}}}Default",
                  Extension="xml", ContentType="application/xml")
    for part, mime in (
        ("/xl/workbook.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"),
        ("/xl/worksheets/sheet1.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"),
        ("/xl/styles.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"),
    ):
        ET.SubElement(types, f"{{{CT}}}Override", PartName=part, ContentType=mime)

    def xml(element):
        return ET.tostring(element, encoding="utf-8", xml_declaration=True)

    fd, temp = tempfile.mkstemp(prefix=".notify-history-", suffix=".xlsx",
                                 dir=str(dest.parent))
    os.close(fd)
    try:
        with ZipFile(temp, "w", ZIP_DEFLATED, compresslevel=6) as archive:
            for name, value in (
                ("[Content_Types].xml", xml(types)),
                ("_rels/.rels", xml(base_rels)),
                ("xl/workbook.xml", xml(book)),
                ("xl/_rels/workbook.xml.rels", xml(rels)),
                ("xl/styles.xml", styles.encode("utf-8")),
                ("xl/worksheets/sheet1.xml", xml(ws)),
            ):
                archive.writestr(name, value)
        os.replace(temp, dest)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return len(records)
