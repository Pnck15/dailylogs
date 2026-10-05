# DailyLog Factory

Source สำหรับสร้าง DailyLog.exe และระบบ Auto Update สำหรับเครื่องผู้ใช้หลายเครื่อง

## 1) Architecture

- Supabase = Auth / Workspace / Logs / shared cloud data
- Google Apps Script = Sale Delivery data source
- DailyLog.exe = โปรแกรมหลักบนแต่ละเครื่อง
- DailyLogUpdater.exe = ตัวช่วยปิด/แทนที่ DailyLog.exe
- GitHub Releases = ที่เก็บไฟล์ release และ `version.json`

GitHub Releases รองรับการแนบ binary assets ให้แต่ละ release และมี URL ดาวน์โหลด asset ของ release ได้โดยตรง. GitHub Releases documentation: https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases

## 2) ตั้ง GitHub สำหรับ Auto Update

สร้าง GitHub repository สำหรับ DailyLog เช่น:

```text
OWNER/REPOSITORY
```

แนะนำให้ repository เป็น **Public** สำหรับระบบนี้ เพราะเครื่องผู้ใช้ต้องอ่าน `version.json` และดาวน์โหลด `DailyLog.exe` โดยไม่ต้องฝัง GitHub token ลงในโปรแกรม

## 3) Login GitHub CLI บนเครื่อง Development

ติดตั้ง GitHub CLI (`gh`) แล้วรัน:

```powershell
gh auth login
```

ตรวจสอบ:

```powershell
gh auth status
```

## 4) Build Release ที่ผูกกับ GitHub

ตัวอย่าง:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\build_release.ps1 -GitHubRepo "OWNER/REPOSITORY"
```

ตัวอย่างจริง:

```powershell
.\build_release.ps1 -GitHubRepo "PearN/DailyLog"
```

คำสั่งนี้จะตั้งค่า `update_config.json` เป็น:

```text
https://github.com/OWNER/REPOSITORY/releases/latest/download/version.json
```

แล้ว Build:

- `release\DailyLog.exe`
- `release\DailyLogUpdater.exe`

## 5) Publish Release

หลัง Build เสร็จ ใช้:

```powershell
.\publish_release.ps1 -GitHubRepo "OWNER/REPOSITORY"
```

Script จะ:

1. อ่าน `APP_VERSION` จาก `main.py`
2. คำนวณ SHA-256 ของ `release\DailyLog.exe`
3. สร้าง `version.json`
4. สร้าง GitHub Release เช่น `v1.0.0`
5. Upload:
   - `DailyLog.exe`
   - `DailyLogUpdater.exe`
   - `version.json`

GitHub จะให้ release asset มี download URL และ API ของ release สามารถระบุ asset ได้.

## 6) เครื่องผู้ใช้ทำงานอย่างไร

เมื่อผู้ใช้เปิด DailyLog.exe:

```text
DailyLog.exe
    ↓
รอประมาณ 2.5 วินาที
    ↓
อ่าน version ปัจจุบัน
    ↓
GET version.json จาก GitHub
    ↓
เปรียบเทียบ version
    ↓
ถ้ามีเวอร์ชันใหม่
    ↓
แสดงปุ่ม "อัปเดตตอนนี้"
    ↓
DailyLogUpdater.exe
    ↓
รอ DailyLog.exe ปิด
    ↓
ดาวน์โหลด DailyLog.exe ใหม่
    ↓
ตรวจ SHA-256
    ↓
แทนที่ DailyLog.exe
    ↓
เปิด DailyLog.exe ใหม่
```

ดังนั้นเครื่องผู้ใช้ **ไม่ต้องเข้า GitHub เองเพื่อกด Download**

## 7) วิธีออก Version ใหม่ในอนาคต

สมมติปัจจุบัน:

```python
APP_VERSION = "1.0.0"
```

เมื่อแก้โปรแกรมแล้ว ให้เปลี่ยนเป็น:

```python
APP_VERSION = "1.1.0"
```

จากนั้น:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\build_release.ps1 -GitHubRepo "OWNER/REPOSITORY"
.\publish_release.ps1 -GitHubRepo "OWNER/REPOSITORY"
```

เครื่องที่ยังเป็น `1.0.0` จะเห็นว่า `1.1.0` ใหม่กว่า และจะแสดง Update popup

## 8) สำคัญ: อย่า Build โดยไม่ระบุ GitHubRepo

ถ้าใช้:

```powershell
.\build_release.ps1
```

ระบบจะยังใช้ค่าที่มีอยู่ใน `update_config.json`

สำหรับการตั้งเครื่องครั้งแรก ให้ใช้:

```powershell
.\build_release.ps1 -GitHubRepo "OWNER/REPOSITORY"
```

## 9) Security

- ไม่ใส่ GitHub token ลงใน DailyLog.exe
- ไม่ใส่ Supabase `service_role` key ลงใน EXE
- GitHub repository สำหรับ update ควรเป็น Public ถ้าต้องการให้เครื่องปลายทางดาวน์โหลดโดยไม่ต้องมี credential
- `version.json` มีเฉพาะ version, download URL, SHA-256 และ release notes

## 10) Supabase / .env บนเครื่องผู้ใช้

ปัจจุบัน `cloud_db.py` ยังอ่าน:

```text
SUPABASE_URL
SUPABASE_PUBLISHABLE_KEY
```

จาก `.env` ที่อยู่ข้าง `DailyLog.exe`

ดังนั้น Auto Update กับ Supabase เป็นคนละส่วนกัน:

```text
GitHub Releases
      ↓
Program Update

Supabase
      ↓
Cloud Data / Login / Logs
```

## 11) Background / Settings

ค่าพื้นหลัง สี ไอคอน และค่าตั้งค่าเฉพาะเครื่องยังเก็บใน Windows AppData ของผู้ใช้แต่ละคน ไม่ได้ถูกเขียนทับจาก GitHub Update

## 12) GitHub Release

GitHub Releases ใช้สำหรับแจก software iterations พร้อม release notes และ binary files และสามารถสร้าง URL สำหรับ latest release asset ได้.
