// Offline contract tests for 04-红牌ชีตnew GAS. Never edits Google Sheets.
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const code=fs.readFileSync(require("node:path").join(__dirname,"../gas/red_plate_new_notify.gs"),"utf8");
const props=new Map();
let stateText=null,tabName="04-红牌ชีตnew",locked=false;
let grid=[
 ["ทะเบียนป้ายแดง","","","",""],
 ["ลำดับ","เลข VIN","ชื่อลูกค้า","เลขทะเบียนป้ายแดง","สถานะ"],
 ["1","VIN-AAA","ทดสอบ ก","กก 100","รับป้าย"],
 ["2","VIN-BBB","ทดสอบ ข","กข 200","รับป้าย"],
];
const mockFile={
 getBlob(){return {getDataAsString(){return stateText;}}},
 setContent(s){stateText=s;}
};
const ctx=vm.createContext({
 Date,console,Logger:{log(){}},
 Utilities:{getUuid(){return "test-"+Math.random().toString(36).slice(2)}},
 ScriptApp:{getService(){return {getUrl(){return "https://script.google.com/macros/s/abc/exec";}}}},
 PropertiesService:{getScriptProperties(){return {
  getProperty(k){return props.get(k)||null},
  setProperty(k,v){props.set(k,v)}
 }}},
 SpreadsheetApp:{openById(id){
  assert.equal(id,"1aC1NFxBfqDg4zkC1-y-vDYmIUpqTqegb");
  return {getSheets(){return [{
    getSheetId(){return 1947537691},getName(){return tabName},
    getLastRow(){return grid.length},
    getLastColumn(){return Math.max(...grid.map(x=>x.length))},
    getRange(r,c,h,w){assert.equal(r,1);assert.equal(c,1);
      return {getDisplayValues(){return grid.map(
        x=>Array.from({length:w},(_,i)=>x[i]||"")
      );}};
    },
  }];}};
 }},
 DriveApp:{createFile(name,content,type){
  assert.equal(type,"application/json");
  stateText=content;
  return {getId(){return "private-test-id";}};
 },getFileById(id){assert.equal(id,"private-test-id");return mockFile;}},
 LockService:{getScriptLock(){return {
  tryLock(){if(locked)return false;locked=true;return true;},
  releaseLock(){locked=false;}
 };}},
 ContentService:{MimeType:{JSON:"application/json"},
  createTextOutput(text){return {text,setMimeType(){return this;}}}},
});
vm.runInContext(code,ctx,{filename:"red_plate_new_notify.gs"});
const run=(action="changes",token=props.get("RP_NOTIFY_SECRET_TOKEN"))=>
 JSON.parse(ctx.doGet({parameter:{action,token}}).text);
assert.equal(run("ping","invalid").ok,false);
ctx.inspectRedPlateHeaders();
assert.equal(stateText,null,"Inspect must not create or change the snapshot");
ctx.setupRedPlateMonitor();
const p=run("ping");
assert.equal(p.ok,true);
assert.equal(p.header_row,2);
assert.equal(p.headers[1].header,"เลข VIN");
assert.equal(p.gid,1947537691);
assert.equal(run().count,0,"baseline produces zero old-row notifications");
const initial=stateText;

grid.splice(2,0,["3","VIN-NEW","ลูกค้าใหม่","กค 300","รอรับ"]);
let change=run();
assert.equal(change.newly_detected,1,"insert must not edit every shifted row");
const add=change.changes.find(x=>x.type==="add");
assert.equal(add.row,3);
assert.equal(add.fields.find(x=>x.column==="B").header,"เลข VIN");
assert.equal(add.fields.find(x=>x.column==="C").value,"ลูกค้าใหม่");
assert.equal(run().changes.find(x=>x.event_id===add.event_id).event_id,
 add.event_id,"pending events replay with same dedupe ID");

grid[3][2]="ทดสอบ ก - แก้ไข";
change=run();
assert.equal(change.newly_detected,1);
const edited=change.changes.find(x=>x.type==="edit"&&x.row===4);
assert.ok(edited);
assert.equal(edited.changed_cells[0].column,"C");
assert.equal(edited.changed_cells[0].before,"ทดสอบ ก");
assert.equal(edited.changed_cells[0].after,"ทดสอบ ก - แก้ไข");

