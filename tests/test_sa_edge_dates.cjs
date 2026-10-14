// Offline regression for the live SA date-fix source code.
// Transpiles the actual Edge Function modules; never calls Supabase.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const esbuild = require("esbuild");

function loadFunctions(relativePath, names) {
  const filename = path.join(__dirname, "..", relativePath);
  const source = fs.readFileSync(filename, "utf8")
    .replace(/^import .*;\s*$/gm, "") +
    "\n globalThis.__functions = {" + names.join(",") + "};";
  const compiled = esbuild.transformSync(source, {
    loader: "ts", format: "iife", target: "es2022"
  }).code;
  const context = vm.createContext({
    Deno: {
      env: { get: () => "test-config-not-used" },
      serve: () => {},
    },
    createClient: () => ({}),
    Intl, Date, console, URL, Response, Set, Map,
  });
  vm.runInContext(compiled, context, { filename });
  return context.__functions;
}

const monitor = loadFunctions(
  "supabase/functions/dailylog-monitor-worker/index.ts",
  ["normalizeSaRowDate", "diffSaFullRow", "saRowSignature", "formatSaFullRow", "displaySaChanges", "saScheduleContext"]
);
const reminder = loadFunctions(
  "supabase/functions/dailylog-sa-reminder-worker/index.ts",
  ["appointmentDateForSaRow", "dateKeyFromText", "parseAppointmentMinutes", "formatFullRow"]
);

const example = {
  sheet: "10.2026",
  row: 95,
  appointment_date: "2069-10-10",
  group_date: "2069-10-10",
  merged_range: "D89:D97",
  in_merged_date_group: true,
  appointment_time: "13:30",
  sequence: "6",
  plate: "sample-plate",
  row_data: [
    { column: "B", header: "预约时间", value: "13:30" },
    { column: "D", header: "วันที่", value: "" },
  ],
};
const fixed = monitor.normalizeSaRowDate(example);
assert.equal(fixed.appointment_date, "2026-10-10");
assert.equal(fixed.group_date, "2026-10-10");
assert.equal(example.appointment_date, "2069-10-10",
  "must not mutate the incoming snapshot");
assert.equal(fixed.row_data[1].value, "",
  "physically merged child D cell remains unmodified");
assert.equal(reminder.appointmentDateForSaRow(example), "2026-10-10");
assert.equal(reminder.appointmentDateForSaRow(fixed), "2026-10-10");
assert.equal(reminder.dateKeyFromText("10.10.69"), "2026-10-10");
assert.equal(reminder.parseAppointmentMinutes("13:30"), 13*60+30);
assert.equal(reminder.parseAppointmentMinutes("13.30"), 13*60+30);
assert.deepEqual(
  [...monitor.diffSaFullRow(
    monitor.normalizeSaRowDate(example),
    monitor.normalizeSaRowDate({ ...example })
  )],
  [],
  "normalizing both sides must not publish 428 false edits"
);
assert.equal(
  monitor.saRowSignature(monitor.normalizeSaRowDate(example)),
  monitor.saRowSignature(monitor.normalizeSaRowDate({ ...example })),
  "the dedupe signature remains stable"
);
assert.equal(
  monitor.normalizeSaRowDate({
    ...example, appointment_date: "2026-10-10",
    group_date: "2026-10-10"
  }).appointment_date,
  "2026-10-10",
  "valid AD dates must remain unchanged"
);
assert.equal(
  monitor.normalizeSaRowDate({
    ...example, appointment_date: "2030-10-10",
    group_date: "2030-10-10"
  }).appointment_date,
  "2030-10-10",
  "unrelated dates must remain unchanged"
);
// SA metadata is still used internally, but not shown in notification text.
const displayRow = {
  ...example,
  row_data: [
    {column: "B", header: "เวลานัดหมาย 预约时间", value: "13:30"},
    {column: "C", header: "ลำดับ 序号", value: "7"},
    {column: "D", header: "วันที่ 日期", value: ""},
    {column: "E", header: "ลูกค้า", value: "ตัวอย่าง"},
  ]
};
for (const fullMessage of [
  monitor.formatSaFullRow(displayRow),
  reminder.formatFullRow(displayRow)
]) {
  assert.ok(fullMessage.includes("E - ลูกค้า: ตัวอย่าง"));
  assert.ok(fullMessage.includes("B - เวลานัดหมาย 预约时间: 13:30"));
  assert.ok(!fullMessage.includes("C - ลำดับ"),
    "user must not see technical sequence C field");
}
const internalChanges = [
  "C - ลำดับ 序号: 6 → 7",
  "E - ลูกค้า: ชื่อเดิม → ตัวอย่าง"
];
assert.equal(
  monitor.displaySaChanges(internalChanges),
  "E - ลูกค้า: ชื่อเดิม → ตัวอย่าง"
);
assert.equal(
  monitor.displaySaChanges(["C - ลำดับ 序号: 6 → 7"]),
  "ข้อมูลภายในรายการมีการเปลี่ยนแปลง",
  "C-only edits must still publish a notification without disclosing C"
);
assert.ok(
  !monitor.formatSaFullRow(displayRow).includes("Merged D:"),
  "merged D range must never be user-visible"
);

const mergedChild = monitor.normalizeSaRowDate({
  ...displayRow,
  row: 95,
  sheet: "10.2026",
  appointment_date: "2069-10-10",
  group_date: "2069-10-10",
  appointment_time: "13:30",
  merged_range: "D89:D97",
  in_merged_date_group: true,
});
const scheduleText = monitor.saScheduleContext(mergedChild);
assert.ok(scheduleText.includes("วันที่นัดหมาย: 2026-10-10"),
  "inherited merged D date must be visible even when physical row D is blank");
assert.ok(scheduleText.includes("    เวลานัดหมาย: 13:30"),
  "time for the changed row must accompany the group date");
assert.ok(!scheduleText.includes("D89:D97"),
  "internal merged range must not be included in the popup");
const movedDay = {...mergedChild, group_date: "2026-10-11",
  appointment_date: "2026-10-11", appointment_time: "14:00"};
const moved = monitor.saScheduleContext(movedDay, mergedChild);
assert.ok(moved.includes("2026-10-10 → 2026-10-11"),
  "changes to inherited group date show old and new date");
assert.ok(moved.includes("13:30 → 14:00"),
  "changes to time show old and new time");
const edgeSource = fs.readFileSync(
  path.join(__dirname, "..", "supabase/functions/dailylog-monitor-worker/index.ts"),
  "utf8"
);
for (const expr of [
  "+ saScheduleContext(row, old)",
  "+ saScheduleContext(row)",
  "+ saScheduleContext(old)",
]) {
  assert.ok(edgeSource.includes(expr),
    "SA edit/new/delete must all include date context: " + expr);
}

console.log("PASS: SA merged-D date and row time in edit/new/delete; no range leak.");
