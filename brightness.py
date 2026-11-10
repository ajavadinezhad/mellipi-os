"""Real backlight controls using logind/brightnessctl and optional demand-only DDC/CI; no gamma tricks or polling."""
import json,os,re,shutil,subprocess,sys,tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from qt_compat import QObject,Property,Signal,Slot,QT5,dispose_native_io
if QT5:
    from PyQt5.QtCore import QFileSystemWatcher
else:
    from PySide6.QtCore import QFileSystemWatcher
SYSFS=Path('/sys/class/backlight')
EMPTY=dict(available=False,percent=0,name='',busy=False,backend='',externalId=0,reason='No laptop backlight detected. External monitors require DDC/CI support and a compatible control backend.')

def discover_backlight(root=SYSFS):
    """Prefer firmware/platform devices over raw GPU duplicates, deterministically."""
    devices=[]
    try:paths=list(Path(root).iterdir())
    except OSError:return None
    for path in paths:
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',path.name):continue
        try:
            maximum=int((path/'max_brightness').read_text().strip())
            if not 0<maximum<=0x7fffffff:continue
            kind=(path/'type').read_text().strip() if (path/'type').exists() else 'raw'
            try:actual=int((path/'actual_brightness').read_text().strip())
            except (OSError,ValueError):actual=int((path/'brightness').read_text().strip())
            actual=max(0,min(maximum,actual))
            devices.append(dict(backend='backlight',name=path.name,path=str(path),maximum=maximum,raw=actual,percent=round(actual*100/maximum),kind=kind))
        except (OSError,ValueError):continue
    return min(devices,key=lambda d:({'firmware':0,'platform':1,'raw':2}.get(d['kind'],3),d['name'])) if devices else None

def logind_set_brightness(name,raw):
    if '/usr/lib/python3/dist-packages' not in sys.path:sys.path.append('/usr/lib/python3/dist-packages')
    from gi.repository import Gio,GLib
    bus=Gio.bus_get_sync(Gio.BusType.SYSTEM,None)
    try:
        path=bus.call_sync('org.freedesktop.login1','/org/freedesktop/login1','org.freedesktop.login1.Manager','GetSessionByPID',GLib.Variant('(u)',(os.getpid(),)),None,Gio.DBusCallFlags.NO_AUTO_START,2000,None).unpack()[0]
    except Exception:path='/org/freedesktop/login1/session/auto'
    bus.call_sync('org.freedesktop.login1',path,'org.freedesktop.login1.Session','SetBrightness',GLib.Variant('(ssu)',('backlight',name,raw)),None,Gio.DBusCallFlags.NO_AUTO_START,2000,None)

def set_backlight(device,percent):
    """Authorization remains with logind or installed device permissions."""
    name=device['name'];maximum=device['maximum']
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',name) or type(maximum) is not int or not 0<maximum<=0x7fffffff:raise ValueError('Invalid backlight device')
    percent=max(1,min(100,int(percent)));raw=max(1,min(maximum,round(maximum*percent/100)))
    try:logind_set_brightness(name,raw);return
    except Exception as error:logind_error=error
    executable=shutil.which('brightnessctl')
    if executable:
        result=subprocess.run([executable,'--class=backlight','--device',name,'set',str(raw)],capture_output=True,text=True,timeout=5)
        if result.returncode==0:return
        raise PermissionError((result.stderr.strip() or 'Backlight permission denied')[:180])
    raise PermissionError('Backlight control unavailable: '+str(logind_error)[:160])

def parse_ddc_displays(output):
    """Parse ddcutil's documented brief report, excluding invalid/phantom devices."""
    records=[];current=None
    for line in str(output)[:65536].splitlines()[:512]:
        match=re.fullmatch(r'\s*Display ([1-9][0-9]{0,3})\s*',line)
        if match:
            current=dict(id=int(match[1]),identity='',name='',bus='')
            records.append(current)
            if len(records)>16:break
        elif re.match(r'\s*(Invalid|Phantom) display',line,re.I):current=None
        elif current is not None:
            match=re.match(r'\s*Monitor:\s*(.+)',line)
            if match:
                identity=' '.join(match[1].split())[:256];parts=identity.split(':')
                current.update(identity=identity,name=(parts[1] if len(parts)>1 else identity)[:120])
            match=re.match(r'\s*I2C bus:\s*/dev/i2c-([0-9]+)',line)
            if match:current['bus']=match[1]
            match=re.match(r'\s*DRM connector:\s*(.+)',line)
            if match:current['connector']=Path(match[1].strip()).name[:128]
    seen=set();result=[]
    for record in records[:16]:
        if record['identity'] and record['id'] not in seen:result.append(record);seen.add(record['id'])
    return result

