# DailyLog Phase 3 — Responsive Cloud Architecture

## เป้าหมาย
Phase 3 ย้ายงาน Supabase ทั้งหมดออกจาก GUI thread เพื่อแก้ปัญหา `Not Responding` ที่เกิดจาก Network I/O และทำให้ Search / Calendar / Add / Edit / Delete / Login ทำงานแบบ asynchronous

### งานที่ย้ายออกจาก GUI thread
- Supabase Login + Workspace membership
- โหลดวันใน Calendar
- โหลด Logs ตามวัน
- Search Logs
- โหลด Log ก่อน Edit
- Add Log
- Update Log
- Delete Log
- Sale Delivery Plan polling
- Update Checker

### สถาปัตยกรรม
`GUI Thread`
→ รับ input / วาด UI / แสดง dialog

`CloudService`
→ queue งาน Supabase ทุกงานให้ thread เดียว

`CloudDB`
→ ติดต่อ Supabase ใน worker thread เท่านั้น

Search ใช้ debounce 350 ms เพื่อไม่ยิง API ทุกตัวอักษร

## สำคัญ
Phase 3 ลดสาเหตุหลักของ `Not Responding` จาก Network I/O แต่ไม่ได้รับประกันว่า Windows จะไม่มีอาการค้างจากทุกสาเหตุ เช่น OS, driver, antivirus, filesystem หรือ CPU-heavy code

## Build
เปิด PowerShell ในโฟลเดอร์ factory แล้วรัน:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\build_release.ps1
```

ผลลัพธ์:
- `release\DailyLog.exe`
- `release\DailyLogUpdater.exe`

## Supabase
ต้องมี `.env` ในเครื่อง factory สำหรับ development:

```env
SUPABASE_URL=...
SUPABASE_PUBLISHABLE_KEY=...
```

อย่านำ `service_role` key ไปใส่ใน Desktop App

## Update
ต้องตั้ง `manifest_url` ใน `update_config.json` ไปยัง JSON ที่โฮสต์จริง และ JSON ต้องมี `version`, `download_url`, `release_notes`

ตัวอย่าง:

```json
{
  "version": "1.1.0",
  "download_url": "https://example.com/releases/DailyLog.exe",
  "published_at": "2026-09-26",
  "release_notes": [
    "Responsive Cloud Architecture",
    "ลดอาการ Not Responding จาก Network I/O"
  ]
}
```


## Sale Delivery notification rule (fixed)
- First connection: load the current sheet as a baseline; do not popup every existing row.
- New row after monitoring starts: notify as new.
- Changed row: notify only the fields that changed.
- Delivery date = today: notify once per row/date.
- Deleted rows are not popup notifications.
