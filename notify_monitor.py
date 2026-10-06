from datetime import date
from PySide6.QtCore import QObject, QThreadPool, QTimer, QRunnable, Signal, Slot
from sale_api_monitor import SaleAPIMonitor

INTERVAL_MS = 300000

class _Signals(QObject):
    done=Signal(str,object); error=Signal(str,str)

class _Job(QRunnable):
    def __init__(self,branch,monitor,initial):
        super().__init__(); self.branch=branch; self.monitor=monitor; self.initial=initial; self.signals=_Signals()
    @Slot()
    def run(self):
        try: self.signals.done.emit(self.branch,self.monitor.check(initial=self.initial))
        except Exception as e: self.signals.error.emit(self.branch,str(e))

class NotifyMonitorEngine(QObject):
    event=Signal(str,str,str); summary_changed=Signal(int,int,int); status_changed=Signal(str)
    def __init__(self,settings,parent=None):
        super().__init__(parent); self.settings=settings; self.pool=QThreadPool.globalInstance()
        self.monitors={}; self.busy=set(); self.timer=QTimer(self); self.timer.setInterval(INTERVAL_MS); self.timer.timeout.connect(self.poll_all)

    def start(self):
        self.reload_urls(); self.poll_all(initial=True)
        if not self.timer.isActive(): self.timer.start()

    def reload_urls(self):
        keys={"Sathorn":"sathorn_url","Srinakarin":"srinakarin_url","SA":"sa_url","MainNoti":"main_noti_url"}
        for branch,key in keys.items():
            url=str(self.settings.value(key,"") or "").strip()
            if url and (branch not in self.monitors or self.monitors[branch].url != url): self.monitors[branch]=SaleAPIMonitor(url)
            elif not url: self.monitors.pop(branch,None)

    def poll_all(self,initial=False):
        self.reload_urls()
        for branch,monitor in list(self.monitors.items()):
            if branch in self.busy: continue
            self.busy.add(branch); job=_Job(branch,monitor,initial)
            job.signals.done.connect(self._done); job.signals.error.connect(self._error); self.pool.start(job)

    def _error(self,branch,message):
        self.busy.discard(branch); self.status_changed.emit(f"{branch}: ERROR - {message}")

    def _done(self,branch,result):
        self.busy.discard(branch); self.status_changed.emit(f"{branch}: OK")
        self._events(branch,result); self._emit_summary()

    def _row(self,v):
        return "\n".join([f"Model: {v.get('model','-')}",f"VIN: {v.get('vin','-')}",f"Customer: {v.get('customer','-')}",f"Sale: {v.get('sale','-')}",f"Pay Day: {v.get('pay_day','-')}",f"Delivery Date: {v.get('delivery_date','-')}"])

    @staticmethod
    def _pick(d,*keys):
        for k in keys:
            if isinstance(d,dict) and d.get(k) not in (None,""): return d.get(k)
        return ""

    def _event_message(self,e):
        parts=[]
        customer=self._pick(e,"customer","customerName","客户的姓名")
        model=self._pick(e,"model","carModel","车型")
        if customer: parts.append(f"Customer: {customer}")
        if model: parts.append(f"Model: {model}")
        today_fields=e.get("today_fields") if isinstance(e.get("today_fields"),list) else []
        for item in today_fields:
            if isinstance(item,dict) and item.get("value") not in (None,""):
                parts.append(f"{item.get('header') or 'วันที่'}: {item.get('value')}")
        changes=e.get("changes") if isinstance(e.get("changes"),list) else []
        for x in changes:
            if not isinstance(x,dict): continue
            name=self._pick(x,"header","field","columnName","name") or "ข้อมูล"
            kind=str(x.get("type") or "").lower()
            old=self._pick(x,"oldValue","old_value","before","old")
            new=self._pick(x,"newValue","new_value","after","new","value")
            if kind=="deleted": line=f"{name}: ลบข้อมูล (เดิม: {old or '-'})"
            elif kind=="created": line=f"{name}: {new or '-'}"
            else: line=f"{name}: {old or '-'} → {new or '-'}"
            parts.append(line)
        return "\n".join(parts) or "พบการเปลี่ยนแปลงข้อมูล"

    def _events(self,branch,result):
        title="SA Notify" if branch=="SA" else ("MainNoti" if branch=="MainNoti" else f"Sale Deli {branch}")
        for _,v in result.get("added",[]): self.event.emit(branch,f"{title} - เพิ่มรายการใหม่",self._row(v))
        for _,old,new in result.get("changed",[]):
            lines=[]
            for label,key in (("Model","model"),("VIN","vin"),("Customer","customer"),("Sale","sale"),("Pay Day","pay_day"),("Delivery Date","delivery_date")):
                if old.get(key,"")!=new.get(key,""): lines.append(f"{label}: {old.get(key,'-')} → {new.get(key,'-')}")
            if lines: self.event.emit(branch,f"{title} - มีการแก้ไขข้อมูล","\n".join(lines))
        today=date.today().isoformat()
        for i,e in enumerate(result.get("changes",[])):
            if not isinstance(e,dict):
                self.event.emit(branch,f"{title} - มีการเปลี่ยนแปลงข้อมูล",str(e)); continue
            event_type=str(e.get("type") or "row_change")
            if event_type in ("delivery_today","today_appointment"):
                sheet=str(e.get("sheet") or ""); row=str(e.get("row") or i)
                sig="|".join(str(x.get("header",""))+":"+str(x.get("value","")) for x in e.get("today_fields",[]) if isinstance(x,dict))
                key=f"today_seen/{today}/{branch}/{sheet}/{row}/{sig}"
                if self.settings.value(key,False,type=bool): continue
                self.settings.setValue(key,True); self.settings.sync()
                event_title=f"{title} - "+("ส่งรถวันนี้" if event_type=="delivery_today" else "นัดหมายวันนี้")
            else:
                event_title=f"{title} - มีการเปลี่ยนแปลงข้อมูล"
            self.event.emit(branch,event_title,self._event_message(e))

    def _emit_summary(self):
        counts={"Sathorn":0,"Srinakarin":0}
        for branch in counts:
            m=self.monitors.get(branch)
            if m: counts[branch]=sum(1 for _,v in m.get_due_today() if "Delivery Date" in v.get("due_fields",[]))
        total=counts["Sathorn"]+counts["Srinakarin"]
        self.summary_changed.emit(counts["Sathorn"],counts["Srinakarin"],total)
        today=date.today().isoformat(); signature=f'{counts["Sathorn"]}:{counts["Srinakarin"]}:{total}'
        key=f"summary/{today}"
        previous=str(self.settings.value(key,"") or "")
        if previous!=signature:
            self.settings.setValue(key,signature); self.settings.sync()
            if previous:
                self.event.emit("Summary","Today's Delivery Summary",f'🚗 ส่งรถวันนี้ {total} คัน\nSathorn {counts["Sathorn"]}\nSrinakarin {counts["Srinakarin"]}')
