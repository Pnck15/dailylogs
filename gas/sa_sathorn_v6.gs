/**
 * SA Sathorn v6: all B:P changes in tabs 10.2026 and 11.2026.
 * Merged D supplies the appointment date for each row in its range.
 * Stateless feed: Central Worker owns snapshots, dedupe and reminders.
 * Deploy as a new version of the existing Web App (/exec).
 */
const SPREADSHEET_ID = "1sgOwVDEe1kSgnc21bP4h8_42IPAAJFWVC0GUNVUVxyc";
const VERSION = "sa-sathorn-all-month-v6";
const TABS = ["10.2026", "11.2026"];
const HEADER_ROW = 2;
const DATA_START_ROW = 3;
const START_COLUMN = 2; // B
const COLUMN_COUNT = 15; // B:P
const TIMEZONE = "Asia/Bangkok";

function formatSaDate_(value) {
  if (Object.prototype.toString.call(value) === "[object Date]" && !isNaN(value.getTime())) {
    return Utilities.formatDate(value, TIMEZONE, "yyyy-MM-dd");
  }
  const text = String(value == null ? "" : value).trim();
  if (!text) return "";
  const m = text.match(/(\d{1,4})[\/.-](\d{1,2})[\/.-](\d{1,4})/);
  if (!m) return text;
  let year, month, day;
  if (m[1].length === 4) {
    year = Number(m[1]); month = Number(m[2]); day = Number(m[3]);
  } else {
    day = Number(m[1]); month = Number(m[2]); year = Number(m[3]);
  }
  if (year > 2400) year -= 543;
  if (year < 100) year += 2000;
  if (month < 1 || month > 12 || day < 1 || day > 31) return text;
  return [year, String(month).padStart(2, "0"), String(day).padStart(2, "0")].join("-");
}

function getSaRows_() {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const result = [];
  TABS.forEach(function(tab) {
    const sheet = ss.getSheetByName(tab);
    if (!sheet) throw new Error("Missing SA tab: " + tab);
    const lastRow = sheet.getLastRow();
    if (lastRow < DATA_START_ROW) return;
    const count = lastRow - DATA_START_ROW + 1;
    const headers = sheet.getRange(HEADER_ROW, START_COLUMN, 1, COLUMN_COUNT).getDisplayValues()[0];
    const displays = sheet.getRange(DATA_START_ROW, START_COLUMN, count, COLUMN_COUNT).getDisplayValues();
    const dateRange = sheet.getRange(DATA_START_ROW, 4, count, 1);
    const rawDates = dateRange.getValues();
    const mergedDates = {};
    const mergedMeta = {};
    dateRange.getMergedRanges().forEach(function(range) {
      const first = Math.max(range.getRow(), DATA_START_ROW);
      const last = Math.min(range.getLastRow(), lastRow);
      const groupDate = formatSaDate_(range.getCell(1, 1).getValue());
      const mergedRange = range.getA1Notation();
      for (let row = first; row <= last; row++) {
        mergedDates[row] = groupDate;
        mergedMeta[row] = mergedRange;
      }
    });
    displays.forEach(function(values, index) {
      const rowNumber = DATA_START_ROW + index;
      if (!values.some(function(value) { return String(value).trim() !== ""; })) return;
      const rowData = values.map(function(value, colIndex) {
        return {
          column: String.fromCharCode(66 + colIndex),
          header: headers[colIndex] || String.fromCharCode(66 + colIndex),
          value: String(value == null ? "" : value).trim()
        };
      });
      const groupDate = mergedDates[rowNumber] || formatSaDate_(rawDates[index][0]);
      result.push({
        sheet: tab,
        row: rowNumber,
        group_date: groupDate,
        appointment_date: groupDate,
        in_merged_date_group: Boolean(mergedMeta[rowNumber]),
        merged_range: mergedMeta[rowNumber] || "",
        appointment_time: String(values[0] || "").trim(),
        sequence: String(values[1] || "").trim(),
        customer: String(values[3] || "").trim(),
        plate: String(values[4] || "").trim(),
        model: String(values[6] || "").trim(),
        row_data: rowData
      });
    });
  });
  return result;
}

function doGet(e) {
  try {
    const action = e && e.parameter && e.parameter.action || "changes";
    if (action === "ping") return saJson_({
      ok: true, success: true, action: "ping", version: VERSION, tabs: TABS
    });
    if (action !== "changes") throw new Error("Unknown action: " + action);
    const rows = getSaRows_();
    return saJson_({
      ok: true,
      success: true,
      version: VERSION,
      mode: "all_month_rows_v6",
      today: Utilities.formatDate(new Date(), TIMEZONE, "yyyy-MM-dd"),
      count: rows.length,
      rows: rows
    });
  } catch (error) {
    return saJson_({ ok: false, success: false, error: String(error) });
  }
}

function saJson_(payload) {
  return ContentService.createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}
