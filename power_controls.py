"""Hardware-backed system battery and explicit charge thresholds, without polling."""
import os,re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from qt_compat import QObject,Property,Signal,Slot,QT5,dispose_native_io
if QT5:
    from PyQt5.QtCore import QFileSystemWatcher
else:
    from PySide6.QtCore import QFileSystemWatcher
from privileged_controls import charge_limit_helper_available,set_charge_limit_privileged,forget_charge_limit_privileged
SYSFS=Path('/sys/class/power_supply')
FILES=('scope','type','present','capacity','status','energy_now','energy_full','charge_now','charge_full','charge_control_end_threshold','charge_control_start_threshold')
EMPTY=dict(batteryPresent=False,batteryPercent=0,percentageAvailable=False,charging=False,chargeLimitSupported=False,chargeLimitWritable=False,chargeLimit=0,chargeStart=-1,selectedBattery='',busy=False,chargeLimitRequiresAuth=False,chargeLimitPersistenceAvailable=False,reason='No system battery detected')

def _integer(path):
    try:return int(path.read_text().strip())
    except (OSError,ValueError):return None

def _identity(path):
    stat=path.stat();return (str(path.resolve()),stat.st_dev,stat.st_ino)

def read_battery(root,name):
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',name):return None
    path=Path(root)/name
    try:
        if (path/'type').read_text().strip()!='Battery' or _integer(path/'present')==0:return None
        if (path/'scope').exists() and (path/'scope').read_text().strip()=='Device':return None
        status=(path/'status').read_text().strip() if (path/'status').exists() else 'Unknown'
        capacity=_integer(path/'capacity');energy=_integer(path/'energy_now');full=_integer(path/'energy_full')
        if capacity is None:
            now,total=(energy,full) if full and full>0 else (_integer(path/'charge_now'),_integer(path/'charge_full'))
            capacity=round(now*100/total) if now is not None and total and total>0 else None
        end=_integer(path/'charge_control_end_threshold');start=_integer(path/'charge_control_start_threshold')
        supported=end is not None and 0<=end<=100
        writable=supported and os.access(path/'charge_control_end_threshold',os.W_OK)
        if start is not None and not 0<=start<=100:start=None
        return dict(name=name,path=str(path),identity=_identity(path),percent=max(0,min(100,capacity)) if capacity is not None else None,charging=status=='Charging',status=status,energy=energy,full=full,supported=supported,writable=bool(writable),limit=end if supported else 0,start=start if start is not None else -1)
    except OSError:return None

def power_snapshot(root=SYSFS,selected=''):
    try:paths=sorted(Path(root).iterdir(),key=lambda p:p.name)
    except OSError:paths=[]
    devices=[]
    for path in paths[:128]:
        device=read_battery(root,path.name)
        if device:devices.append(device)
        if len(devices)>=8:break
    state=dict(EMPTY)
    privileged=Path(root)==SYSFS and charge_limit_helper_available()
    for device in devices:
        device['directWritable']=device['writable'];device['privileged']=bool(privileged and device['supported'])
        if device['privileged']:device['writable']=True
    if devices:
        chosen=next((d for d in devices if d['name']==selected),devices[0]);percentages=[d['percent'] for d in devices if d['percent'] is not None]
        if all(d['energy'] is not None and d['full'] and d['full']>0 for d in devices):percentage=round(sum(d['energy'] for d in devices)*100/sum(d['full'] for d in devices))
        else:percentage=round(sum(percentages)/len(percentages)) if percentages else 0
        reason='' if chosen['supported'] and chosen['writable'] else 'This battery does not expose a charge-limit control' if not chosen['supported'] else 'Charge limits are supported, but changing them requires permission to the battery threshold files'
        if chosen.get('privileged'):reason='Administrator confirmation is required; approved limits are restored at startup'
        state.update(chargeLimitRequiresAuth=bool(chosen.get('privileged')),chargeLimitPersistenceAvailable=bool(chosen.get('privileged')),batteryPresent=True,batteryPercent=max(0,min(100,percentage)),percentageAvailable=bool(percentages),charging=any(d['charging'] for d in devices),chargeLimitSupported=chosen['supported'],chargeLimitWritable=chosen['writable'],chargeLimit=chosen['limit'],chargeStart=chosen['start'],selectedBattery=chosen['name'],reason=reason)
    return dict(state=state,devices=devices)

