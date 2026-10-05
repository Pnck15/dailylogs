DailyLog - Sale Delivery Plan
==============================

ไฟล์ชุดนี้เปลี่ยนระบบ Sale Delivery Plan จาก Google Sheets API/OAuth
มาเป็น:

Google Sheet (Private / Viewer)
        ↓
Standalone Google Apps Script
        ↓
Web App URL (HTTP JSON)
        ↓
DailyLog.exe
        ↓
Notification List + Toast

ไม่ใช้:
- Google Cloud Project
- credentials.json
- Google Sheets API
- Google OAuth ใน DailyLog

ไฟล์
----
main.py
    โปรแกรม DailyLog ที่แก้ระบบ Sale Delivery Plan แล้ว

sale_api_monitor.py
    ตัวอ่าน Apps Script Web App ด้วย HTTP

Code.gs
    โค้ด Google Apps Script สำหรับอ่าน Delivery 2026

cloud_db.py
    ใช้ไฟล์เดิมของโปรเจกต์ ไม่ได้แก้

วิธีใช้
-------
1. ใน Apps Script ให้ใช้ Code.gs
2. Deploy เป็น Web App
3. ตั้ง Execute as: Me
4. ตั้ง Who has access ตามสิทธิ์ที่องค์กร/บัญชีอนุญาต
5. คัดลอก Web App URL
6. เปิด DailyLog
7. กด "แจ้งเตือน Sale Delivery Plan"
8. วาง Web App URL
9. กด "เริ่มแจ้งเตือน"

DailyLog จะตรวจทุก 60 วินาที

ข้อมูลที่อ่านจาก Delivery 2026
--------------------------------
F = VIN
H = Customers
K = Pay Day
L = Delivery Date

การแจ้งเตือน
------------
🟢 เพิ่มรายการใหม่
🟡 มีการแก้ไขข้อมูล
🔴 รายการถูกลบ
🚗 ถึงกำหนดส่งรถวันนี้
🔔 สถานะการเชื่อมต่อ/ข้อผิดพลาด

Notification จะเก็บอยู่ในตัวโปรแกรมสูงสุด 50 รายการ
และเมื่อมีเหตุการณ์ใหม่ จะมี Toast เล็ก ๆ แสดงภายในหน้าต่าง DailyLog

ติดตั้ง dependency
------------------
ถ้ายังไม่มี requests:

pip install requests

ทดสอบก่อนเปิดโปรแกรม
---------------------
python -m py_compile main.py sale_api_monitor.py

จากนั้น:

python main.py

หมายเหตุ
--------
ระบบนี้ยังใช้ database/cloud_db.py เดิมของ DailyLog
และไม่ได้เปลี่ยนระบบ Database ตามที่ต้องการ
