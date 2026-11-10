"""Known windowless applications, watched with pidfds rather than process polling."""
import hashlib,json,os,select,stat,tempfile,time
from pathlib import Path
from qt_compat import QObject,Property,Signal,QSocketNotifier,QTimer
from desktop import match_application
MAX_WATCHES=64
# Qt owns deferred C++ deletion, but PySide wrappers need an explicit Python
# root until it happens. A worker-thread gc.collect must not finalize a retired
# notifier (or its owning tracker) on that worker instead of the GUI thread.
_RETIRED_NOTIFIERS={}

def _retire_notifier(notifier,owner):
    key=id(notifier);_RETIRED_NOTIFIERS[key]=(notifier,owner)
    # Release the parent only after the child's destructor has returned; dropping
    # the final parent wrapper from inside destroyed can recursively delete it.
    notifier.destroyed.connect(lambda *_,key=key:QTimer.singleShot(0,lambda key=key:_RETIRED_NOTIFIERS.pop(key,None)))
    notifier.deleteLater()

def _process_info(pid):
    """Read one explicitly known process; never enumerate /proc or retain argv."""
    if type(pid) is not int or pid<=1:return None
    try:
        path=Path('/proc')/str(pid)
        if path.stat().st_uid!=os.getuid():return None
        stat=(path/'stat').read_text();fields=stat[stat.rfind(')')+2:].split()
        argv=(path/'cmdline').read_bytes().split(b'\0')
        return dict(pid=pid,parent=int(fields[1]),birth=int(fields[19]),exe=str((path/'exe').resolve(strict=True)),child=any(arg.startswith(b'--type=') for arg in argv))
    except (OSError,ValueError,IndexError):return None

def resolve_application_pid(pid):
    """Follow only Electron's same-executable renderer/zygote chain, at most8 hops."""
    info=_process_info(pid)
    if not info:return None
    for _ in range(8):
        if not info['child']:return info['pid'],info['birth']
        parent=_process_info(info['parent'])
        if not parent or parent['exe']!=info['exe']:return None
        info=parent
    return None

def _birth(pid):
    try:
        stat=(Path('/proc')/str(pid)/'stat').read_text();return int(stat[stat.rfind(')')+2:].split()[19])
    except (OSError,ValueError,IndexError):return None

def _alive(fd):
    try:return not select.select([fd],[],[],0)[0]
    except (OSError,ValueError):return False