def _write_threshold(path,value):
    # Only known fixed threshold attributes are opened, never a path from QML.
    fd=os.open(path,os.O_WRONLY|os.O_NOFOLLOW)
    try:
        data=(str(value)+'\n').encode()
        if os.write(fd,data)!=len(data):raise OSError('Incomplete threshold write')
    finally:os.close(fd)

def set_charge_limit(device,percent,root=SYSFS):
    """User-triggered end limit; adjust start only if needed to retain valid gap."""
    if type(percent) is not int or not 40<=percent<=100:raise ValueError('Charge limit must be between 40% and 100%')
    current=read_battery(root,device.get('name'))
    if not current or current['identity']!=device.get('identity'):raise RuntimeError('Battery changed or was disconnected; choose it again')
    if not current['supported']:raise RuntimeError('This battery does not support charge limits')
    if Path(root)==SYSFS and charge_limit_helper_available():
        result=set_charge_limit_privileged(current['name'],percent,current['identity'],persist=True)
        actual=read_battery(root,current['name'])
        if not actual or actual['identity']!=current['identity']:raise RuntimeError('Battery disconnected while applying the charge limit')
        actual['persisted']=result.get('persisted') is True
        return actual
    if not current['writable']:raise PermissionError('Battery charge-limit permission is required; no threshold was changed')
    path=Path(current['path']);old_start=current['start'];old_end=current['limit'];new_start=old_start
    if old_start>=0 and old_start>percent-5:
        new_start=max(0,percent-max(5,old_end-old_start))
        if not os.access(path/'charge_control_start_threshold',os.W_OK):raise PermissionError('Permission to both start and stop thresholds is required for this limit')
        _write_threshold(path/'charge_control_start_threshold',new_start)
    try:_write_threshold(path/'charge_control_end_threshold',percent)
    except OSError:
        if new_start!=old_start:
            # Restore our preparatory change only if the end stayed unchanged.
            actual=read_battery(root,current['name'])
            if actual and actual['identity']==current['identity'] and actual['limit']==old_end:
                try:_write_threshold(path/'charge_control_start_threshold',old_start)
                except OSError:pass
        raise
    actual=read_battery(root,current['name'])
    if not actual or actual['identity']!=current['identity']:raise RuntimeError('Battery disconnected while applying the charge limit')
    if not actual['supported']:raise RuntimeError('The driver did not provide a readable charge limit')
    return actual

