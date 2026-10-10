/**
 * SA Sathorn: read-only monthly B:P feed (October and November in Oct 2026).
 *
 * IMPORTANT: Deploy the ONE script below as a new version of the EXISTING
 * Apps Script Web App (/exec), rather than creating a competing Web App URL.
 *
 * Data stays in Google Sheets. Snapshot comparisons, event delivery and the
 * -10 minute / on-time reminders happen in the existing Supabase workers.
 *
 * Keep only one doGet() entrypoint in the deployed Apps Script project.
 */
const SA_SPREADSHEET_ID = "1sgOwVDEe1kSgnc21bP4h8_42IPAAJFWVC0GUNVUVxyc";
const SA_API_VERSION = "sa-sathorn-all-month-v6.2";
const SA_TIMEZONE = "Asia/Bangkok";
const SA_HEADER_ROW = 2;
const SA_DATA_START_ROW = 3;
const SA_START_COLUMN = 2; // B
const SA_COLUMNS = 15;    // B:P
const SA_MERGED_DATE_COLUMN = 4; // D

const SA_THAI_MONTHS = {
  "ม.ค.": 1, "มกราคม": 1, "ก.พ.": 2, "กุมภาพันธ์": 2,
  "มี.ค.": 3, "มีนาคม": 3, "เม.ย.": 4, "เมษายน": 4,
  "พ.ค.": 5, "พฤษภาคม": 5, "มิ.ย.": 6, "มิถุนายน": 6,
  "ก.ค.": 7, "กรกฎาคม": 7, "ส.ค.": 8, "สิงหาคม": 8,
  "ก.ย.": 9, "กันยายน": 9, "ต.ค.": 10, "ตุลาคม": 10,
  "พ.ย.": 11, "พฤศจิกายน": 11, "ธ.ค.": 12, "ธันวาคม": 12
};

function saDateKey_(actual, display) {
  function valid(year, month, day) {
    if (year > 2400) year -= 543;
    // Thai short year 69 means BE 2569 (AD 2026).
    if (year < 100) year = year >= 43 ? year + 1957 : year + 2000;
    if (year < 1900 || month < 1 || month > 12 || day < 1 || day > 31) return "";
    const dt = new Date(Date.UTC(year, month - 1, day));
    if (dt.getUTCFullYear() !== year ||
        dt.getUTCMonth() + 1 !== month ||
        dt.getUTCDate() !== day) return "";
    return [year, String(month).padStart(2, "0"), String(day).padStart(2, "0")].join("-");
  }

  // Google Sheets sometimes converts 10.10.69 into an underlying AD 2069
  // Date. Trust the visible two-digit Thai year rather than that Date.
  const shown = String(display == null ? "" : display).trim();
  const short = shown.match(/^(\d{1,2})[\/.-](\d{1,2})[\/.-](\d{2})$/);
  if (short) {
    return valid(Number(short[3]), Number(short[2]), Number(short[1]));
  }

  if (Object.prototype.toString.call(actual) === "[object Date]" &&
      !isNaN(actual.getTime())) {
    return Utilities.formatDate(actual, SA_TIMEZONE, "yyyy-MM-dd");
  }

  const text = shown || String(actual == null ? "" : actual).trim();
  if (!text) return "";

  const match = text.match(/(\d{1,4})[\/.-](\d{1,2})[\/.-](\d{1,4})/);
  if (match) {
    const a = Number(match[1]), b = Number(match[2]), c = Number(match[3]);
    return match[1].length === 4 ? valid(a, b, c) : valid(c, b, a);
  }

  const thai = text.match(/^(\d{1,2})\s+(\S+)\s+(\d{2,4})/);
  if (thai) {
    return valid(Number(thai[3]), SA_THAI_MONTHS[thai[2]] || 0, Number(thai[1]));
  }
  return "";
}

function saMonthTabs_() {
  // Arithmetic by year/month avoids ambiguity around Apps Script's timezone.
  const year = Number(Utilities.formatDate(new Date(), SA_TIMEZONE, "yyyy"));
  const month = Number(Utilities.formatDate(new Date(), SA_TIMEZONE, "M"));
  const nextMonth = month === 12 ? 1 : month + 1;
  const nextYear = month === 12 ? year + 1 : year;
  return [month + "." + year, nextMonth + "." + nextYear];
}

