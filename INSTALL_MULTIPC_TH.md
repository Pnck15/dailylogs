# คู่มือติดตั้ง DailyLog และ DailyLogNotify หลายเครื่อง (Windows)

สองโปรแกรมเป็น EXE แยกกัน DailyLogNotify รับ Notification จาก Supabase Central โดยไม่ต้องเปิด DailyLog.exe

## แยกโฟลเดอร์ลงเครื่อง

    C:\DailyLog\
        DailyLog.exe
        DailyLogUpdater.exe

    C:\DailyLogNotify\
        DailyLogNotify.exe
        DailyLogUpdater.exe

ใช้ EXE ที่เผยแพร่ผ่าน GitHub Releases เท่านั้น และอย่าใช้ Updater.exe คนละโปรแกรมเขียนทับกัน
ไฟล์ version.json และ notify-version.json เป็นข้อมูล Manifest ที่ Release เผยแพร่ไว้เพื่อการตรวจอัปเดต

**ไม่ต้องเอา DailyLog.old.exe ไปติดตั้ง.** ตัวอัปเดตจะสร้าง .old.exe เป็นสำรอง
ของ EXE เดิมไว้ในเครื่องนั้นก่อนแทนไฟล์ใหม่ หากอัปเดตผิดพลาดจะใช้กู้คืน
อย่าลบไฟล์สำรองก่อนแน่ใจว่ารุ่นใหม่เปิดได้ดี

## ลง DailyLog

1. ติดตั้ง EXE และ Updater คู่กันในโฟลเดอร์ของ DailyLog
2. Login ด้วยบัญชีที่ได้รับสิทธิ์ใน Supabase Workspace
3. เปิดเมนู ☰ → เครื่องคิดเลขหัก ณ ที่จ่าย 3% / ส่วนต่างยอดลูกค้า
   คิดจากฐานก่อน VAT, ยอดเรียกเก็บจริง, ยอดชำระแล้ว
4. หน้า + Add Log → รูปแบบ → แบบฟอร์มป้ายแดง จะมีช่อง
   ชื่อลูกค้า, VIN, วันรับ, วันคืน/ยังไม่คืน, SC, หมายเหตุ
5. แบบฟอร์มเก็บใน Logs ของ Supabase เดิม และเปิดแก้ย้อนหลังแบบมีช่องกรอกได้

## ส่งลิงก์ GAS จาก DailyLog ให้ Notify

1. ผู้ดูแลเปิด ☰ → Notification System Settings → Main Notification Sources
2. กด + New, ใส่ชื่อ Source และ Apps Script Web App URL ที่ใช้งานจริง (/exec)
3. เลือก Enable monitoring และ Show this Source in DailyLogNotify
4. กด Test Connection แล้ว Save
5. ใน DailyLogNotify ของแต่ละเครื่อง เปิด Notification Sources → Refresh Sources
   เลือก Source ใหม่แล้วกด Save
6. ระบบจะโหลดรายการ Source จาก Supabase Central แทนการกรอก URL ซ้ำใน Notify

หมายเหตุ: ลิงก์หน้า Google Sheets ไม่ใช่ GAS API; ต้องสร้าง GAS Web App
ที่คืน JSON ตามรูปแบบ Central Monitor จึงจะตรวจจับการเปลี่ยนแปลงได้

## ลง DailyLogNotify

1. แยกโฟลเดอร์ของ Notify พร้อม DailyLogUpdater.exe
2. Login และเลือกแหล่งแจ้งเตือนตามแต่ละเครื่อง
3. ตรวจ System Status: Central Login Connected, Device Registration Active,
   Last Heartbeat มีเวลา, Windows Startup Enabled, Updater Ready
4. กด X ของหน้าต่างหลักจะซ่อนใน System Tray (ถ้า Tray ไม่พร้อมจะย่อใน Taskbar)
5. หลัง Windows Login โปรแกรมจะเริ่มอัตโนมัติได้ หาก Startup ติดตั้งและยังมีสิทธิ์ Session
6. อุปกรณ์ที่ Admin เพิกถอน Session ไม่ควรถูกปลดล็อกด้วยการลบ Device ID;
   ต้องให้ผู้ดูแลตรวจสิทธิ์ก่อน

## อัปเดต

DailyLog ใช้ GitHub Release tag แบบ vX.Y.Z ส่วน Notify ใช้ notify-vX.Y.Z
Updater ตรวจ SHA256 และสำรอง EXE เดิมเป็นไฟล์ .old.exe ก่อนแทนที่
การ Build ผ่านไม่ได้ยืนยันว่าเครื่องทุกเครื่อง Login และ Heartbeat สำเร็จ
ต้องตรวจ System Status บนเครื่องจริงทุกเครื่อง
