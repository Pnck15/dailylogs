// Offline GAS contract tests: no Google permissions or live Sheet edits.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const code = fs.readFileSync(
  path.join(__dirname, "..", "gas", "sa_sathorn_v6.gs"), "utf8"
);

class FixedDate extends Date {
  constructor(...args) {
    super(...(args.length ? args : ["2026-10-10T05:00:00.000Z"]));
  }
}

function fakeSheet(name) {
  const headers = Array.from({ length: 15 }, (_, i) => "Header " + (i + 2));
  const row = (clock, date, customer) => {
    const result = Array(15).fill("");
    result[0] = clock;    // B
    result[1] = "5";      // C
    result[2] = date;     // D
    result[3] = customer; // E
    result[4] = customer + " Plate"; // F
    return result;
  };
  const shown = name === "10.2026"
    ? [
      row("09.00", "10.10.69", "Sample One"),
      row("09.30", "", "Sample Two"),
      row("10:00", "11/10/2569", "Sample Three"),
    ]
    : [row("08:15", "01/11/2569", "Sample Four")];

  const actualD = shown.map((r) => [r[2]]);
  // Google Sheets can store short Thai year "69" as an underlying AD 2069
  // Date even though the visible date means BE 2569 = AD 2026.
  if (name === "10.2026") {
    actualD[0] = [new Date("2069-10-10T00:00:00.000Z")];
  }
  const merges = name === "10.2026" ? [{
    getRow: () => 3,
    getLastRow: () => 4,
    getA1Notation: () => "D3:D4",
  }] : [];

  return {
    getLastRow() { return shown.length + 2; },
    getRange(start, col, numRows, numCols) {
      if (start === 2 && col === 2 && numRows === 1 && numCols === 15) {
        return { getDisplayValues: () => [headers] };
      }
      if (start === 3 && col === 2 && numRows === shown.length && numCols === 15) {
        return { getDisplayValues: () => shown };
      }
      if (start === 3 && col === 4 && numRows === shown.length && numCols === 1) {
        return { getValues: () => actualD, getMergedRanges: () => merges };
      }
      throw new Error("Unexpected per-cell read: " + name + " row=" + start + ", col=" + col);
    }
  };
}

function harness(missingNovember) {
  let opened = 0;
  const sheets = {
    "10.2026": fakeSheet("10.2026"),
    ...(missingNovember ? {} : { "11.2026": fakeSheet("11.2026") }),
  };
  const context = vm.createContext({
    Date: FixedDate,
    SpreadsheetApp: {
      openById() {
        opened++;
        return { getSheetByName(name) { return sheets[name] || null; } };
      },
    },
    Utilities: {
      formatDate(input, tz, fmt) {
        assert.equal(tz, "Asia/Bangkok");
        const date = new Date(input);
        const parts = Object.fromEntries(
          new Intl.DateTimeFormat("en-US", {
            timeZone: tz, year: "numeric", month: "numeric", day: "2-digit",
          }).formatToParts(date).map(p => [p.type, p.value])
        );
        if (fmt === "yyyy") return parts.year;
        if (fmt === "M") return String(Number(parts.month));
        if (fmt === "yyyy-MM-dd") {
          return parts.year + "-" + String(parts.month).padStart(2, "0") + "-" + parts.day;
        }
        throw new Error("Unexpected format " + fmt);
      },
    },
    ContentService: {
      MimeType: { JSON: "application/json" },
      createTextOutput(text) {
        return {
          text,
          setMimeType(type) { this.mimeType = type; return this; }
        };
      }
    },
  });
  vm.runInContext(code, context, { filename: "sa_sathorn_v6.gs" });
  return {
    run(action = "changes") {
      return JSON.parse(context.doGet({ parameter: { action } }).text);
    },
    get opened() { return opened; },
  };
}

const happy = harness(false);
const ping = happy.run("ping");
assert.equal(ping.ok, true);
assert.equal(ping.action, "ping");
assert.equal(ping.version, "sa-sathorn-all-month-v6.2");
assert.equal(happy.opened, 0, "ping must never scan the spreadsheet");

const feed = happy.run();
assert.equal(feed.ok, true);
assert.equal(feed.mode, "all_month_rows_v6");
assert.deepEqual([...feed.monitored_sheets], ["10.2026", "11.2026"]);
assert.equal(feed.count, 4);
assert.equal(feed.rows.length, 4);

const group = feed.rows.filter(x => x.merged_range === "D3:D4");
assert.equal(group.length, 2);
assert.equal(group[0].appointment_date, "2026-10-10");
assert.equal(group[1].appointment_date, "2026-10-10",
  "D4 should inherit the top-left D3 appointment date");
assert.equal(group[1].appointment_time, "09.30");
assert.equal(group[1].row_data[2].value, "",
  "Merged D4 physical cell remains blank for accurate cell diffs");
assert.equal(feed.rows.find(x => x.customer === "Sample Three").appointment_date,
  "2026-10-11");
assert.equal(feed.rows.find(x => x.sheet === "11.2026").appointment_date,
  "2026-11-01");

const missing = harness(true).run();
assert.equal(missing.success, false, "missing a monthly tab must fail");
assert.match(missing.error, /Missing SA tab: 11\.2026/);
assert.ok(!("rows" in missing),
  "Never output partial row data as it could generate false deletions");

console.log("PASS: SA v6 ping, two months, B:P rows, inherited Merged D, no per-group cell reads, safe missing-tab behavior.");