class BackgroundApps(QObject):
    changed=Signal()
    def __init__(self,enabled=True,parent=None,environment=None):
        super().__init__(parent);self.environment=dict(os.environ if environment is None else environment);self.enabled=enabled and hasattr(os,'pidfd_open');self.records={};self.visible=set();self.catalog={};self.excludedIds=set();self.excludedPids=set();self._closed=False
    available=Property(bool,lambda self:self.enabled,constant=True)
    items=Property('QVariantList',lambda self:self._items(),notify=changed)
    def _items(self):
        rows={}
        for key,record in self.records.items():
            app=record['app'];ident=app['id']
            if ident in self.visible or ident in self.excludedIds or key[0] in self.excludedPids:continue
            rows.setdefault(ident,dict(id=ident,name=app['name'],icon=app.get('icon','application-x-executable'),pid=key[0]))
        return list(rows.values())
    def setExcluded(self,desktop_ids=(),pids=()):
        """Deduplicate only confirmed desktop IDs/PIDs, never fuzzy display names."""
        before=self._items();self.excludedIds=set(desktop_ids);self.excludedPids=set(pids)
        if before!=self._items():self.changed.emit()
    def _remove(self,key,notify=True):
        record=self.records.pop(key,None)
        if not record:return
        notifier=record['notifier'];notifier.setEnabled(False)
        try:notifier.activated.disconnect()
        except RuntimeError:pass
        _retire_notifier(notifier,self)
        try:os.close(record['fd'])
        except OSError:pass
        if notify:self.changed.emit()
    def observe(self,apps,windows):
        if not self.enabled or self._closed:return
        before=self._items();self.catalog={app['id']:app for app in apps};visible=set()
        # Readiness is checked only in response to window events, to avoid a
        # transient stale row if the process exits before Qt dispatches its fd.
        for key,record in list(self.records.items()):
            if not _alive(record['fd']):self._remove(key,False)
        for window in windows:
            app=match_application(window,apps)
            if not app:continue # Do not turn unrelated daemons/services into apps.
            visible.add(app['id'])
            try:pid=int(window.get('pid',0))
            except (TypeError,ValueError):continue
            cached=next((key for key,record in self.records.items() if key[0]==pid and record['app']['id']==app['id']),None)
            if cached:
                self.records[cached]['app']=app;continue
            if len(self.records)>=MAX_WATCHES:continue
            identity=resolve_application_pid(pid)
            if not identity or identity in self.records:continue
            fd=None
            try:
                fd=os.pidfd_open(identity[0],0)
                # Bind the birth time around pidfd_open to reject PID reuse.
                if _birth(identity[0])!=identity[1] or not _alive(fd):os.close(fd);continue
                notifier=QSocketNotifier(fd,QSocketNotifier.Type.Read,self)
                notifier.activated.connect(lambda *_,key=identity:self._remove(key))
                self.records[identity]=dict(fd=fd,notifier=notifier,app=app)
            except (OSError,RuntimeError):
                if fd is not None:
                    try:os.close(fd)
                    except OSError:pass
        self.visible=visible
        # A removed launcher is no longer a trusted activation target.
        for key,record in list(self.records.items()):
            if record['app']['id'] not in self.catalog:self._remove(key,False)
        if before!=self._items():self.changed.emit()
    def close(self):
        self._closed=True
        for key in list(self.records):self._remove(key,False)
        self.visible=set();self.changed.emit()

    def _handoff_location(self):
        """Only reuse observations inside this exact live compositor instance."""
        control=self.environment.get('ORBIT_NATIVE_CONTROL','')
        runtime=self.environment.get('XDG_RUNTIME_DIR','')
        if not control or not runtime:return None
        try:
            endpoint=Path(control);endpoint_info=endpoint.lstat();directory=Path(runtime)
            owner=directory.lstat()
            if not endpoint.is_absolute() or not stat.S_ISSOCK(endpoint_info.st_mode) or endpoint_info.st_uid!=os.getuid():return None
            if not directory.is_absolute() or not stat.S_ISDIR(owner.st_mode) or owner.st_uid!=os.getuid() or owner.st_mode&0o077:return None
            private=directory/f'orbit-{os.getuid()}';private.mkdir(mode=0o700,exist_ok=True);info=private.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:return None
            identity=[str(endpoint),endpoint_info.st_dev,endpoint_info.st_ino,endpoint_info.st_ctime_ns,self.environment.get('WAYLAND_DISPLAY','')]
            token=hashlib.sha256(json.dumps(identity).encode()).hexdigest()
            return private/f'background-handoff-{hashlib.sha256(str(endpoint).encode()).hexdigest()[:16]}.json',token
        except OSError:return None

    def saveHandoff(self):
        """A short-lived graceful-reload checkpoint; no enumeration or idle work."""
        if not self.enabled or self._closed:return True
        location=self._handoff_location()
        if not location:return True # Non-native previews have no recovery owner.
        path,token=location;rows=[]
        for (pid,birth),record in list(self.records.items())[:MAX_WATCHES]:
            info=_process_info(pid)
            if info and info['birth']==birth and not info['child'] and _alive(record['fd']):
                rows.append(dict(pid=pid,birth=birth,exe=info['exe'],app=record['app']['id']))
        payload=json.dumps(dict(version=1,session=token,created=time.time(),records=rows)).encode()
        if len(payload)>32768:return False
        temporary=None
        try:
            fd,temporary=tempfile.mkstemp(prefix='.background-handoff-',dir=path.parent)
            with os.fdopen(fd,'wb') as stream:stream.write(payload);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,path);return True
        except OSError:return False
        finally:
            if temporary:
                try:os.unlink(temporary)
                except FileNotFoundError:pass

    def restoreHandoff(self,apps):
        """Consume once; revalidate ownership, session, birth, executable and pidfd."""
        if not self.enabled or self._closed:return
        location=self._handoff_location()
        if not location:return
        path,token=location;fd=None
        try:
            fd=os.open(path,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW|os.O_NONBLOCK)
            metadata=os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid!=os.getuid() or metadata.st_mode&0o077 or metadata.st_nlink!=1 or metadata.st_size>32768:return
            with os.fdopen(fd,'rb') as stream:fd=None;payload=json.loads(stream.read(32769))
            if not isinstance(payload,dict) or payload.get('version')!=1 or payload.get('session')!=token:return
            created=payload.get('created');rows=payload.get('records')
            if not isinstance(created,(int,float)) or isinstance(created,bool) or not 0<=time.time()-created<=60 or not isinstance(rows,list) or len(rows)>MAX_WATCHES:return
            catalog={app['id']:app for app in apps};before=self._items();self.catalog=catalog
            for row in rows:
                if not isinstance(row,dict):continue
                pid,birth,ident=row.get('pid'),row.get('birth'),row.get('app')
                if type(pid) is not int or type(birth) is not int or not isinstance(ident,str) or ident not in catalog or (pid,birth) in self.records or len(self.records)>=MAX_WATCHES:continue
                info=_process_info(pid)
                if not info or info['child'] or info['birth']!=birth or info['exe']!=row.get('exe'):continue
                descriptor=None
                try:
                    descriptor=os.pidfd_open(pid,0)
                    if _birth(pid)!=birth or not _alive(descriptor):os.close(descriptor);continue
                    notifier=QSocketNotifier(descriptor,QSocketNotifier.Type.Read,self)
                    notifier.activated.connect(lambda *_,key=(pid,birth):self._remove(key))
                    self.records[(pid,birth)]=dict(fd=descriptor,notifier=notifier,app=catalog[ident])
                except (OSError,RuntimeError):
                    if descriptor is not None:
                        try:os.close(descriptor)
                        except OSError:pass
            if before!=self._items():self.changed.emit()
        except (OSError,ValueError,TypeError):pass
        finally:
            if fd is not None:os.close(fd)
            # Failed/untrusted snapshots are never kept for a future startup.
            try:path.unlink()
            except OSError:pass