grid[3][3]="";
change=run();
assert.equal(change.newly_detected,1);
const clear=change.changes.find(x=>x.type==="edit"&&
 x.changed_cells.some(z=>z.column==="D"&&z.after===""));
assert.ok(clear,"clearing one cell should be an edit");

grid.splice(2,1);
change=run();
assert.equal(change.newly_detected,1);
const del=change.changes.find(x=>x.type==="delete");
assert.ok(del);
assert.equal(del.fields.find(x=>x.column==="B").value,"VIN-NEW");

grid[1][2]="ชื่อลูกค้าใหม่";
change=run();
assert.equal(change.newly_detected,1);
assert.ok(change.changes.some(x=>x.type==="header_edit"));
const safe=stateText;
tabName="wrong tab";
assert.equal(run().ok,false);
assert.equal(stateText,safe,"wrong tab must not reset baseline or delete rows");
tabName="04-红牌ชีตnew";
ctx.setupRedPlateMonitor();
assert.equal(stateText,safe,"re-running setup must preserve all pending events");
assert.notEqual(stateText,initial);
// Viewer Excel reader: parsing is isolated, and never writes the source.
const shared=ctx.rpXlsxShared_(
 '<sst><si><t>เลข VIN</t></si><si><r><t>ชื่อลูกค้า</t></r></si>'+
 '<si><t>ลูกค้า&amp;จีน</t></si></sst>'
);
assert.deepEqual(Array.from(shared),["เลข VIN","ชื่อลูกค้า","ลูกค้า&จีน"]);
const xml='<worksheet><sheetData>'+
 '<row r="1"><c r="B1" t="s"><v>0</v></c>'+
 '<c r="IS1" t="s"><v>1</v></c><c r="C1" s="1"/></row>'+
 '<row r="2"><c r="B2" t="s"><v>2</v></c>'+
 '<c r="IS2"><v>123</v></c></row>'+
 '</sheetData></worksheet>';
const viewerGrid=ctx.rpXlsxGrid_(xml,shared);
assert.equal(viewerGrid.length,2);
assert.equal(viewerGrid[0].length,253,"Excel content through column 253 must be monitored");
assert.equal(viewerGrid[0][252],"ชื่อลูกค้า");
assert.equal(viewerGrid[1][1],"ลูกค้า&จีน");
assert.equal(viewerGrid[1][252],"123");
const viewerBaseline=ctx.rpSnapshotFromGrid_(
 viewerGrid,"04-红牌ชีตnew",1947537691
);
assert.equal(viewerBaseline.rows.length,1);
assert.equal(viewerBaseline.rows[0].row,2);
const modifiedViewerXml=xml.replace("<v>123</v>","<v>321</v>");
const revisedViewer=ctx.rpSnapshotFromGrid_(
 ctx.rpXlsxGrid_(modifiedViewerXml,shared),"04-红牌ชีตnew",1947537691
);
const changed=ctx.rpDiff_(viewerBaseline,revisedViewer);
assert.equal(changed.length,1);
assert.equal(changed[0].type,"edit");
assert.equal(changed[0].changed_cells[0].column,"IS");
assert.equal(changed[0].changed_cells[0].before,"123");
assert.equal(changed[0].changed_cells[0].after,"321");
assert.throws(()=>ctx.rpXlsxGrid_(
 '<row r="1"><c r="ZZ1"><v>1</v></c></row>',shared
),/MAX_COLUMNS/);
assert.match(code,/rpViewerExcelFile/);
assert.ok(code.includes("Utilities.unzip(file.getBlob())"));
assert.doesNotMatch(code,/\.setContent\(\s*file\.getBlob\(\)/);

console.log("PASS: red-plate GAS token, auto-header, add/edit/delete, shifted rows, replay, header rename, failure safety.");
console.log("PASS: Viewer .xlsx XML values to column 253, edits, parser limits and read-only routing.");
