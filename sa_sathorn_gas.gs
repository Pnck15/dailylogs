const SA_SPREADSHEET_ID = "1sgOwVDEe1kSgnc21bP4h8_42IPAAJFWVC0GUNVUVxyc";

const SA_API_VERSION = "sa-sathorn-month-tabs-v6";
const SA_TIMEZONE = "Asia/Bangkok";

const SA_START_COLUMN = 2; // B
const SA_END_COLUMN = 16;  // P
const SA_HEADER_ROW = 2;
const SA_DATA_START_ROW = 3;
const SA_DATE_COLUMN = 4;  // D
const SA_TIME_COLUMN = 2;  // B

/**
 * SA Sathorn v6
 *
 * - Reads the current month tab and the next month tab.
 *   Example in October 2026: 10.2026 + 11.2026.
 * - Returns every non-empty B:P row so Central can detect
 *   add/edit/delete anywhere in those monthly tabs.
 * - Detects merged groups in column D and propagates the merged
 *   appointment date to every row inside that group.
 * - Column B is returned as appointment_time. Central handles
 *   reminders at -10 minutes and at appointment time.
 *
 * This GAS endpoint is READ ONLY. Snapshots/dedupe live in Supabase.
 */

function doGet(e) {
  try {
    const action = (
      e &&
      e.parameter &&
      e.parameter.action
        ? String(e.parameter.action)
        : "changes"
    ).trim().toLowerCase();

    if (action === "ping") {
      return saJsonResponse_({
        success: true,
        ok: true,
        action: "ping",
        version: SA_API_VERSION,
        mode: "month_tabs_full_rows_with_merged_schedule",
        timezone: SA_TIMEZONE,
        monitored_sheets: saMonitoredSheetNames_(),
        timestamp: new Date().toISOString()
      });
    }

    if (action === "changes") {
      return saJsonResponse_(saReadMonthlyRows_());
    }

    return saJsonResponse_({
      success: false,
      ok: false,
      error: "Unknown action: " + action,
      version: SA_API_VERSION
    });
  } catch (error) {
    return saJsonResponse_({
      success: false,
      ok: false,
      error: String(error),
      stack: error && error.stack ? String(error.stack) : "",
      version: SA_API_VERSION
    });
  }
}

function saReadMonthlyRows_() {
  const spreadsheet = SpreadsheetApp.openById(
    SA_SPREADSHEET_ID
  );

  const wantedNames = saMonitoredSheetNames_();
  const rows = [];
  const foundSheets = [];

  wantedNames.forEach(function(sheetName) {
    const sheet = spreadsheet.getSheetByName(sheetName);

    if (!sheet) {
      return;
    }

    foundSheets.push(sheetName);

    const lastRow = sheet.getLastRow();

    if (lastRow < SA_DATA_START_ROW) {
      return;
    }

    const numRows = lastRow - SA_DATA_START_ROW + 1;
    const numColumns = SA_END_COLUMN - SA_START_COLUMN + 1;

    const headers = sheet
      .getRange(
        SA_HEADER_ROW,
        SA_START_COLUMN,
        1,
        numColumns
      )
      .getDisplayValues()[0];

    const displayRows = sheet
      .getRange(
        SA_DATA_START_ROW,
        SA_START_COLUMN,
        numRows,
        numColumns
      )
      .getDisplayValues();

    const actualDateValues = sheet
      .getRange(
        SA_DATA_START_ROW,
        SA_DATE_COLUMN,
        numRows,
        1
      )
      .getValues();

    const dateDisplayValues = sheet
      .getRange(
        SA_DATA_START_ROW,
        SA_DATE_COLUMN,
        numRows,
        1
      )
      .getDisplayValues();

    const mergedDateMap = saMergedDateMap_(
      sheet,
      lastRow
    );

    displayRows.forEach(function(row, index) {
      const rowNumber = SA_DATA_START_ROW + index;

      // Skip fully empty physical rows. If a previously populated row
      // becomes empty, Central will detect that as a deletion.
      const hasData = row.some(function(value) {
        return String(value || "").trim() !== "";
      });

      if (!hasData) {
        return;
      }

      const mergedInfo = mergedDateMap[rowNumber] || null;

      let appointmentDate = "";
      let appointmentDateDisplay = "";
      let mergedRange = "";
      let inMergedDateGroup = false;

      if (mergedInfo) {
        appointmentDate = mergedInfo.date_key;
        appointmentDateDisplay = mergedInfo.display;
        mergedRange = mergedInfo.range;
        inMergedDateGroup = true;
      } else {
        appointmentDate = saDateKey_(
          actualDateValues[index][0],
          dateDisplayValues[index][0]
        );
        appointmentDateDisplay = String(
          dateDisplayValues[index][0] || ""
        ).trim();
      }

      const rowData = row.map(function(value, colIndex) {
        const absoluteColumn = SA_START_COLUMN + colIndex;

        return {
          column: saColumnLetter_(absoluteColumn),
          header: String(headers[colIndex] || "").trim(),
          value: String(value || "").trim()
        };
      });

      rows.push({
        sheet: sheetName,
        row: rowNumber,

        // Stable business fields used by Central reconciliation.
        sequence: String(row[1] || "").trim(), // C
        customer: String(row[3] || "").trim(), // E
        plate: String(row[4] || "").trim(),    // F
        model: String(row[6] || "").trim(),    // H

        appointment_time: String(row[0] || "").trim(), // B
        appointment_date: appointmentDate,
        appointment_date_display: appointmentDateDisplay,

        in_merged_date_group: inMergedDateGroup,
        merged_range: mergedRange,

        row_data: rowData
      });
    });
  });

  return {
    success: true,
    ok: true,
    action: "changes",
    version: SA_API_VERSION,
    mode: "month_tabs_full_rows_with_merged_schedule",
    timezone: SA_TIMEZONE,
    today: Utilities.formatDate(
      new Date(),
      SA_TIMEZONE,
      "yyyy-MM-dd"
    ),
    monitored_sheets: wantedNames,
    found_sheets: foundSheets,
    count: rows.length,
    rows: rows
  };
}

