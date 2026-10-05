DailyLog Update - 25/09/2026

ไฟล์หลัก
- main.py
- cloud_db.py
- sale_api_monitor.py
- test_delivery_popup.py
- add_log_author_columns.sql

สิ่งที่แก้
1) เก็บชื่อผู้บันทึกจาก email (ส่วนก่อน @) และแสดงใน Log เช่น 👤 บันทึกโดย: pnck533
2) Login มี Remember me (Email + Password) โดย Windows ใช้ DPAPI เข้ารหัส password ก่อนเก็บใน QSettings
3) Sale Deli แยก 2 ปุ่ม: Sathorn / Srinakarin และจำ URL แยกกัน
4) ขยายหน้าต่างเป็น 720x430 และเว้นระยะ + Add Log จากปฏิทิน
5) Hover/Pressed ปุ่มเป็นเทาเข้ม ตัวหนังสือขาว
6) Sale popup ไม่หายเอง ต้องกด ปิด
7) Background ถูก copy ไป %APPDATA%\\MiniDailyLog\\background.* ทำให้ปิด/เปิดใหม่ยังอยู่

สำคัญ: ต้องรัน add_log_author_columns.sql ใน Supabase SQL Editor 1 ครั้งก่อน Add Log ใหม่ เพื่อเพิ่ม created_by_name และ created_by_email

Sathorn ใช้ Apps Script URL เดิมที่มีอยู่ในโค้ด
Srinakarin: เปิดปุ่ม Sale Deli Srinakarin แล้วใส่ Apps Script Web App URL ของ Sheet Srinakarin ครั้งแรก โปรแกรมจะจำไว้เอง

ไม่ต้องใช้ Google Cloud และไม่ต้องใช้ credentials.json
