# GAS แจ้งเตือน Google Sheets: 04-红牌ชีตnew

**Google Sheets:** https://docs.google.com/spreadsheets/d/1aC1NFxBfqDg4zkC1-y-vDYmIUpqTqegb/edit?gid=1947537691

- Spreadsheet ID: `1aC1NFxBfqDg4zkC1-y-vDYmIUpqTqegb`
- แท็บ: `04-红牌ชีตnew`
- GID: `1947537691`
- GAS Source: [red_plate_new_notify.gs](red_plate_new_notify.gs)
- Regression test: [test_red_plate_gas.cjs](../tests/test_red_plate_gas.cjs)
- Central formatter: `supabase/functions/dailylog-monitor-worker/index.ts` (v19)

## ติดตั้ง

1. ใช้บัญชีที่เข้าถึงชีตนี้ได้ เข้า [Google Apps Script](https://script.google.com) แล้วสร้าง **โปรเจ็กต์ใหม่** แยกจาก GAS ของ SA/Sale เพื่อไม่ให้มี `doGet()` ซ้ำ
2. คัดลอกโค้ดใน `red_plate_new_notify.gs` ไปวางเป็น `Code.gs` และบันทึก
3. Run `inspectRedPlateHeaders()` เพื่อตรวจเลขแถวหัวข้อ (HEADER_ROW) และชื่อคอลัมน์จาก Execution log; หากไม่ตรง ปรับ `RP_CONFIG.HEADER_ROW` ก่อนสร้าง Snapshot
4. Run `setupRedPlateMonitor()` เพื่อสร้าง Snapshot เริ่มต้นบน **Drive ส่วนตัว** และ Token; ไม่มีการแจ้งเตือนข้อมูลเก่าย้อนหลัง
5. Deploy → **New deployment → Web app** → Execute as **Me** → Who has access **Anyone** (เพราะ Central Worker ไม่มี Google sign-in) — URL มี **Token** บังคับ จึงไม่ควรเปิดเผยต่อบุคคลภายนอก
6. Run `showRedPlateWebAppUrl()` จากนั้นคัดลอก URL ส่วนตัว `https://script.google.com/macros/s/.../exec?token=...` จาก Execution log
7. ตรวจ URL โดยเติม `&action=ping` หลัง URL ต้องได้ `ok:true` พร้อม `sheet`, `gid`, `header_row` และชื่อ `headers`
8. ใน **DailyLog → Main Notification Sources → New** ตั้งชื่อเช่น **04-红牌ชีตnew (Red Plate)**, ใส่ URL /exec ที่มี token, ติ๊ก **Enable monitoring** และ **Show this Source in DailyLogNotify**, Test Connection → Save
9. ใน **DailyLogNotify → Notification Sources → Refresh Sources** ติ๊กชื่อ Source นี้แล้ว Save บนเครื่องที่ต้องการรับ

> ผู้ใช้ต้อง Deploy GAS ด้วยบัญชี Google ของตนเองก่อน เราไม่สามารถสร้าง URL Web App จากเพียงลิงก์ `docs.google.com/spreadsheets` ได้

## พฤติกรรม

- **เพิ่มแถว:** แจ้งเลขแถว และคู่ `A - ชื่อหัวคอลัมน์: ค่า` ทุกคอลัมน์ที่มีข้อมูลในแถวนั้น
- **แก้ไขเซลล์:** แจ้งเลขแถว + คอลัมน์ + ค่าเดิม → ค่าใหม่
- **ล้างค่าเซลล์:** แจ้งเป็น `ลบ ค่าเดิม` ในเหตุการณ์แก้ไข
- **ลบแถว:** แจ้งตำแหน่งแถวเดิมพร้อมค่าของคอลัมน์ที่ถูกลบ
- **แก้ชื่อหัวคอลัมน์:** แจ้งชื่อเดิมและชื่อใหม่

GAS ใช้ `getDisplayValues()` อ่านข้อมูลและชื่อคอลัมน์จริง ไม่ตั้งชื่อหัวคอลัมน์ตามการคาดเดา อ่านทั้งชีตเป้าหมาย ไม่อ่านแท็บอื่น และไม่แก้ข้อมูลต้นฉบับ มี Snapshot และคิว retry บน Google Drive ส่วนตัวของผู้ Deploy

การแจ้งเตือนเป็น **polling ตามรอบ Central ประมาณ 5 นาที** ไม่ใช่ onEdit แบบทันที; การแก้แล้วเปลี่ยนกลับภายในรอบอาจตรวจไม่พบ หากแถวไม่มี VIN/เลขทะเบียนเฉพาะตัว การแทรก/ย้ายแถวและแก้ข้อมูลพร้อมกันอาจแยก Edit กับ Delete+Add ได้ไม่สมบูรณ์

**การรักษาความลับ:** ไฟล์ GAS ใช้ Secret Token ใน URL ที่เก็บใน Script Properties; อย่านำ URL ที่มี token ไปแชร์ภายนอก เพราะสามารถใช้เข้าถึงข้อมูลใน API ได้

**สำคัญ:** บัญชีที่ Deploy ต้องมีสิทธิ์อ่าน Google Sheet และองค์กรต้องอนุญาต Web App ที่เข้าถึงได้จาก Central. บาง Workspace อาจบังคับนโยบายที่ทำให้การ Deploy เป็น Anyone ใช้ไม่ได้
