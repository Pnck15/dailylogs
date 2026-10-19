# RedPlateNotify: อ่านไฟล์ .xlsx ด้วยสิทธิ์ Viewer (v1.1)

**สถานะ:** โค้ดรองรับการอ่าน Excel แบบ Read-only แล้ว แต่ยังต้องคัดลอก GAS ไป Deploy ด้วยบัญชีที่มีสิทธิ์ Viewer และนำ URL พร้อม Token ไปบันทึกใน DailyLog. **การแก้โค้ดใน GitHub ไม่ได้อัปเดต Apps Script Deployment โดยอัตโนมัติ**

- ต้นทาง: `1aC1NFxBfqDg4zkC1-y-vDYmIUpqTqegb`, ชื่อ `GACB-发票登记表20250318(Customer ).xlsx`
- แท็บที่จะติดตาม: `04-红牌ชีตnew` (ลิงก์ Google Sheets แสดง gid `1947537691`; ในโครงสร้าง Excel ระบุด้วย **ชื่อแท็บ**)
- อ่านเฉพาะข้อมูลจากไฟล์ต้นฉบับด้วย `DriveApp.getFileById(...).getBlob()` และ `Utilities.unzip()`; ไม่ต้องมีสิทธิ์ Editor
- ตรวจจับเพิ่มแถว, ลบแถว, แก้ไขค่าเซลล์ และแก้ไขชื่อหัวคอลัมน์ พร้อมเลขคอลัมน์/แถวและค่าเดิม → ค่าใหม่
- ขยายขอบเขตเป็น 260 คอลัมน์ (ข้อมูลจริงในแท็บนี้พบถึงคอลัมน์ที่ 253); ส่วน Snapshot/Queue บันทึกไว้ใน **ไฟล์ส่วนตัวของบัญชีที่ Deploy** เท่านั้น
- เช็คการแก้ไขจาก Last modified ของไฟล์ก่อนแกะ Excel เพื่อไม่ต้องอ่าน ZIP 28 MB ทุกครั้งที่ไฟล์ไม่เปลี่ยน
- การใช้งานครั้งแรกสร้าง Baseline และ **ไม่ย้อนแจ้งเตือนการแก้ไขในอดีต**; แจ้งเฉพาะการเปลี่ยนแปลงหลังตั้ง Baseline
- ต้องมีสิทธิ์ Viewer **และดาวน์โหลดไฟล์ได้** ในบัญชีที่ Deploy GAS; หากเจ้าของปิด Download/Copy ระบบจะอ่าน Blob ไม่ได้
- Apps Script จำกัดเวลาโดยทั่วไปไม่เกิน 6 นาทีต่อคำขอ จึงต้องตรวจ Performance กับไฟล์จริงก่อนเชื่อถือว่าตรวจครบทุก 5 นาที

## วิธีติดตั้งแบบไม่แตะไฟล์ต้นฉบับ

1. เปิด <https://script.google.com/home/projects/create> จากบัญชี Google ที่มีสิทธิ์ Viewer/ดาวน์โหลด Excel นี้ได้
2. สร้าง Apps Script **Standalone Project แยก** (ไม่ต้องเปิด Script Editor จากไฟล์ต้นฉบับ)
3. คัดลอกโค้ดทั้งหมดใน `gas/red_plate_new_notify.gs` ไปใส่ไฟล์ Code.gs ของโปรเจกต์ใหม่นี้
4. Run `inspectRedPlateHeaders()` เพื่อตรวจว่าพบชื่อแท็บ Header แถวเริ่มต้นและคอลัมน์ครบ ไม่มีการเขียนกลับไฟล์ต้นฉบับ
5. Run `setupRedPlateMonitor()` เพื่อสร้าง Snapshot ส่วนตัวและ Secret Token
6. Deploy → New deployment → Web app → Execute as **Me** → Who has access: **Anyone** (Token คุมสิทธิ์) แล้ว Deploy
7. Run `showRedPlateWebAppUrl()` คัดลอก URL เต็ม **`.../exec?token=...`** จาก Execution log ไปใส่ **DailyLog.exe → Main Notification Sources → RedPlate → Test Connection → Save** โดยแก้ Source เดิม (ไม่สร้างชื่อซ้ำ)
8. ตรวจ `action=ping` แล้วให้ Central Poll `action=changes` ทดสอบด้วยการเปลี่ยนค่าจริงในไฟล์ต้นฉบับโดยผู้มีสิทธิ์ Editor เท่านั้น จากนั้นดู `monitor_state.last_success_at` และ Notification Events

คำเตือน: หากมี Source เดิมที่ยังใช้ `?key=...` / `action=status` อย่าใช้ API Key ของสคริปต์เดิมกับโค้ด Standalone ใหม่นี้ เพราะเป็นคนละ API — ใช้ URL `?token=...` ที่ `showRedPlateWebAppUrl()` สร้างเท่านั้น

---
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