function saMergedDateMap_(sheet, lastRow) {
  const result = {};

  if (lastRow < SA_DATA_START_ROW) {
    return result;
  }

  const dateRange = sheet.getRange(
    SA_DATA_START_ROW,
    SA_DATE_COLUMN,
    lastRow - SA_DATA_START_ROW + 1,
    1
  );

  const mergedRanges = dateRange.getMergedRanges();

  mergedRanges.forEach(function(range) {
    // Only column D date groups are relevant.
    if (
      range.getColumn() > SA_DATE_COLUMN ||
      range.getLastColumn() < SA_DATE_COLUMN
    ) {
      return;
    }

    const startRow = Math.max(
      SA_DATA_START_ROW,
      range.getRow()
    );

    const endRow = Math.min(
      lastRow,
      range.getLastRow()
    );

    const topLeft = sheet.getRange(
      range.getRow(),
      SA_DATE_COLUMN
    );

    const actualValue = topLeft.getValue();
    const displayValue = topLeft.getDisplayValue();

    const dateKey = saDateKey_(
      actualValue,
      displayValue
    );

    for (
      let rowNumber = startRow;
      rowNumber <= endRow;
      rowNumber++
    ) {
      result[rowNumber] = {
        date_key: dateKey,
        display: String(displayValue || "").trim(),
        range: range.getA1Notation()
      };
    }
  });

  return result;
}

function saMonitoredSheetNames_() {
  const now = new Date();

  const currentYear = Number(
    Utilities.formatDate(
      now,
      SA_TIMEZONE,
      "yyyy"
    )
  );

  const currentMonth = Number(
    Utilities.formatDate(
      now,
      SA_TIMEZONE,
      "M"
    )
  );

  const current = new Date(
    currentYear,
    currentMonth - 1,
    1,
    12,
    0,
    0
  );

  const next = new Date(
    currentYear,
    currentMonth,
    1,
    12,
    0,
    0
  );

  return [
    Utilities.formatDate(
      current,
      SA_TIMEZONE,
      "M.yyyy"
    ),
    Utilities.formatDate(
      next,
      SA_TIMEZONE,
      "M.yyyy"
    )
  ];
}

function saDateKey_(actualValue, displayValue) {
  if (
    Object.prototype.toString.call(actualValue) === "[object Date]" &&
    !isNaN(actualValue.getTime())
  ) {
    return Utilities.formatDate(
      actualValue,
      SA_TIMEZONE,
      "yyyy-MM-dd"
    );
  }

  const text = String(
    displayValue || actualValue || ""
  ).trim();

  if (!text) {
    return "";
  }

  const match = text.match(
    /(\d{1,4})[\/\.\-](\d{1,2})[\/\.\-](\d{1,4})/
  );

  if (!match) {
    return "";
  }

  let a = parseInt(match[1], 10);
  const b = parseInt(match[2], 10);
  let c = parseInt(match[3], 10);

  let year;
  let month;
  let day;

  if (match[1].length === 4) {
    year = a > 2400 ? a - 543 : a;
    month = b;
    day = c;
  } else {
    year = c > 2400 ? c - 543 : c;
    if (year < 100) {
      year += 2000;
    }
    month = b;
    day = a;
  }

  if (
    !year ||
    month < 1 ||
    month > 12 ||
    day < 1 ||
    day > 31
  ) {
    return "";
  }

  return (
    String(year).padStart(4, "0") +
    "-" +
    String(month).padStart(2, "0") +
    "-" +
    String(day).padStart(2, "0")
  );
}

function saColumnLetter_(columnNumber) {
  let number = Number(columnNumber);
  let result = "";

  while (number > 0) {
    const remainder = (number - 1) % 26;
    result =
      String.fromCharCode(65 + remainder) +
      result;
    number = Math.floor((number - 1) / 26);
  }

  return result;
}

function saJsonResponse_(data) {
  return ContentService
    .createTextOutput(
      JSON.stringify(data)
    )
    .setMimeType(
      ContentService.MimeType.JSON
    );
}
