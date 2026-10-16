// Regression for generic red-plate events: exact row + column/header context.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const esbuild = require("esbuild");

const filename = path.join(
  __dirname, "..", "supabase/functions/dailylog-monitor-worker/index.ts"
);
const source = fs.readFileSync(filename, "utf8");
const js = esbuild.transformSync(
  source.replace(/^import .*;\s*$/gm, "") +
  "\n globalThis.__exports={redPlateEventMessage,redPlateFieldLabel};",
  {loader:"ts", format:"iife", target:"es2022"}
).code;
const env = vm.createContext({
  Deno:{env:{get:()=>"test-value"}, serve:()=>{}},
  createClient:()=>({}), Intl,Date,console,URL,Response,Set,Map
});
vm.runInContext(js, env, {filename});
const formatter=env.__exports.redPlateEventMessage;
const added={
  schema:"red_plate_monitor_v1",event_id:"test-add-001",
  type:"add",sheet:"04-红牌ชีตnew",row:12,
  fields:[
    {column:"A",header:"ลำดับ",value:"3"},
    {column:"B",header:"เลข VIN",value:"VIN123"},
    {column:"C",header:"ชื่อลูกค้า",value:"ทดสอบ"},
    {column:"D",header:"เลขทะเบียน",value:"กก 123"}
  ],changed_cells:[]
};
const addText=formatter(added);
assert.ok(addText.includes("แท็บ: 04-红牌ชีตnew"));
assert.ok(addText.includes("แถว: 12"));
assert.ok(addText.includes("B - เลข VIN: VIN123"));
assert.ok(addText.includes("C - ชื่อลูกค้า: ทดสอบ"));
assert.ok(addText.includes("D - เลขทะเบียน: กก 123"));
const edited={
  schema:"red_plate_monitor_v1",event_id:"test-edit-001",
  type:"edit",sheet:"04-红牌ชีตnew",row:12,old_row:11,
  changed_cells:[
    {column:"C",header:"ชื่อลูกค้า",before:"ก่อนแก้",after:"หลังแก้"},
    {column:"E",header:"สถานะ",before:"",after:"รับแล้ว"},
    {column:"D",header:"ทะเบียน",before:"กก 123",after:""}
  ]
};
const editText=formatter(edited);
assert.ok(editText.includes("แถว: 12 (ก่อนหน้าแถว 11)"));
assert.ok(editText.includes("C - ชื่อลูกค้า: ก่อนแก้ → หลังแก้"));
assert.ok(editText.includes("E - สถานะ: เพิ่ม รับแล้ว"));
assert.ok(editText.includes("D - ทะเบียน: ลบ กก 123"));
assert.ok(formatter({...added,type:"delete"}).includes("ข้อมูลที่ถูกลบ"));
assert.ok(formatter({...edited,type:"header_edit"}).includes("หัวคอลัมน์ที่เปลี่ยน"));
assert.ok(source.includes('normalize(event.schema) === "red_plate_monitor_v1"'));
assert.ok(source.includes('eventType === "add"'));
assert.ok(source.includes('eventType === "delete"'));
assert.ok(source.includes('redPlateEventMessage(event)'));
assert.ok(source.includes('JSON.stringify(event, null, 2)'),
  "Other generic GAS monitors must remain unchanged");
console.log("PASS: red-plate row/column header formatting, add/edit/delete and generic compatibility.");
