# DailyLog Factory / Development Machine

## ย้ายไปเครื่องใหม่

1. ติดตั้ง Python และ VS Code
2. แตก ZIP โปรเจกต์ลง เช่น `D:\mini_daily_log`
3. เปิดโฟลเดอร์ด้วย VS Code
4. เปิด PowerShell ในโฟลเดอร์โปรเจกต์
5. สร้าง virtual environment ใหม่:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

6. ใส่ `.env` ของโปรเจกต์ไว้ที่ root (อย่าเผยแพร่ไฟล์นี้)
7. ทดสอบ:

```powershell
python main.py
```

## Build EXE

```powershell
pyinstaller main.spec
```

> `main.spec` ปัจจุบันอ้างถึง `app.ico` หากไม่มีไฟล์นี้ ให้เพิ่ม `app.ico` หรือแก้ `main.spec` ก่อน Build

## Update Phase 1

`main.py` มี `APP_VERSION` เป็น version ของโปรแกรม

`update_checker.py` ตรวจ `update_config.json`

- ถ้า `manifest_url` ว่าง: ใช้ `update_manifest.json` ในโฟลเดอร์โปรแกรมเพื่อทดสอบ
- ถ้าใส่ URL: โปรแกรมจะอ่าน manifest จาก HTTP/HTTPS

ตัวอย่าง manifest:

```json
{
  "version": "1.1.0",
  "download_url": "https://example.com/DailyLog_1.1.0.exe",
  "published_at": "2026-09-30",
  "release_notes": [
    "เพิ่ม User Management",
    "แก้ไข Sale Deli"
  ]
}
```

Phase 1 มีหน้าที่แจ้งว่ามีเวอร์ชันใหม่เท่านั้น ยังไม่ทำ self-update

## สำคัญ

- `.env` มีข้อมูลเชื่อมต่อ Cloud ไม่ควรใส่ใน Git หรือส่งสาธารณะ
- `.venv` ไม่จำเป็นต้องย้ายข้ามเครื่อง ให้สร้างใหม่จาก `requirements.txt`
- Supabase และ Apps Script ไม่ต้องย้ายไปเครื่อง Development ใหม่
