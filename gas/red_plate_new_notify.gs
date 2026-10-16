/**
 * DailyLog / Central Notify — Google Sheets Red Plate Monitor, v1.0
 * Spreadsheet: 1aC1NFxBfqDg4zkC1-y-vDYmIUpqTqegb
 * Tab: 04-红牌ชีตnew (gid=1947537691)
 *
 * STANDALONE Apps Script project (do not replace an existing doGet).
 * Read-only access to the source Sheet. Snapshot and retry queue reside in a
 * PRIVATE JSON file in the deploying account's Google Drive.
 *
 * 1) Run setupRedPlateMonitor() once, authorize Sheets + Drive.
 * 2) Deploy as Web App: Execute as Me; Access: Anyone (token protected).
 * 3) Run showRedPlateWebAppUrl() and copy the /exec?token=... URL to
 *    DailyLog > Main Notification Sources > New > Test Connection > Save.
 */
const RP_CONFIG = Object.freeze({
  VERSION: 'red-plate-rows-v1.0',
  SPREADSHEET_ID: '1aC1NFxBfqDg4zkC1-y-vDYmIUpqTqegb',
  SHEET_GID: 1947537691,
  SHEET_NAME: '04-红牌ชีตnew',
  HEADER_ROW: 0,            // 0: detect dynamically; use 1, 2, ... if needed
  DATA_START_ROW: 0,        // 0: row immediately below HEADER_ROW
  MAX_ROWS: 6500,           // fail safely if exceeded; never return partial rows
  MAX_COLUMNS: 70,
  RETENTION_HOURS: 168,     // retry events for 7 days, across Central outages
  DELIVERY_PAGE_SIZE: 75,
  MAX_QUEUED_EVENTS: 3000,
  TOKEN_PROPERTY: 'RP_NOTIFY_SECRET_TOKEN',
  FILE_PROPERTY: 'RP_NOTIFY_PRIVATE_SNAPSHOT_FILE_ID'
});

