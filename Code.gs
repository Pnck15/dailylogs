function testReadSheetData() {
  const spreadsheetId = "1qsVq4gp_dxQXytCv4-lFIpvrKlVmyVV4zjEgfvs0JtI";

  const spreadsheet = SpreadsheetApp.openById(spreadsheetId);

  const sheet = spreadsheet.getSheetByName("Delivery 2026");

  if (!sheet) {
    throw new Error("ไม่พบ Sheet: Delivery 2026");
  }

  const lastRow = sheet.getLastRow();
  const lastColumn = sheet.getLastColumn();

  Logger.log("Sheet: " + sheet.getName());
  Logger.log("จำนวนแถว: " + lastRow);
  Logger.log("จำนวนคอลัมน์: " + lastColumn);

  // อ่าน 10 แถวแรก
  const rowsToRead = Math.min(10, lastRow);

  const data = sheet
    .getRange(1, 1, rowsToRead, lastColumn)
    .getDisplayValues();

  data.forEach(function(row, index) {
    Logger.log("Row " + (index + 1) + ": " + JSON.stringify(row));
  });
}

function testReadDeliveryData() {
  const spreadsheetId = "1qsVq4gp_dxQXytCv4-lFIpvrKlVmyVV4zjEgfvs0JtI";

  const spreadsheet = SpreadsheetApp.openById(spreadsheetId);

  const sheet = spreadsheet.getSheetByName("Delivery 2026");

  if (!sheet) {
    throw new Error("ไม่พบ Sheet: Delivery 2026");
  }

  const lastRow = sheet.getLastRow();

  // อ่านตั้งแต่ Column D (4) ถึง L (12) รวม 9 คอลัมน์
  const data = sheet
    .getRange(1, 4, lastRow, 9)
    .getDisplayValues();

  Logger.log("Sheet: " + sheet.getName());
  Logger.log("จำนวนข้อมูล: " + (lastRow - 1));

  // เริ่มจาก Row 2 เพราะ Row 1 เป็น Header
  for (let i = 1; i < data.length; i++) {

    const rowNumber = i + 1;

    const model = data[i][0];        // Column D (Car Model)
    const vin = data[i][2];          // Column F (VIN)
    const customer = data[i][4];     // Column H (Customer)
    const sale = data[i][6];         // Column J (Sale)
    const payDay = data[i][7];       // Column K (Pay Day)
    const deliveryDate = data[i][8]; // Column L (Delivery Date)

    Logger.log(
      JSON.stringify({
        row: rowNumber,
        model: model,
        vin: vin,
        customer: customer,
        sale: sale,
        pay_day: payDay,
        delivery_date: deliveryDate
      })
    );
  }
}

function getDeliveryData() {
  const spreadsheetId = "1qsVq4gp_dxQXytCv4-lFIpvrKlVmyVV4zjEgfvs0JtI";

  const spreadsheet = SpreadsheetApp.openById(spreadsheetId);

  const sheet = spreadsheet.getSheetByName("Delivery 2026");

  if (!sheet) {
    throw new Error("ไม่พบ Sheet: Delivery 2026");
  }

  const lastRow = sheet.getLastRow();

  if (lastRow < 2) {
    return [];
  }

  // อ่านตั้งแต่ Column D (4) ถึง L (12) จำนวน 9 คอลัมน์
  const data = sheet
    .getRange(2, 4, lastRow - 1, 9)
    .getDisplayValues();

  const result = [];

  for (let i = 0; i < data.length; i++) {

    const row = i + 2;

    const model = data[i][0];        // Column D (Car Model)
    const vin = data[i][2];          // Column F (VIN)
    const customer = data[i][4];     // Column H (Customer)
    const sale = data[i][6];         // Column J (Sale)
    const payDay = data[i][7];       // Column K (Pay Day)
    const deliveryDate = data[i][8]; // Column L (Delivery Date)

    result.push({
      row: row,
      model: model,
      vin: vin,
      customer: customer,
      sale: sale,
      pay_day: payDay,
      delivery_date: deliveryDate
    });
  }

  return result;
}

function testGetDeliveryData() {

  const result = getDeliveryData();

  Logger.log("จำนวนรายการ: " + result.length);

  // แสดงแค่ 5 รายการแรก
  const sample = result.slice(0, 5);

  Logger.log(JSON.stringify(sample, null, 2));
}

function doGet(e) {
  const data = getDeliveryData();

  return ContentService
    .createTextOutput(JSON.stringify({
      ok: true,
      success: true,
      count: data.length,
      rows: data,
      data: data
    }))
    .setMimeType(ContentService.MimeType.JSON);
}