def parse_ddc_brightness(output):
    match=re.search(r'^VCP\s+10\s+C\s+([0-9]+)\s+([0-9]+)\s*$',str(output)[:4096],re.M)
    if not match:raise RuntimeError('This display does not report DDC/CI brightness (VCP 10)')
    current,maximum=map(int,match.groups())
    if not 0<maximum<=65535 or not 0<=current<=maximum:raise RuntimeError('Invalid DDC/CI brightness response')
    return current,maximum

def ddc_command(arguments):
    executable=shutil.which('ddcutil')
    if not executable:raise RuntimeError('Install ddcutil to detect and control external displays with DDC/CI')
    result=subprocess.run([executable,*arguments],capture_output=True,text=True,timeout=8)
    if result.returncode:raise PermissionError((result.stderr.strip() or result.stdout.strip() or 'DDC/CI access failed; check display support and I2C permissions')[:200])
    return result.stdout[:65536]

def discover_external():return parse_ddc_displays(ddc_command(['detect','--brief']))

def read_external(device):
    ident=device['id']
    if type(ident) is not int or not 1<=ident<=9999:raise ValueError('Invalid external display ID')
    current,maximum=parse_ddc_brightness(ddc_command(['--display',str(ident),'getvcp','10','--terse']))
    return dict(device,backend='ddc',raw=current,maximum=maximum,percent=round(current*100/maximum))

def set_external(device,percent):
    ident=device['id']
    if type(ident) is not int or not 1<=ident<=9999:raise ValueError('Invalid external display ID')
    # Numeric display IDs may change after hotplug. Never apply a queued slider
    # value to a replacement monitor: confirm its identity before every write.
    found=next((d for d in discover_external() if d['id']==ident),None)
    if found is None or (found['identity'],found['bus'])!=(device['identity'],device['bus']):raise RuntimeError('External display changed; detect and select it again')
    maximum=device['maximum']
    if type(maximum) is not int or not 0<maximum<=65535:raise ValueError('Invalid DDC/CI brightness range')
    raw=max(1,min(maximum,round(maximum*max(1,min(100,int(percent)))/100)))
    ddc_command(['--display',str(ident),'setvcp','10',str(raw)])

def target_key(device):
    return (device.get('backend','ddc' if 'id' in device else 'backlight'),device['name'],device.get('id',0),device.get('identity',''),device.get('bus',''))

