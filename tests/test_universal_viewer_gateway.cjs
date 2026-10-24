// Offline Viewer Gateway integration tests; never contacts or edits Google Drive.
const assert=require("node:assert/strict");
const fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const script=fs.readFileSync(path.join(__dirname,"../gas/universal_viewer_gateway.gs"),"utf8");
const props=new Map([["VIEWER_GATEWAY_SECRET","test-secret"]]);
const savedFiles=new Map();
let grid=[
 ["ทะเบียนป้ายแดง","","","",""],
 ["ลำดับ","เลข VIN","ลูกค้า","ทะเบียน","สถานะ"],
 ["1","VIN-AAA","Alice","AB 100","รับป้าย"],
 ["2","VIN-BBB","Bob","CD 200","รับป้าย"]
];
const sourceId="1aC1NFxBfqDg4zkC1-y-vDYmIUpqTqegb";
const idTwo="sampleSheet_Viewer_000002";
const context=vm.createContext({
 console,Date,Logger:{log(){}},
 Utilities:{
  getUuid(){return "random-"+Math.random().toString(36).slice(2)},
  DigestAlgorithm:{SHA_256:"SHA_256"},
  computeDigest(_type,value){return Array.from(String(value)).map(c=>c.charCodeAt(0)%256);},
 },
 PropertiesService:{getScriptProperties(){return {
  getProperty(k){return props.get(k)||null;},setProperty(k,v){props.set(k,v);}
 }}},
 ScriptApp:{getService(){return {getUrl(){return "https://script.google.com/macros/s/gateway/exec";}}}},
 SpreadsheetApp:{openById(id){
  if (id!==sourceId && id!==idTwo)throw new Error("File denied");
  return {getSheets(){return [{
   getName(){return "04-红牌ชีตnew";},getSheetId(){return 1947537691;},
   getLastRow(){return grid.length;},getLastColumn(){return 5;},
   getRange(){return {getDisplayValues(){return grid.map(row=>[...row]);}}}
  }];}};
 }},
 DriveApp:{
  createFile(name,contents,type){assert.equal(type,"application/json");
   const key="snapshot-"+savedFiles.size;savedFiles.set(key,contents);
   return {getId(){return key;}};},
  getFileById(id){
   if(!savedFiles.has(id))throw new Error("Missing state file");
   return {getBlob(){return {getDataAsString(){return savedFiles.get(id);}};},
     setContent(value){savedFiles.set(id,value);}};
  }
 },
 LockService:{getScriptLock(){return {tryLock(){return true;},releaseLock(){}};}},
 ContentService:{MimeType:{JSON:"application/json"},createTextOutput(text){
   return {text,setMimeType(){return this;}};
 }},
});
vm.runInContext(script,context);
function api(id=sourceId,action="changes",token="test-secret"){
 return JSON.parse(context.doGet({parameter:{id,gid:"1947537691",action,token}}).text);
}
assert.equal(api(sourceId,"ping","WRONG").ok,false);
const ping=api(sourceId,"ping");
assert.equal(ping.ok,true);
assert.equal(ping.monitored_rows,2);
assert.equal(savedFiles.size,0,"Ping cannot create snapshot");
assert.equal(api().initialized,true);
assert.equal(savedFiles.size,1,"First change scan creates a private baseline");
assert.equal(api().count,0);
grid[3][2]="Bob changed";
let changed=api();
assert.equal(changed.newly_detected,1);
assert.equal(changed.changes.find(x=>x.type==="edit").changed_cells[0].column,"C");
assert.equal(api(idTwo).initialized,true,"Second file has independent snapshot");
assert.equal(savedFiles.size,2);
assert.equal(api().changes.length,1,"Stable queue retries data change");
assert.equal(context.RP_CONFIG.SPREADSHEET_ID,sourceId);
context.rpSelectTarget_({id:sourceId,gid:"1947537691",tab:"04-红牌ชีตnew"});
assert.equal(context.RP_CONFIG.SHEET_NAME,"04-红牌ชีตnew");
assert.throws(()=>context.rpSelectTarget_({id:"x"}),/Invalid/);
assert.match(script,/rpViewerExcelFile/);
assert.ok(script.includes("Utilities.unzip(file.getBlob())"));
assert.ok(!script.includes("SpreadsheetApp.openById(RP_CONFIG.SPREADSHEET_ID).setValue"));
console.log("PASS: Viewer Gateway token, real ping, independent private baselines, edits, replay, URL validation.");