function rpString_(value) {
  return String(value == null ? '' : value).trim();
}
function rpColumn_(index) {
  var col = '';
  for (var n = index + 1; n > 0; n = Math.floor((n - 1) / 26)) {
    col = String.fromCharCode(65 + (n - 1) % 26) + col;
  }
  return col;
}
function rpJson_(value) {
  return ContentService.createTextOutput(JSON.stringify(value))
    .setMimeType(ContentService.MimeType.JSON);
}
function rpOpenTab_() {
  var book = SpreadsheetApp.openById(RP_CONFIG.SPREADSHEET_ID);
  var tabs = book.getSheets().filter(function (tab) {
    return tab.getSheetId() === RP_CONFIG.SHEET_GID;
  });
  if (tabs.length !== 1 || tabs[0].getName() !== RP_CONFIG.SHEET_NAME) {
    throw new Error('Target tab not found: expected 04-红牌ชีตnew, gid=1947537691. No snapshot modified.');
  }
  return tabs[0];
}
function rpHeaderRow_(display) {
  if (RP_CONFIG.HEADER_ROW > 0) return RP_CONFIG.HEADER_ROW;
  var maxScan = Math.min(display.length, 12);
  var best = { row: 1, score: -Infinity };
  var patterns = /(VIN|เลข|ชื่อ|วันที่|ชำระ|รับ|คืน|ป้าย|ทะเบียน|ลูกค้า|status|date|plate|车|牌|客户|编号|备注|付款|โทร|สถานะ|สี|รุ่น|model|remark|หมายเหตุ)/i;
  for (var i = 0; i < maxScan; i++) {
    var cells = display[i].map(rpString_).filter(Boolean);
    var headerHints = cells.filter(function (v) { return patterns.test(v); }).length;
    var labels = cells.filter(function (v) {
      return v.length <= 45 && !/^[-+]?\d+(?:[.,/-]\d+)*$/.test(v);
    }).length;
    // Strong header words outrank populated data rows; tie -> earlier row.
    var score = headerHints * 8 + labels * 2 + Math.min(cells.length, 18);
    if (score > best.score) best = { row: i + 1, score: score };
  }
  return best.row;
}
function rpKeyColumn_(headers) {
  // Prefer VIN/plate number as stable row identity. Duplicates are handled
  // conservatively by the reconciliation, not forcibly treated as unique.
  var priorities = [
    /(?:^|\b)VIN(?:\b|$)|เลขตัวถัง|车架号|車架號/i,
    /เลขทะเบียน|ทะเบียน|เลขป้าย|หมายเลขป้าย|红牌号码|牌照|plate\s*(?:no|number)/i,
    /(?:^|\b)RO(?:\b|$)|ใบสั่ง|单号|รายการเลขที่/i
  ];
  for (var p = 0; p < priorities.length; p++) {
    for (var col = 0; col < headers.length; col++) {
      if (priorities[p].test(headers[col])) return col;
    }
  }
  return -1;
}
function rpRead_(sheet) {
  var lastRow = sheet.getLastRow();
  var lastCol = sheet.getLastColumn();
  if (lastRow < 1 || lastCol < 1) throw new Error('Target sheet has no headers. Snapshot unchanged.');
  if (lastRow > RP_CONFIG.MAX_ROWS || lastCol > RP_CONFIG.MAX_COLUMNS) {
    throw new Error('Sheet is larger than monitor safety limits. Increase MAX_ROWS/MAX_COLUMNS before retry; snapshot unchanged.');
  }
  var grid = sheet.getRange(1, 1, lastRow, lastCol).getDisplayValues();
  var headerRow = rpHeaderRow_(grid);
  if (headerRow < 1 || headerRow > grid.length) throw new Error('Invalid HEADER_ROW');
  var dataStart = RP_CONFIG.DATA_START_ROW || headerRow + 1;
  if (dataStart <= headerRow) throw new Error('DATA_START_ROW must follow HEADER_ROW');
  var headers = grid[headerRow - 1].map(function (value, idx) {
    return rpString_(value) || 'คอลัมน์ ' + rpColumn_(idx);
  });
  var keyCol = rpKeyColumn_(headers);
  var rows = [];
  for (var r = dataStart - 1; r < grid.length; r++) {
    var values = grid[r].map(rpString_);
    if (!values.some(Boolean)) continue;
    rows.push({ row: r + 1, values: values });
  }
  return {
    sheet: sheet.getName(), gid: sheet.getSheetId(),
    header_row: headerRow, data_start_row: dataStart,
    headers: headers, key_column: keyCol, rows: rows
  };
}
function rpFingerprint_(item) { return JSON.stringify(item.values); }
function rpMatch_(oldRows, newRows, keyCol) {
  var usedOld = {}, usedNew = {}, pairs = [];
  function uniqueMap(rows, getKey) {
    var map = {}, duplicates = {};
    for (var i = 0; i < rows.length; i++) {
      var key = getKey(rows[i]);
      if (!key) continue;
      if (Object.prototype.hasOwnProperty.call(map, key)) duplicates[key] = true;
      else map[key] = i;
    }
    Object.keys(duplicates).forEach(function (key) { delete map[key]; });
    return map;
  }
  function link(a, b) {
    usedNew[a] = true;
    usedOld[b] = true;
    pairs.push([a, b]);
  }
  // 1. Stable unique VIN/plate identity for edited or physically shifted rows.
  if (keyCol >= 0) {
    var stableOld = uniqueMap(oldRows, function (r) { return rpString_(r.values[keyCol]); });
    var stableNew = uniqueMap(newRows, function (r) { return rpString_(r.values[keyCol]); });
    Object.keys(stableNew).forEach(function (key) {
      if (Object.prototype.hasOwnProperty.call(stableOld, key)) {
        link(stableNew[key], stableOld[key]);
      }
    });
  }
  // 2. Identical rows shifted after an insert/delete (no stable key needed).
  var availableOld = uniqueMap(oldRows.map(function (r, i) {
    return usedOld[i] ? { values: ["__already_matched__" + i] } : r;
  }), function (r) { return rpFingerprint_(r); });
  var availableNew = uniqueMap(newRows.map(function (r, i) {
    return usedNew[i] ? { values: ["__already_matched__" + i] } : r;
  }), function (r) { return rpFingerprint_(r); });
  Object.keys(availableNew).forEach(function (key) {
    if (/__already_matched__/.test(key)) return;
    if (Object.prototype.hasOwnProperty.call(availableOld, key)) {
      link(availableNew[key], availableOld[key]);
    }
  });
  // 3. In-place edits not matched above: require some common cell content.
  var oldByRow = {};
  oldRows.forEach(function (row, i) { if (!usedOld[i]) oldByRow[row.row] = i; });
  newRows.forEach(function (row, i) {
    if (usedNew[i] || !Object.prototype.hasOwnProperty.call(oldByRow, row.row)) return;
    var oi = oldByRow[row.row];
    if (usedOld[oi]) return;
    var previous = oldRows[oi];
    var common = 0, occupied = 0;
    for (var c = 0; c < Math.max(previous.values.length, row.values.length); c++) {
      var x = rpString_(previous.values[c]), y = rpString_(row.values[c]);
      if (x || y) occupied++;
      if (x && x === y) common++;
    }
    if (common >= 1 && common / Math.max(occupied, 1) >= 0.30) {
      link(i, oi);
    }
  });
  return { pairs: pairs, added: newRows.map(function (_, i) { return i; }).filter(function (i) { return !usedNew[i]; }),
    deleted: oldRows.map(function (_, i) { return i; }).filter(function (i) { return !usedOld[i]; }) };
}
function rpField_(col, value, headers) {
  return { column: rpColumn_(col), header: rpString_(headers[col]) || 'คอลัมน์ ' + rpColumn_(col), value: rpString_(value) };
}
function rpEvent_(type, row, headers, details, oldRow) {
  return {
    schema: 'red_plate_monitor_v1',
    event_id: Utilities.getUuid(), type: type,
    occurred_at: new Date().toISOString(),
    sheet: RP_CONFIG.SHEET_NAME, gid: RP_CONFIG.SHEET_GID,
    row: row.row, old_row: oldRow ? oldRow.row : null,
    fields: type === 'edit' ? [] : row.values.map(function (v, i) {
      return rpField_(i, v, headers);
    }).filter(function (field) { return Boolean(field.value); }),
    changed_cells: details || []
  };
}
function rpDiff_(previous, current) {
  if (previous.header_row !== current.header_row || previous.data_start_row !== current.data_start_row) {
    throw new Error('Header/data starting row changed. Refusing to generate false row deletions. Correct configuration and baseline manually.');
  }
  var oldRows = previous.rows || [], nowRows = current.rows || [];
  var oldHeaders = previous.headers || [], newHeaders = current.headers || [];
  var result = [], matched = rpMatch_(oldRows, nowRows, current.key_column);
  matched.pairs.forEach(function (indexes) {
    var now = nowRows[indexes[0]], old = oldRows[indexes[1]], details = [];
    for (var c = 0; c < Math.max(now.values.length, old.values.length); c++) {
      var before = rpString_(old.values[c]);
      var after = rpString_(now.values[c]);
      if (before === after) continue;
      details.push({ column: rpColumn_(c), header: newHeaders[c] || oldHeaders[c] || 'คอลัมน์ ' + rpColumn_(c), before: before, after: after });
    }
    if (details.length) result.push(rpEvent_('edit', now, newHeaders, details, old));
  });
  matched.added.forEach(function (i) { result.push(rpEvent_('add', nowRows[i], newHeaders, [])); });
  matched.deleted.forEach(function (i) { result.push(rpEvent_('delete', oldRows[i], oldHeaders, [])); });
  // Header renames should be visible, but must not rewrite unchanged data.
  var headerChanges = [];
  for (var j = 0; j < Math.max(oldHeaders.length, newHeaders.length); j++) {
    if (oldHeaders[j] !== newHeaders[j]) headerChanges.push({
      column: rpColumn_(j), header: 'หัวคอลัมน์', before: rpString_(oldHeaders[j]), after: rpString_(newHeaders[j])
    });
  }
  if (headerChanges.length) result.push(rpEvent_('header_edit', {row: current.header_row, values: []}, newHeaders, headerChanges));
  return result;
}
function rpProperties_() { return PropertiesService.getScriptProperties(); }
function rpReadState_() {
  var id = rpProperties_().getProperty(RP_CONFIG.FILE_PROPERTY);
  if (!id) return null;
  var text = DriveApp.getFileById(id).getBlob().getDataAsString('UTF-8');
  var state = JSON.parse(text);
  if (!state || state.version !== RP_CONFIG.VERSION || !state.snapshot) {
    throw new Error('Snapshot file has unexpected format; NOT reinitializing to protect event history.');
  }
  return state;
}
function rpStoreState_(state) {
  var content = JSON.stringify(state);
  if (content.length > 9500000) throw new Error('Private snapshot too large; not overwriting.');
  var props = rpProperties_(), id = props.getProperty(RP_CONFIG.FILE_PROPERTY);
  if (id) {
    DriveApp.getFileById(id).setContent(content);
  } else {
    var file = DriveApp.createFile('DailyLog_RedPlateNotify_PrivateState.json', content, 'application/json');
    props.setProperty(RP_CONFIG.FILE_PROPERTY, file.getId());
  }
}
function rpBaseline_(snapshot) {
  return { version: RP_CONFIG.VERSION, snapshot: snapshot, queue: [],
    cursor: 0, checked_at: new Date().toISOString() };
}
function setupRedPlateMonitor() {
  var props = rpProperties_();
  if (!props.getProperty(RP_CONFIG.TOKEN_PROPERTY)) {
    props.setProperty(RP_CONFIG.TOKEN_PROPERTY, Utilities.getUuid() + '-' + Utilities.getUuid());
  }
  var state = rpReadState_();
  if (!state) {
    var snapshot = rpRead_(rpOpenTab_());
    rpStoreState_(rpBaseline_(snapshot));
    Logger.log('Baseline initialized: ' + snapshot.rows.length + ' rows, HEADER_ROW=' + snapshot.header_row);
  } else {
    Logger.log('Snapshot already exists: preserved; no data or event queue reset.');
  }
  showRedPlateWebAppUrl();
}
function showRedPlateWebAppUrl() {
  var token = rpProperties_().getProperty(RP_CONFIG.TOKEN_PROPERTY);
  if (!token) throw new Error('Run setupRedPlateMonitor() first.');
  var url = ScriptApp.getService().getUrl();
  if (!url) {
    Logger.log('Deploy as Web App first; then run showRedPlateWebAppUrl() again.');
    return;
  }
  Logger.log('PRIVATE Notify GAS URL (do not share publicly): ' + url + (url.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(token));
}
function rpChanges_() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) return {ok:false, success:false, busy:true, error:'Monitor busy; retry later.'};
  try {
    var current = rpRead_(rpOpenTab_());
    var state = rpReadState_();
    if (!state) {
      rpStoreState_(rpBaseline_(current));
      return {ok:true,success:true,action:'changes',version:RP_CONFIG.VERSION,
        initialized:true,mode:'structured_changes',count:0,changes:[], note:'Initial baseline; no historical notifications.'};
    }
    var newEvents = rpDiff_(state.snapshot, current);
    var cutoff = Date.now() - RP_CONFIG.RETENTION_HOURS * 3600000;
    var queue = (state.queue || []).filter(function (evt) {
      return Date.parse(evt.occurred_at) >= cutoff;
    }).concat(newEvents);
    if (queue.length > RP_CONFIG.MAX_QUEUED_EVENTS) {
      throw new Error('Pending notification queue limit exceeded; snapshot NOT advanced. Contact Admin.');
    }
    var pageSize = RP_CONFIG.DELIVERY_PAGE_SIZE;
    var pages = Math.max(1, Math.ceil(queue.length / pageSize));
    var page = Number(state.cursor || 0) % pages;
    var delivered = queue.slice(page * pageSize, (page + 1) * pageSize);
    state.snapshot = current;
    state.queue = queue;
    state.cursor = (page + 1) % pages;
    state.checked_at = new Date().toISOString();
    rpStoreState_(state);
    return {ok:true,success:true,action:'changes',version:RP_CONFIG.VERSION,
      mode:'structured_changes', sheet:RP_CONFIG.SHEET_NAME,
      gid:RP_CONFIG.SHEET_GID, header_row:current.header_row,
      data_start_row:current.data_start_row, count:delivered.length,
      pending_count:queue.length, newly_detected:newEvents.length,
      partial:queue.length>delivered.length, changes:delivered};
  } finally {
    lock.releaseLock();
  }
}
function doGet(e) {
  try {
    var token = rpProperties_().getProperty(RP_CONFIG.TOKEN_PROPERTY);
    if (!token || rpString_(e && e.parameter && e.parameter.token) !== token) {
      return rpJson_({ok:false,success:false,error:'Missing or invalid monitor token.'});
    }
    var action = rpString_(e && e.parameter && e.parameter.action || 'changes').toLowerCase();
    if (action === 'ping') {
      var state = rpReadState_();
      if (!state) throw new Error('Run setupRedPlateMonitor() before connecting DailyLog.');
      return rpJson_({ok:true,success:true,action:'ping',version:RP_CONFIG.VERSION,
        sheet:RP_CONFIG.SHEET_NAME,gid:RP_CONFIG.SHEET_GID,
        mode:'structured_changes',header_row:state.snapshot.header_row,
        data_start_row:state.snapshot.data_start_row,
        headers:state.snapshot.headers.map(function (v,i) {return {column:rpColumn_(i),header:v};}),
        monitored_rows:state.snapshot.rows.length});
    }
    if (action !== 'changes') throw new Error('Unknown action: ' + action);
    return rpJson_(rpChanges_());
  } catch (error) {
    // Do not return partial data if a scan or snapshot write fails.
    return rpJson_({ok:false,success:false,version:RP_CONFIG.VERSION,
      error:String(error && error.message || error)});
  }
}
