# SA Sathorn — deploy GAS v6.2 (Thailand)

## ตรวจพบก่อน Deploy

- DailyLog 1.2.1 แสดงไฟเหลือง **เมื่อกำลังตรวจหรือรอคิว** ไม่ได้แปลว่าหลุดทุกครั้ง
- ฝั่ง Supabase Central Monitor ได้รับ `sa-sathorn-merged-d-v5` และ `merged_d_today_rows` อยู่
- โปรแกรมใหม่ต้องได้รับ Feed `sa-sathorn-all-month-v6.2` และ `all_month_rows_v6`
- ระบบ Cloud Worker v13 รองรับทั้ง v6 formats และไม่ล้าง Snapshot เดิม

## กรณีวันที่ `10.10.69` บน Merged D

Google Sheets อาจอ่านรูปแบบปี พ.ศ. 69 เป็น ค.ศ. 2069 ซึ่งทำให้แจ้งเตือน 10 นาที
ก่อนนัดและตรงเวลาไม่ขึ้น โค้ด GAS v6.2 จะ **อ่านปีสองหลักจากข้อความที่แสดงในเซลล์**
แล้วแปลง `10.10.69` → `2026-10-10` ไม่ว่าค่าภายในเซลล์เป็น Date หรือ Text

ระหว่างรอ Deploy GAS v6.2, Supabase `dailylog-sa-reminder-worker` v2 และ
`dailylog-monitor-worker` v14 แก้ไขกรณีนี้ให้แล้วสำหรับแถวในแท็บ `10.2026`
โดยไม่ได้แก้เซลล์ต้นฉบับ: Worker ใช้ชื่อแท็บและปีที่อ่านผิดไป +43 ปี
เพื่อคืนวันที่ที่ตั้งใจ และจะไม่ส่งแจ้งเตือนว่าแก้ไขข้อมูลย้อนหลังแบบผิดพลาด

แต่ต้องมีเครื่องรับ `DailyLogNotify` ที่ Login สำเร็จและเลือก `SA Sathorn` ไว้;
การมี Event ใน Central ไม่ได้ยืนยันว่า Popup ปรากฏบนเครื่องที่ออกจากระบบแล้ว

## สำรองก่อน

1. เปิด **Apps Script project ที่เป็นของ SA Sathorn เดิม** (จาก Google Sheets > Extensions > Apps Script)
2. คัดลอก Source ของ GAS เดิมไปเก็บเป็นไฟล์ **.txt นอก Apps Script Project** เพื่อใช้ Rollback (อย่าเพิ่มไฟล์ .gs ที่ยังมี `doGet()` ซ้ำใน Project)
3. ที่ Apps Script > **Deploy > Manage deployments** จด URL `/exec` ปัจจุบันและหมายเลขเวอร์ชันไว้
4. อย่าลบ Google Sheets, SQL Snapshot, Supabase `monitor_state`, `notification_events` หรือ GitHub Release

## เปลี่ยนโค้ด GAS

1. เปิด <https://github.com/Pnck15/dailylogs/blob/feature/dailylog-notify/gas/sa_sathorn_v6.gs>
2. ใช้ Source นี้แทน **เฉพาะ Web App สำหรับ SA Sathorn** โดยรักษา `doGet` ของโปรเจกต์ให้เหลือหนึ่งฟังก์ชัน
3. Verify Spreadsheet ID และคอลัมน์ B:P, Header Row 2, Data Row 3
4. `Deploy > Manage deployments > Edit` ของ **Deployment เดิม** เลือก **New version** แล้ว Deploy (ไม่สร้าง Deployment ใหม่โดยไม่จำเป็น)
5. ถ้า Google ต้องการสิทธิ์ให้ Approve ด้วยบัญชีที่มีสิทธิ์อ่าน Google Sheets

## ตรวจโดยไม่แก้ Sheet จริง

เปิด URL เดิมต่อท้าย `?action=ping` (ถ้ามี `?` อยู่แล้ว ใช้ `&action=ping`).
ควรเห็นค่าเหล่านี้:

- `ok: true`
- `version: "sa-sathorn-all-month-v6.2"`
- `mode: "all_month_rows_v6"`
- `monitored_sheets: ["10.2026", "11.2026"]` เมื่ออยู่ในตุลาคม 2026

`?action=changes` ต้องคืน `ok:true`, `rows` (ข้อมูลสองแท็บ) และ
`found_sheets` สองชื่อข้างต้น เมื่อมีข้อมูลลูกค้าจริง **อย่าเผยแพร่ JSON responses เต็มแบบสาธารณะ**.

จากนั้นให้ Central ทำงานตามรอบ 5 นาทีจน `monitor_state.version` เป็น
`sa-sathorn-all-month-v6.2` และ Snapshot มีรายการรายเดือน

**สำคัญ:** รอบแรกที่เปลี่ยนจาก v5 เป็น v6.2 จะสร้าง Baseline ใหม่อย่างปลอดภัย
และไม่สร้าง Notification ย้อนหลังนับพันรายการ; การเปลี่ยนแปลงหลังจากรอบนั้น
จึงถูกเปรียบเทียบ เพิ่ม/แก้/ลบต่อเนื่องข้ามวัน
ซึ่งรวมถึงวันที่ที่สืบทอดจาก Merged D ด้วย

## ตรวจแจ้งเตือนจริง

- แก้ข้อมูลในแท็บ 10.2026 หรือ 11.2026 *หลังจาก* Snapshot v6.2 มีข้อมูลแล้ว
- ทดสอบ เพิ่ม/แก้/ลบในข้อมูลทดสอบ 1 แถวเท่านั้น ไม่ใช้ข้อมูลลูกค้าจริง
- Test Reminder: แถวตัวอย่างที่มี D เป็นวันนี้ และ B เป็นเวลาทดสอบ จะส่งสอง Event
  **ก่อนเวลา 10 นาที** และ **ตรงเวลา** หาก Central schedule ต่อเนื่อง
- DailyLogNotify ต้อง Login, เลือก Source SA Sathorn และไม่ถูก Admin revoke; ใช้เมนู System Status / Test Notification Popup เพื่อแยกปัญหาหน้าต่างจากปัญหาการรับ event

## Rollback

Apps Script > Deploy > Manage deployments > Edit ของ Deployment เดิม >
เลือก **เวอร์ชันก่อนหน้า**. Web App URL เดิมยังคงอยู่
(เมื่อย้อนกลับ v5 จะตรวจข้อมูลได้ไม่ครบสองเดือน)
ห้ามลบ Snapshot เพื่อแก้ปัญหาด้วยตนเอง

**ข้อจำกัด:** GitHub commit เปลี่ยนโค้ดที่เก็บใน Repository เท่านั้น
ไม่ Deploy ไป Apps Script เอง; ต้องทำขั้นตอน Manage deployments ด้วยบัญชี
Google ที่มีสิทธิ์ใน Script Project นั้น
