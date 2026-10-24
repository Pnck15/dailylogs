/**
 * DailyLog Central Viewer Gateway — one standalone GAS deployment, many
 * Google Drive file URLs. The executing Google account must have Viewer
 * (including download) access; this does NOT bypass Google permissions.
 * NO edits to source files. All snapshots live in deployer's private Drive.
 * Access token is sensitive; do not publish the URL with its token.
 * Use setupViewerGateway() and showViewerGatewayUrl() after deploying.
 */
var RP_CONFIG = {
  VERSION: 'viewer-gateway-v1.0',
  SPREADSHEET_ID: '',
  SHEET_GID: 0,
  SHEET_NAME: '',
  HEADER_ROW: 0,            // 0: detect dynamically; use 1, 2, ... if needed
  DATA_START_ROW: 0,        // 0: row immediately below HEADER_ROW
  MAX_ROWS: 6500,           // fail safely if exceeded; never return partial rows
  MAX_COLUMNS: 260,         // Actual .xlsx red-plate tab has data through column 253
  RETENTION_HOURS: 168,     // retry events for 7 days, across Central outages
  DELIVERY_PAGE_SIZE: 75,
  MAX_QUEUED_EVENTS: 3000,
  TOKEN_PROPERTY: 'VIEWER_GATEWAY_SECRET',
  FILE_PROPERTY: ''
};

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
  var book;
  try {
    book = SpreadsheetApp.openById(RP_CONFIG.SPREADSHEET_ID);
  } catch (nativeError) {
    var file = DriveApp.getFileById(RP_CONFIG.SPREADSHEET_ID);
    if (file.getMimeType() !==
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet') {
      throw nativeError;
    }
    return { rpViewerExcelFile: file };
  }
  var tabs = book.getSheets(), matched;
  if (RP_CONFIG.SHEET_NAME) {
    matched = tabs.filter(function(tab){return tab.getName()===RP_CONFIG.SHEET_NAME;});
  } else if (RP_CONFIG.SHEET_GID) {
    matched = tabs.filter(function(tab){return tab.getSheetId()===RP_CONFIG.SHEET_GID;});
  } else {
    matched = tabs.slice(0,1);
  }
  if (matched.length!==1) throw new Error('Target tab not found; check gid or tab name. Snapshot unchanged.');
  RP_CONFIG.SHEET_NAME=matched[0].getName();
  RP_CONFIG.SHEET_GID=matched[0].getSheetId();
  return matched[0];
}
function rpXlsxAttr_(xmlTag, name) {
  var pattern = new RegExp('(?:^|\\s)' + name + '=["\\\']([^"\\\']*)["\\\']');
  var match = pattern.exec(xmlTag || '');
  return match ? match[1] : '';
}
function rpXlsxText_(str) {
  var entities = {amp:'&',lt:'<',gt:'>',quot:'"',apos:"'"};
  return String(str || '').replace(/&(#(?:x[0-9a-f]+|[0-9]+)|amp|lt|gt|quot|apos);/gi,
    function (match, key) {
      if (key.charAt(0) === '#') {
        var code = key.charAt(1).toLowerCase() === 'x'
          ? parseInt(key.slice(2),16) : parseInt(key.slice(1),10);
        try {return String.fromCodePoint(code);} catch (_) {return match;}
      }
      return Object.prototype.hasOwnProperty.call(entities,key) ? entities[key] : match;
    });
}
function rpXlsxShared_(xml) {
  var result = [], match;
  var si = /<si(?:\s[^>]*)?>([\s\S]*?)<\/si>/g;
  while ((match = si.exec(xml))) {
    var parts = [], textMatch;
    var textNodes = /<t(?:\s[^>]*)?>([\s\S]*?)<\/t>/g;
    while ((textMatch = textNodes.exec(match[1]))) parts.push(rpXlsxText_(textMatch[1]));
    result.push(parts.join(''));
  }
  return result;
}
function rpXlsxColNumber_(ref) {
  var letters = String(ref || '').match(/^([A-Z]+)[0-9]+$/i);
  if (!letters) return -1;
  var column = 0;
  letters[1].toUpperCase().split('').forEach(function (ch) {
    column = column * 26 + ch.charCodeAt(0) - 64;
  });
  return column - 1;
}
function rpXlsxGrid_(sheetXml, shared) {
  var rows = [], maxCol = 0, maxRow = 0, rowMatch;
  var rowPattern = /<row(?:\s[^>]*)?>([\s\S]*?)<\/row>/g;
  while ((rowMatch = rowPattern.exec(sheetXml))) {
    var rowMarkup = rowMatch[0].slice(0,rowMatch[0].indexOf('>') + 1);
    var rowNumber = Number(rpXlsxAttr_(rowMarkup, 'r'));
    if (!rowNumber || rowNumber > RP_CONFIG.MAX_ROWS) {
      throw new Error('Source Excel exceeded MAX_ROWS or has invalid row references. Snapshot unchanged.');
    }
    var values = [], match;
    var cellPattern = /<c\b([^>]*?)>([\s\S]*?)<\/c>/g;
    while ((match = cellPattern.exec(rowMatch[1]))) {
      var index = rpXlsxColNumber_(rpXlsxAttr_(match[1], 'r'));
      if (index < 0 || index >= RP_CONFIG.MAX_COLUMNS) {
        throw new Error('Source Excel exceeded MAX_COLUMNS. Snapshot unchanged.');
      }
      var type = rpXlsxAttr_(match[1], 't'), content = match[2];
      var valueMatch = /<v(?:\s[^>]*)?>([\s\S]*?)<\/v>/.exec(content);
      var raw = valueMatch ? rpXlsxText_(valueMatch[1]) : '';
      if (type === 's' && raw) {
        var sharedIndex = Number(raw);
        if (!Number.isInteger(sharedIndex) || sharedIndex < 0 || sharedIndex >= shared.length) {
          throw new Error('Malformed Excel shared-string index; snapshot unchanged.');
        }
        raw = shared[sharedIndex];
      } else if (type === 'inlineStr') {
        var inlineMatch, fragments = [], inline = /<t(?:\s[^>]*)?>([\s\S]*?)<\/t>/g;
        while ((inlineMatch = inline.exec(content))) fragments.push(rpXlsxText_(inlineMatch[1]));
        raw = fragments.join('');
      } else if (type === 'b' && raw) {
        raw = raw === '1' ? 'TRUE' : 'FALSE';
      }
      if (!raw && /<f(?:\s[^>]*)?>/.test(content)) {
        // A changed formula with an empty cache is still a data change.
        var formula = /<f(?:\s[^>]*)?>([\s\S]*?)<\/f>/.exec(content);
        raw = formula ? '=' + rpXlsxText_(formula[1]) : '';
      }
      if (!rpString_(raw)) continue; // Ignore styling-only and blank cells.
      values[index] = String(raw);
      maxCol = Math.max(maxCol,index + 1);
    }
    if (values.some(function (v) {return Boolean(rpString_(v));})) {
      rows[rowNumber - 1] = values;
      maxRow = Math.max(maxRow,rowNumber);
    }
  }
  if (!maxRow || !maxCol) throw new Error('Selected Excel tab has no readable data. Snapshot unchanged.');
  var grid=[];
  for (var r=0;r<maxRow;r++) {
    var row=rows[r] || [];
    grid.push(Array.from({length:maxCol},function (_,i) {return rpString_(row[i]);}));
  }
  return grid;
}
function rpReadXlsx_(file) {
  // read-only: the original .xlsx is NEVER copied, edited or converted.
  // Utilities.unzip is an official Apps Script utility for ZIP containers;
  // Office .xlsx files use the same archive format.
  var parts = Utilities.unzip(file.getBlob());
  var blobs = {};
  parts.forEach(function (part) {
    var name = String(part.getName() || '').replace(/^\/+/, '');
    if (name === 'xl/workbook.xml' || name === 'xl/_rels/workbook.xml.rels' ||
        name === 'xl/sharedStrings.xml' || /^xl\/worksheets\/sheet[0-9]+\.xml$/.test(name)) {
      blobs[name] = part;
    }
  });
  if (!blobs['xl/workbook.xml'] || !blobs['xl/_rels/workbook.xml.rels']) {
    throw new Error('Invalid Excel archive: missing workbook relationships. Snapshot unchanged.');
  }
  var main = XmlService.getNamespace('http://schemas.openxmlformats.org/spreadsheetml/2006/main');
  var rel = XmlService.getNamespace('r','http://schemas.openxmlformats.org/officeDocument/2006/relationships');
  var workbook = XmlService.parse(blobs['xl/workbook.xml'].getDataAsString('UTF-8'));
  var sheets = workbook.getRootElement().getChild('sheets',main).getChildren('sheet',main);
  var wanted = sheets.filter(function (node) {
    if (RP_CONFIG.SHEET_NAME) {
      return node.getAttribute('name').getValue() === RP_CONFIG.SHEET_NAME;
    }
    if (RP_CONFIG.SHEET_GID) {
      return Number(node.getAttribute('sheetId').getValue()) === RP_CONFIG.SHEET_GID;
    }
    return true;
  });
  if (wanted.length!==1) {
    throw new Error('Excel .xlsx with multiple tabs requires a tab name. Add tab=EXACT_SHEET_NAME to the Source URL; source not changed.');
  }
  RP_CONFIG.SHEET_NAME=wanted[0].getAttribute('name').getValue();
  RP_CONFIG.SHEET_GID=Number(wanted[0].getAttribute('sheetId').getValue())||0;
  var relId = wanted[0].getAttribute('id',rel).getValue();
  var relationshipNs = XmlService.getNamespace('http://schemas.openxmlformats.org/package/2006/relationships');
  var relationships = XmlService.parse(blobs['xl/_rels/workbook.xml.rels'].getDataAsString('UTF-8'))
    .getRootElement().getChildren('Relationship',relationshipNs);
  var matches = relationships.filter(function (node) {
    return node.getAttribute('Id').getValue() === relId;
  });
  if (matches.length !== 1) throw new Error('Excel sheet mapping is invalid. Snapshot unchanged.');
  var target = matches[0].getAttribute('Target').getValue();
  var partName = target.charAt(0) === '/' ? target.slice(1) : 'xl/' + target.replace(/^\.\//,'');
  if (!/^xl\/worksheets\/sheet[0-9]+\.xml$/.test(partName) || !blobs[partName]) {
    throw new Error('Selected Excel worksheet ZIP component not found. Snapshot unchanged.');
  }
  var shared = blobs['xl/sharedStrings.xml']
    ? rpXlsxShared_(blobs['xl/sharedStrings.xml'].getDataAsString('UTF-8')) : [];
  var grid = rpXlsxGrid_(blobs[partName].getDataAsString('UTF-8'),shared);
  return rpSnapshotFromGrid_(grid, RP_CONFIG.SHEET_NAME, RP_CONFIG.SHEET_GID);
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
  if (sheet && sheet.rpViewerExcelFile) return rpReadXlsx_(sheet.rpViewerExcelFile);
  var lastRow = sheet.getLastRow();
  var lastCol = sheet.getLastColumn();
  if (lastRow < 1 || lastCol < 1) throw new Error('Target sheet has no headers. Snapshot unchanged.');
  if (lastRow > RP_CONFIG.MAX_ROWS || lastCol > RP_CONFIG.MAX_COLUMNS) {
    throw new Error('Sheet is larger than monitor safety limits. Increase MAX_ROWS/MAX_COLUMNS before retry; snapshot unchanged.');
  }
  var grid = sheet.getRange(1, 1, lastRow, lastCol).getDisplayValues();
  return rpSnapshotFromGrid_(grid, sheet.getName(), sheet.getSheetId());
}
function rpSnapshotFromGrid_(grid, sourceName, sourceGid) {
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
    sheet: sourceName, gid: sourceGid,
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
function rpSourceModified_(source) {
  return source && source.rpViewerExcelFile
    ? String(source.rpViewerExcelFile.getLastUpdated().getTime()) : '';
}
/** Install ONCE under a Google account with Viewer/download on target files. */
function setupViewerGateway() {
  var props=PropertiesService.getScriptProperties();
  if (!props.getProperty(RP_CONFIG.TOKEN_PROPERTY)) {
    props.setProperty(RP_CONFIG.TOKEN_PROPERTY,
      Utilities.getUuid()+'-'+Utilities.getUuid());
  }
  showViewerGatewayUrl();
}
function showViewerGatewayUrl() {
  var token=PropertiesService.getScriptProperties().getProperty(RP_CONFIG.TOKEN_PROPERTY);
  if(!token) throw new Error('Run setupViewerGateway() first.');
  var url=ScriptApp.getService().getUrl();
  if(!url) {Logger.log('Deploy as Web App first.');return;}
  Logger.log('PRIVATE Viewer Gateway URL: '+url+
    (url.indexOf('?')>=0?'&':'?')+'token='+encodeURIComponent(token));
}
function rpSelectTarget_(p) {
  var id=rpString_(p.id);
  if(!/^[a-zA-Z0-9_-]{15,}$/.test(id)) {
    throw new Error('Invalid or missing Google Drive file id.');
  }
  var gid=rpString_(p.gid);
  if(gid && !/^[0-9]{1,15}$/.test(gid)) {
    throw new Error('Invalid gid.');
  }
  var tab=rpString_(p.tab);
  if(tab.length>120) throw new Error('Sheet tab name too long.');
  RP_CONFIG.SPREADSHEET_ID=id;
  RP_CONFIG.SHEET_GID=gid?Number(gid):0;
  RP_CONFIG.SHEET_NAME=tab;
  var identifier=id+'|'+gid+'|'+tab;
  var digest=Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,identifier);
  var key=digest.map(function(x){return ('0'+(x&255).toString(16)).slice(-2);}).join('');
  RP_CONFIG.FILE_PROPERTY='VG_STATE_'+key;
}
function rpChanges_() {
    var source = rpOpenTab_();
    var modifiedAt = rpSourceModified_(source);
    var state = rpReadState_();
    // Large Viewer .xlsx files need no re-parse if their Drive mtime did
    // not move. Pending events are still replayed from the private queue.
    var unchanged = Boolean(state && modifiedAt && state.source_modified_at === modifiedAt);
    var current = unchanged ? state.snapshot : rpRead_(source);
    if (!state) {
      rpStoreState_(rpBaseline_(current));
      return {ok:true,success:true,action:'changes',version:RP_CONFIG.VERSION,
        initialized:true,mode:'structured_changes',count:0,changes:[], note:'Initial baseline; no historical notifications.'};
    }
    var newEvents = unchanged ? [] : rpDiff_(state.snapshot, current);
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
    state.source_modified_at = modifiedAt;
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
}
function doGet(e) {
  var lock=LockService.getScriptLock();
  if (!lock.tryLock(10000)) {
    return rpJson_({ok:false,success:false,busy:true,error:'Gateway busy, retry later'});
  }
  try {
    var p=(e&&e.parameter)||{};
    var token=PropertiesService.getScriptProperties().getProperty(RP_CONFIG.TOKEN_PROPERTY);
    if(!token || rpString_(p.token)!==token) {
      return rpJson_({ok:false,success:false,error:'Missing or invalid monitor token.'});
    }
    rpSelectTarget_(p);
    var action=rpString_(p.action||'changes').toLowerCase();
    if(action==='ping') {
      var current=rpRead_(rpOpenTab_());
      return rpJson_({ok:true,success:true,action:'ping',
        version:RP_CONFIG.VERSION,sheet:current.sheet,gid:current.gid,
        monitored_rows:current.rows.length,header_row:current.header_row});
    }
    if(action!=='changes') throw new Error('Unknown action: '+action);
    return rpJson_(rpChanges_());
  } catch(err) {
    return rpJson_({ok:false,success:false,version:RP_CONFIG.VERSION,
      error:String(err&&err.message||err)});
  } finally {
    lock.releaseLock();
  }
}