function saReadRows_() {
  const book = SpreadsheetApp.openById(SA_SPREADSHEET_ID);
  const tabs = saMonthTabs_();
  const all = [];

  tabs.forEach(function (name) {
    const sheet = book.getSheetByName(name);
    // Fail rather than send a partial/empty set which could generate
    // thousands of false DELETE events in Central.
    if (!sheet) throw new Error("Missing SA tab: " + name);
    const last = sheet.getLastRow();
    if (last < SA_DATA_START_ROW) return;

    const n = last - SA_DATA_START_ROW + 1;
    const headers = sheet.getRange(SA_HEADER_ROW, SA_START_COLUMN, 1, SA_COLUMNS)
      .getDisplayValues()[0];
    const shown = sheet.getRange(SA_DATA_START_ROW, SA_START_COLUMN, n, SA_COLUMNS)
      .getDisplayValues();
    const dateRange = sheet.getRange(SA_DATA_START_ROW, SA_MERGED_DATE_COLUMN, n, 1);
    const dates = dateRange.getValues();

    const inherited = {};
    const ranges = {};
    // IMPORTANT: no extra Sheet read per merged group in the common case.
    // Reading 100s of top-left cells one-by-one is extremely slow in GAS.
    dateRange.getMergedRanges().forEach(function (merge) {
      const top = merge.getRow();
      const first = Math.max(top, SA_DATA_START_ROW);
      const final = Math.min(merge.getLastRow(), last);
      if (first > final) return;
      let topValue, topDisplay;
      if (top >= SA_DATA_START_ROW && top <= last) {
        const idx = top - SA_DATA_START_ROW;
        topValue = dates[idx][0];
        topDisplay = shown[idx][SA_MERGED_DATE_COLUMN - SA_START_COLUMN];
      } else {
        const cell = sheet.getRange(top, SA_MERGED_DATE_COLUMN);
        topValue = cell.getValue();
        topDisplay = cell.getDisplayValue();
      }
      const key = saDateKey_(topValue, topDisplay);
      const group = merge.getA1Notation();
      for (let row = first; row <= final; row++) {
        inherited[row] = key;
        ranges[row] = group;
      }
    });

    shown.forEach(function (cells, offset) {
      // Date in Column D may be physically blank because it is merged.
      const hasContent = cells.some(function (value) {
        return String(value == null ? "" : value).trim() !== "";
      });
      if (!hasContent) return;
      const physicalRow = SA_DATA_START_ROW + offset;
      const dateDisplay = String(cells[SA_MERGED_DATE_COLUMN - SA_START_COLUMN] || "").trim();
      const dateKey = Object.prototype.hasOwnProperty.call(inherited, physicalRow)
        ? inherited[physicalRow]
        : saDateKey_(dates[offset][0], dateDisplay);

      const detail = cells.map(function (value, index) {
        return {
          column: String.fromCharCode(66 + index),
          header: String(headers[index] || String.fromCharCode(66 + index)),
          value: String(value == null ? "" : value).trim()
        };
      });

      all.push({
        sheet: name,
        row: physicalRow,
        appointment_date: dateKey,
        appointment_date_display: dateDisplay,
        group_date: dateKey,
        appointment_time: String(cells[0] || "").trim(), // B
        sequence: String(cells[1] || "").trim(),         // C
        in_merged_date_group: Object.prototype.hasOwnProperty.call(ranges, physicalRow),
        merged_range: ranges[physicalRow] || "",
        customer: String(cells[3] || "").trim(),         // E
        plate: String(cells[4] || "").trim(),            // F
        model: String(cells[6] || "").trim(),            // H
        row_data: detail
      });
    });
  });

  return { tabs: tabs, rows: all };
}

function doGet(e) {
  try {
    const action = String((e && e.parameter && e.parameter.action) || "changes")
      .trim().toLowerCase();
    if (action === "ping") {
      // Ping never reads the Spreadsheet, so connectivity stays responsive.
      return saJson_({
        success: true, ok: true, action: "ping", version: SA_API_VERSION,
        mode: "all_month_rows_v6", monitored_sheets: saMonthTabs_()
      });
    }
    if (action !== "changes") throw new Error("Unknown action: " + action);

    const result = saReadRows_();
    return saJson_({
      success: true, ok: true, action: "changes",
      version: SA_API_VERSION, mode: "all_month_rows_v6",
      timezone: SA_TIMEZONE,
      today: Utilities.formatDate(new Date(), SA_TIMEZONE, "yyyy-MM-dd"),
      monitored_sheets: result.tabs,
      found_sheets: result.tabs,
      count: result.rows.length,
      rows: result.rows
    });
  } catch (error) {
    return saJson_({
      success: false, ok: false,
      version: SA_API_VERSION, error: String(error)
    });
  }
}

function saJson_(data) {
  return ContentService.createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}
