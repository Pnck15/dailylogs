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
  ["normalizeSaRowDate", "diffSaFullRow", "saRowSignature"]
);
const reminder = loadFunctions(
  "supabase/functions/dailylog-sa-reminder-worker/index.ts",
  ["appointmentDateForSaRow", "dateKeyFromText", "parseAppointmentMinutes"]
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
console.log("PASS: SA BE69/AD2026 reminder schedule date and safe snapshot normalization.");
