import json
from datetime import date
from PySide6.QtCore import QObject, QThreadPool, QTimer, QRunnable, Signal, Slot
from sale_api_monitor import SaleAPIMonitor

BRANCHES = ("Sathorn", "Srinakarin", "SA", "MainNoti")
INTERVAL_MS = 300000

class _Signals(QObject):
    done = Signal(str, object)
    error = Signal(str, str)

class _Job(QRunnable):
    def __init__(self, branch, monitor, initial):
        super().__init__(); self.branch=branch; self.monitor=monitor; self.initial=initial; self.signals=_Signals()
    @Slot()
    def run(self):
        try:
            self.signals.done.emit(self.branch, self.monitor.check(initial=self.initial))
        except Exception as e:
            self.signals.error.emit(self.branch, str(e))

class NotifyMonitorEngine(QObject):
    event = Signal(str, str, str)
    summary_changed = Signal(int, int, int)
    status_changed = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings=settings
        self.pool=QThreadPool.globalInstance()
        self.monitors={}
        self.busy=set()
        self.due_seen=set()
        self.timer=QTimer(self); self.timer.setInterval(INTERVAL_MS); self.timer.timeout.connect(self.poll_all)

    def start(self):
        self.reload_urls()
        self.poll_all(initial=True)
        self.timer.start()

    def reload_urls(self):
        keys={"Sathorn":"sathorn_url","Srinakarin":"srinakarin_url","SA":"sa_url","MainNoti":"main_noti_url"}
        for branch,key in keys.items():
            url=str(self.settings.value(key,"") or "").strip()
            if url and (branch not in self.monitors or self.monitors[branch].url != url):
                self.monitors[branch]=SaleAPIMonitor(url)
            elif not url:
                self.monitors.pop(branch,None)

    def poll_all(self, initial=False):
        self.reload_urls()
        for branch,monitor in list(self.monitors.items()):
            if branch in self.busy: continue
            self.busy.add(branch)
            job=_Job(branch,monitor,initial)
            job.signals.done.connect(self._done); job.signals.error.connect(self._error)
            self.pool.start(job)

    def _error(self, branch, message):
        self.busy.discard(branch)
        self.status_changed.emit(f"{branch}: ERROR - {message}")

    def _done(self, branch, result):
        self.busy.discard(branch)
        self.status_changed.emit(f"{branch}: OK")
        self._events(branch,result)
        self._emit_summary()

    def _row(self,v):
        return "\n".join([
            f"Model: {v.get('model','-')}", f"VIN: {v.get('vin','-')}",
            f"Customer: {v.get('customer','-')}", f"Sale: {v.get('sale','-')}",
            f"Pay Day: {v.get('pay_day','-')}", f"Delivery Date: {v.get('delivery_date','-')}"
        ])

    def _events(self, branch, result):
        title="SA Notify" if branch=="SA" else ("MainNoti" if branch=="MainNoti" else f"Sale Deli {branch}")
        for _,v in result.get("added",[]): self.event.emit(branch,f"{title} - เพิ่มรายการใหม่",self._row(v))
        for _,old,new in result.get("changed",[]):
            lines=[]
            for label,key in (("Model","model"),("VIN","vin"),("Customer","customer"),("Sale","sale"),("Pay Day","pay_day"),("Delivery Date","delivery_date")):
                if old.get(key,"") != new.get(key,""): lines.append(f"{label}: {old.get(key,'-')} → {new.get(key,'-')}")
            if lines: self.event.emit(branch,f"{title} - มีการแก้ไขข้อมูล","\n".join(lines))
        for row in result.get("deleted",[]): self.event.emit(branch,f"{title} - รายการถูกลบ",f"Row: {row}")
        for e in result.get("changes",[]):
            if isinstance(e,dict):
                customer=e.get("customer") or e.get("customerName") or e.get("客户的姓名") or ""
                model=e.get("model") or e.get("carModel") or e.get("车型") or ""
                parts=[]
                if customer: parts.append(f"Customer: {customer}")
                if model: parts.append(f"Model: {model}")
                nested=e.get("changes")
                if isinstance(nested,list):
                    for x in nested:
                        if isinstance(x,dict):
                            name=x.get("header") or x.get("field") or x.get("columnName") or "ข้อมูล"
                            before=x.get("oldValue",x.get("old","-")); after=x.get("newValue",x.get("new",x.get("value","-")))
                            parts.append(f"{name}: {before or '-'} → {after or '-'}")
                if not parts:
                    for k,v in e.items():
                        if k not in {"row","rowNumber","sheet","sheetName","timestamp","changes"} and v not in ("",None):
                            parts.append(f"{k}: {v}")
                self.event.emit(branch,f"{title} - มีการเปลี่ยนแปลงข้อมูล","\n".join(parts) or "พบการเปลี่ยนแปลงข้อมูล")
            else: self.event.emit(branch,f"{title} - มีการเปลี่ยนแปลงข้อมูล",str(e))
        monitor=self.monitors.get(branch)
        if monitor:
            for row,v in monitor.get_due_today():
                key=f"{date.today().isoformat()}:{branch}:{row}:{v.get('delivery_date','')}"
                if key not in self.due_seen:
                    self.due_seen.add(key); self.event.emit(branch,f"{title} - ถึงกำหนดวันนี้",self._row(v))

    def _emit_summary(self):
        s=k=0
        for branch in ("Sathorn","Srinakarin"):
            m=self.monitors.get(branch)
            if not m: continue
            count=sum(1 for _,v in m.get_due_today() if "Delivery Date" in v.get("due_fields",[]))
            if branch=="Sathorn": s=count
            else: k=count
        self.summary_changed.emit(s,k,s+k)