class PowerControls(QObject):
    changed=Signal();notice=Signal(str);received=Signal(object)
    def __init__(self,enabled=True,parent=None,root=SYSFS,setter=None):
        super().__init__(parent);self.root=Path(root);self.setter=setter or set_charge_limit;self._state=dict(EMPTY);self._devices=[];self._selected='';self._closed=False;self._refreshing=False;self._writing=False;self._refresh_pending=False;self._desired=None;self._write_reason=None
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='orbit-power');self.received.connect(self.apply)
        self.watcher=QFileSystemWatcher(self);self.watcher.fileChanged.connect(self.refresh);self.watcher.directoryChanged.connect(self.refresh)
        if enabled:self.refresh()
    state=Property('QVariantMap',lambda self:dict(self._state),notify=changed)
    batteries=Property('QVariantList',lambda self:[dict(name=d['name'],percent=d['percent'] if d['percent'] is not None else -1,charging=d['charging'],chargeLimitSupported=d['supported']) for d in self._devices],notify=changed)
    def submit(self,kind,work,**details):
        future=self.pool.submit(work)
        def finished(result):
            if self._closed:return
            try:data=dict(kind=kind,snapshot=result.result(),**details)
            except Exception as error:data=dict(kind=kind,error=str(error)[:240],**details)
            if not self._closed:self.received.emit(data)
        future.add_done_callback(finished)
    @Slot()
    def refresh(self,*_):
        if self._closed:return
        if self._writing or self._refreshing:self._refresh_pending=True;return
        self._refreshing=True;self.submit('read',lambda:power_snapshot(self.root,self._selected))
    @Slot(str)
    def selectBattery(self,name):
        if self._closed:return
        if self._writing:self.notice.emit('Wait for the charge-limit change to finish');return
        if not any(d['name']==name for d in self._devices):self.notice.emit('Choose a connected system battery');return
        self._selected=name;self._desired=None;self._write_reason=None;self.refresh()
    def watch(self):
        desired=[str(self.root)] if self.root.exists() else [str(self.root.parent)]
        for device in self._devices:
            path=Path(device['path']);desired.append(str(path));desired.extend(str(path/name) for name in FILES if (path/name).exists())
        old=set(self.watcher.files()+self.watcher.directories());new=set(desired)
        if old-new:self.watcher.removePaths(list(old-new))
        if new-old:self.watcher.addPaths(list(new-old))
    @Slot(object)
    def apply(self,result):
        if self._closed:return
        writing=result['kind'] in ('write','forget');self._writing=False if writing else self._writing;self._refreshing=False if not writing else self._refreshing
        if result.get('error'):
            self._state={**self._state,'busy':False,'reason':result['error']};self.changed.emit();self.notice.emit(result['error']);self._desired=None
            if writing:self._write_reason=(self._selected,result['error']);self.refresh()
            return
        snapshot=result['snapshot'];before=self._state;self._devices=snapshot['devices'];self._state={**snapshot['state'],'busy':False};self._selected=self._state['selectedBattery'];self.watch()
        if self._write_reason and self._write_reason[0]==self._selected and self._state['batteryPresent']:self._state['reason']=self._write_reason[1]
        if result['kind']=='forget':
            message='Startup restoration removed; the current charge limit is unchanged'
            self._state['reason']=message;self._write_reason=(self._selected,message);self.notice.emit(message)
        elif writing:
            actual=self._state['chargeLimit'];requested=result['requested']
            message=f'Charge limit set to {actual}%' if actual==requested else f'Driver applied {actual}% (requested {requested}%)'
            if snapshot.get('persisted'):message+='; saved for startup'
            if self._state['chargeStart']>=0:message+=f'; charging starts below {self._state["chargeStart"]}%'
            self._state['reason']=message;self._write_reason=(self._selected,message);self.notice.emit(message)
        if self._state!=before:self.changed.emit()
        desired,self._desired=self._desired,None
        if desired is not None and desired[0]==self._selected and (not writing or desired[1]!=result.get('requested')):self.setChargeLimit(desired[1])
        elif self._refresh_pending:self._refresh_pending=False;self.refresh()
    @Slot(int)
    def setChargeLimit(self,percent):
        if self._closed:return
        if type(percent) is not int or not 40<=percent<=100:self.notice.emit('Choose a charge limit between 40% and 100%');return
        device=next((d for d in self._devices if d['name']==self._selected),None)
        if not device or not device['supported'] or not device['writable']:
            self.notice.emit(self._state['reason'] or 'Charge-limit control is unavailable');return
        if self._refreshing:
            self._desired=(self._selected,percent);self._state={**self._state,'busy':True};self.changed.emit();return
        if self._writing:self._desired=(self._selected,percent);return
        self._write_reason=None;self._writing=True;self._state={**self._state,'busy':True};self.changed.emit();device=dict(device)
        def work():
            actual=self.setter(device,percent,self.root);snapshot=power_snapshot(self.root,self._selected)
            if isinstance(actual,dict):snapshot['persisted']=actual.get('persisted') is True
            return snapshot
        self.submit('write',work,requested=percent)
    @Slot()
    def forgetChargeLimit(self):
        if self._closed:return
        if self._writing or self._refreshing:self.notice.emit('Wait for the charge-limit operation to finish');return
        device=next((d for d in self._devices if d['name']==self._selected),None)
        if not device or not device.get('privileged') or not self._state.get('chargeLimitPersistenceAvailable'):
            self.notice.emit('Startup restoration requires the installed administrator helper');return
        self._write_reason=None;self._writing=True;self._state={**self._state,'busy':True};self.changed.emit();name=self._selected
        def work():forget_charge_limit_privileged(name);return power_snapshot(self.root,name)
        self.submit('forget',work)
    def close(self):
        if self._closed:return
        self._closed=True
        self.watcher.fileChanged.disconnect();self.watcher.directoryChanged.disconnect()
        paths=self.watcher.files()+self.watcher.directories()
        if paths:self.watcher.removePaths(paths)
        self.pool.shutdown(wait=True,cancel_futures=True)
        dispose_native_io(self.watcher)
