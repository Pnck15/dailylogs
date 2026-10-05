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

## Build
```powershell
.\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm DailyLogNotify.spec
```

ผลลัพธ์: `dist\DailyLogNotify.exe`

> ห้าม commit token จริงลง GitHub ค่า LINE ของแต่ละเครื่องถูกเก็บด้วย QSettings ในเครื่องนั้น