class BrightnessControls(QObject):
    changed=Signal();notice=Signal(str);received=Signal(object)
    def __init__(self,enabled=True,parent=None,root=SYSFS,setter=None,target_path=None):
        super().__init__(parent);self.root=Path(root);self.setter=setter or set_backlight;self._state=EMPTY.copy();self._device=None;self._closed=False
        self.target_path=Path(target_path) if target_path is not None else Path(os.environ.get('ORBIT_DATA',str(Path(__file__).resolve().parent/'data')))/'brightness-target.json' if enabled and self.root==SYSFS else None
        self._remembered=self.load_target();self._restore_pending=bool(self._remembered);self._restore_unresolved=bool(self._remembered);self._remember_on_read=False
        self._desired=None;self._writing=False;self._refreshing=False;self._refresh_after_write=False;self._discovering=False;self._external=[];self._externalId=0
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='orbit-backlight')
        self.watcher=QFileSystemWatcher(self);self.watcher.fileChanged.connect(self.refresh);self.watcher.directoryChanged.connect(self.refresh)
        self.received.connect(self.apply)
        if enabled:self.refresh()
    def load_target(self):
        if self.target_path is None:return ''
        try:
            value=json.loads(self.target_path.read_text()).get('identity','')
            return value if isinstance(value,str) and 0<len(value)<=256 and all(ord(c)>=32 for c in value) else ''
        except (OSError,ValueError,AttributeError):return ''
    def save_target(self,identity):
        self._remembered=identity
        if self.target_path is None:return
        try:
            if not identity:
                self.target_path.unlink(missing_ok=True);return
            self.target_path.parent.mkdir(parents=True,exist_ok=True)
            fd,name=tempfile.mkstemp(prefix='.brightness-target-',dir=self.target_path.parent)
            try:
                with os.fdopen(fd,'w') as handle:json.dump({'identity':identity},handle);handle.flush();os.fsync(handle.fileno())
                os.replace(name,self.target_path)
            finally:
                if os.path.exists(name):os.unlink(name)
        except OSError:self.notice.emit('Brightness target selected, but its preference could not be saved')
    def restore_target(self):
        if not self._restore_pending or self._closed:return
        self._restore_pending=False;self._discovering=True;self._device=None
        self._state={**self._state,'available':False,'backend':'ddc','busy':True};self.changed.emit()
        identity=self._remembered
        def work():
            rows=discover_external();matches=[d for d in rows if d['identity']==identity]
            if len(matches)==1:return dict(rows=rows,selected=read_external(matches[0]),reason='')
            return dict(rows=rows,selected=None,reason='Several displays share the remembered identity; choose one explicitly' if matches else 'Remembered external display is unavailable; detect and select a display')
        self.submit('restore',work)
    state=Property('QVariantMap',lambda self:dict(self._state),notify=changed)
    externalDisplays=Property('QVariantList',lambda self:[dict(id=d['id'],name=d['name']) for d in self._external],notify=changed)
    def submit(self,kind,work,**details):
        future=self.pool.submit(work)
        def finished(result):
            if self._closed:return
            try:data=dict(kind=kind,device=result.result(),**details)
            except Exception as error:data=dict(kind=kind,error=str(error)[:220],**details)
            if not self._closed:self.received.emit(data)
        future.add_done_callback(finished)
    @Slot()
    def discoverExternal(self):
        if self._closed:return
        if self._writing or self._refreshing or self._discovering:self.notice.emit('Wait for the brightness operation to finish');return
        if not shutil.which('ddcutil'):
            reason='Install ddcutil to detect external displays; the monitor must support DDC/CI'
            self._state={**self._state,'reason':reason};self.changed.emit();self.notice.emit(reason);return
        self._discovering=True;self._state={**self._state,'busy':True};self.changed.emit();self.submit('detect',discover_external)
    @Slot(str)
    def selectByIdentity(self,identity):
        matches=[d for d in self._external if d['identity']==identity]
        if len(matches)!=1:self.notice.emit('Detect displays and choose one exact monitor; the identity is missing or ambiguous');return
        self.selectExternal(matches[0]['id'])
    @Slot()
    def selectFirstExternal(self):
        if len(self._external)!=1:self.notice.emit('Choose a display explicitly when more than one is detected');return
        self.selectExternal(self._external[0]['id'])
    @Slot(int)
    def selectExternal(self,ident):
        if self._closed:return
        if self._writing or self._refreshing or self._discovering:self.notice.emit('Wait for the brightness operation to finish');return
        if ident!=0 and not any(d['id']==ident for d in self._external):self.notice.emit('Detect and choose an available external display');return
        self._restore_pending=False;self._restore_unresolved=False;self._remember_on_read=bool(ident)
        if not ident:self.save_target('')
        self._externalId=ident;self._device=None;self._desired=None
        self._state={**EMPTY,'backend':'ddc' if ident else '', 'externalId':ident,'busy':True,'reason':''};self.changed.emit();self.refresh()
    @Slot()
    def refresh(self,*_):
        if self._closed:return
        if self._restore_unresolved and not self._restore_pending:return
        if self._writing:self._refresh_after_write=True;return
        if self._refreshing or self._discovering:return
        self._refreshing=True
        if self._externalId:
            device=next((dict(d) for d in self._external if d['id']==self._externalId),None)
            self.submit('refresh',lambda:read_external(device) if device else None)
        else:self.submit('refresh',lambda:discover_backlight(self.root))
    def watch_device(self):
        paths=[]
        if not self._externalId:
            paths=[str(self.root)] if self.root.exists() else []
            if self._device:
                path=Path(self._device['path'])
                paths += [str(p) for p in [path,path/'brightness',path/'actual_brightness',path/'max_brightness'] if p.exists()]
        current=set(self.watcher.files()+self.watcher.directories());wanted=set(paths)
        if current-wanted:self.watcher.removePaths(list(current-wanted))
        if wanted-current:self.watcher.addPaths(list(wanted-current))
    @Slot(object)
    def apply(self,result):
        if self._closed:return
        if result['kind']=='restore':
            self._discovering=False
            if 'error' in result:
                self._state={**EMPTY,'backend':'ddc','reason':result['error']};self.changed.emit();return
            restored=result['device'];self._external=restored['rows'];device=restored['selected']
            if device:
                self._restore_unresolved=False;self._externalId=device['id'];self._device=device
                self._state=dict(available=True,percent=device['percent'],name=device['name'],busy=False,backend='ddc',externalId=device['id'],reason='');self.watch_device()
            else:self._state={**EMPTY,'backend':'ddc','reason':restored['reason']}
            self.changed.emit();return
        if result['kind']=='detect':
            self._discovering=False
            if 'error' in result:
                self._state={**self._state,'busy':False,'reason':result['error']};self.notice.emit(result['error'])
            else:
                self._external=result['device'];reason='' if self._state['available'] else 'Choose an external display to control brightness' if self._external else 'No accessible DDC/CI displays found; check monitor support and I2C permissions'
                if self._externalId and self._device:
                    found=next((d for d in self._external if d['id']==self._externalId),None)
                    if not found or target_key(found)!=target_key(self._device):self._device=None;self._state={**self._state,'available':False};reason='External display changed; select it again'
                self._state={**self._state,'busy':False,'reason':reason}
            self.changed.emit();return
        writing=result['kind']=='write'
        if writing:self._writing=False
        else:self._refreshing=False
        if 'error' in result:
            self._state={**self._state,'reason':result['error'],'busy':self._writing}
            self.notice.emit('Brightness: '+result['error'])
        else:
            self._device=result['device'];device=self._device
            self._state=dict(available=bool(device),percent=device['percent'] if device else 0,name=device['name'] if device else '',busy=self._writing,backend=device.get('backend','backlight') if device else 'ddc' if self._externalId else '',externalId=self._externalId,reason='' if device else 'Selected external display is unavailable; detect it again' if self._externalId else EMPTY['reason'])
            self.watch_device()
            if self._remember_on_read and device and device.get('backend')=='ddc':self.save_target(device['identity']);self._remember_on_read=False
        self.changed.emit()
        if writing:
            desired,self._desired=self._desired,None
            if desired is not None and desired!=result['requested']:
                if self._device and target_key(self._device)==result['requestedDevice']:self.begin_write(desired)
                else:self.notice.emit('Brightness device changed; adjust it again')
            elif self._refresh_after_write:self._refresh_after_write=False;self.refresh()
        elif self._restore_pending:self.restore_target()
    @Slot(int)
    def setBrightness(self,percent):
        if self._closed:return
        percent=max(1,min(100,int(percent)))
        if not self._device:self.notice.emit(self._state['reason']);return
        if self._discovering:self.notice.emit('Wait for external display detection to finish');return
        if self._writing:self._desired=percent;return
        self.begin_write(percent)
    def begin_write(self,percent):
        self._writing=True;self._state={**self._state,'busy':True};self.changed.emit();device=dict(self._device)
        def work():
            if device.get('backend')=='ddc':set_external(device,percent);return read_external(device)
            self.setter(device,percent);return discover_backlight(self.root)
        self.submit('write',work,requested=percent,requestedDevice=target_key(device))
    def close(self):
        if self._closed:return
        self._closed=True
        paths=self.watcher.files()+self.watcher.directories()
        if paths:self.watcher.removePaths(paths)
        self.pool.shutdown(wait=True,cancel_futures=True)
        dispose_native_io(self.watcher)
