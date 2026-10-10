# DailyLogNotify

โปรแกรมแยกสำหรับแจกพนักงาน โดยไม่เปิดหน้าปฏิทิน/บันทึกส่วนตัวของ DailyLog

## ความสามารถชุดแรก
- System Tray
- เปิดพร้อม Windows เมื่อรันเป็น EXE
- Windows notification popup
- Notification History เก็บใน SQLite ภายใต้ LOCALAPPDATA
- หน้าต่าง Notification Connections แยก
- เปิด/ปิด LINE Messaging API
- Test LINE
- เตรียมจุดเชื่อม Today's Delivery Summary

## Build และ release อัตโนมัติ

Windows workflow `.github/workflows/notify-release.yml` ทำการทดสอบ, build เข้า `release/`, ทดสอบ EXE จริง และเผยแพร่ `notify-v<APP_VERSION>` เมื่อ push โค้ดที่เกี่ยวข้องเข้า `feature/dailylog-notify` ต้องเพิ่ม `APP_VERSION` ก่อนออก release ใหม่ ไฟล์ที่เผยแพร่มี `DailyLogNotify.exe`, `DailyLogUpdater.exe` และ `notify-version.json` พร้อม SHA256 ของทั้งสอง EXE และ commit ต้นทาง

รุ่น 1.5.1 ขึ้นไปตรวจอัปเดตเมื่อเปิดโปรแกรมและทุก 15 นาที ดาวน์โหลดครบและตรวจ SHA256 ก่อนหยุด receiver พร้อมซ่อม updater ที่หายหรือเก่าให้อัตโนมัติ หากติดตั้งหรือเปิดรุ่นใหม่ไม่สำเร็จ updater จะกู้รุ่นเดิมและเปิดกลับ ข้อมูล login และ source ที่เลือกยังเก็บในเครื่องเดิม

เครื่องที่ใช้รุ่นก่อนหน้าและมี `DailyLogUpdater.exe` อยู่ข้าง EXE จะรับรุ่นใหม่ตามรอบตรวจของรุ่นนั้น (เช่น 6 ชั่วโมงหรือเมื่อเปิดโปรแกรมใหม่) ถ้ารุ่นเก่าไม่มีตัว updater จะต้องนำทั้งสอง EXE ไปวางในโฟลเดอร์ที่เขียนได้และเปิดครั้งแรกหนึ่งครั้งก่อน การเปิดพร้อม Windows หมายถึงหลังผู้ใช้เข้าสู่ระบบ Windows; ครั้งแรกต้อง login และเลือก source

CI ใช้เฉพาะ Supabase URL และ publishable key ใน `notify_build_config.json` ไม่ใช้ service-role key การ build ด้วยมือยังใช้ `.env` ของผู้พัฒนาได้

## Build ด้วยมือ
```powershell
.\build_notify.ps1
.\publish_notify_release.ps1 -GitHubRepo Pnck15/dailylogs
```

ผลลัพธ์: `release\DailyLogNotify.exe` และ `release\DailyLogUpdater.exe`

> ห้าม commit token จริงลง GitHub ค่า LINE ของแต่ละเครื่องถูกเก็บด้วย QSettings ในเครื่องนั้น

