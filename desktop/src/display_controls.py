"""Demand-driven Wayland display configuration with independent timed rollback."""
import json,math,os,select,subprocess,sys,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from qt_compat import QObject,Property,Signal,Slot,QTimer
from display_config import catalog,validated
from project_paths import PROJECT_ROOT as ROOT, SOURCE_ROOT

class DisplayControls(QObject):
    changed=Signal();notice=Signal(str);completed=Signal(object)
    def __init__(self,enabled=True,config_path=None,requester=None):
        super().__init__();self.enabled=enabled;self.closed=False;self.rows=[];self.process=None;self.pending_output='';self.deadline=0
        self.native_supported=False
        if os.environ.get('ORBIT_NATIVE_CONTROL'):
            try:
                from native_compositor import NativeCompositor
                self.native_supported=bool(NativeCompositor(os.environ['ORBIT_NATIVE_CONTROL']).status().get('control_capabilities',{}).get('display'))
            except (OSError,ValueError,RuntimeError):pass
        self.config_path=Path(config_path or (Path(os.environ.get('ORBIT_DATA',str(ROOT/'data')))/'outputs.conf')).absolute()
        if os.environ.get('ORBIT_NATIVE_CONTROL') and config_path is None:self.config_path=self.config_path.with_name('outputs-native.json')
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='orbit-display');self.requester=requester
        self.data=dict(available=False,busy=False,error='',pending=False,secondsRemaining=0)
        self.completed.connect(self._complete);self.timer=QTimer(self);self.timer.setInterval(250);self.timer.timeout.connect(self._tick)
    state=Property('QVariantMap',lambda s:dict(s.data),notify=changed)
    outputs=Property('QVariantList',lambda s:[dict(r) for r in s.rows],notify=changed)
    def _request(self,kind,payload=''):
        if self.requester:return self.requester(kind,payload)
        if os.environ.get('ORBIT_NATIVE_CONTROL'):
            from native_compositor import NativeCompositor
            if kind!=3:raise RuntimeError('Native display configuration is not supported yet')
            return NativeCompositor(os.environ['ORBIT_NATIVE_CONTROL']).snapshot().get('outputs',[])
        from sway_events import request
        return request(kind,payload)
    def _submit(self,work,kind):
        if self.closed or self.data['busy']:return False
        self.data.update(busy=True,error='');self.changed.emit()
        def run():
            try:return dict(kind=kind,value=work())
            except Exception as error:return dict(kind=kind,error=str(error)[:300])
        future=self.pool.submit(run);future.add_done_callback(lambda f:self.completed.emit(f.result()) if not self.closed and not f.cancelled() else None)
        return True
    @Slot()
    def refresh(self):
        if not self.enabled or (not self.requester and not os.environ.get('SWAYSOCK') and not os.environ.get('ORBIT_NATIVE_CONTROL')):
            self.data.update(available=False,error='Display configuration requires an Orbit Wayland session');self.changed.emit();return
        self._submit(lambda:catalog(self._request(3)),'refresh')
    def _read(self,process,timeout=8):
        if not select.select([process.stdout],[],[],timeout)[0]:raise RuntimeError('Display transaction did not respond; previous settings will be restored')
        raw=process.stdout.readline(4096)
        if not raw:raise RuntimeError('Display transaction ended; previous settings will be restored')
        result=json.loads(raw)
        if not result.get('ok'):raise RuntimeError(result.get('error','Display settings failed'))
        return result
    def _retire(self,process):
        try:
            if process.stdin:process.stdin.close()
        except OSError:pass
        try:process.wait(timeout=8)
        except subprocess.TimeoutExpired:pass # Never kill a process responsible for restoring the screen.
        if process.stdout:process.stdout.close()
        if self.process is process:self.process=None
    @Slot(str,str,float,str,int,int)
    def apply(self,name,mode,scale,transform,x,y):
        if self.data['pending'] or self.data['busy'] or self.closed:return
        if not self.enabled:return
        if os.environ.get('ORBIT_NATIVE_CONTROL') and not self.native_supported:
            self.data['error']='Native display mode changes and rollback are not supported by this backend yet';self.notice.emit(self.data['error']);self.changed.emit();return
        try:settings=validated(self.rows,name,mode,scale,transform,x,y)
        except ValueError as error:self.data['error']=str(error);self.changed.emit();return
        def work():
            # Fresh validation prevents a stale panel applying to a removed monitor.
            validated(catalog(self._request(3)),**settings)
            if self.requester:raise RuntimeError('Fake display backends cannot change the real display')
            process=subprocess.Popen([sys.executable,str(ROOT/'tools/display-watchdog.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,start_new_session=True)
            self.process=process
            try:
                process.stdin.write(json.dumps(dict(settings=settings,config_path=str(self.config_path),seconds=15))+'\n');process.stdin.flush()
                result=self._read(process)
                if self.closed:self._retire(process);raise RuntimeError('Display panel closed; restoring previous settings')
                return result
            except Exception:self._retire(process);raise
        self.pending_output=name;self._submit(work,'apply')
    @Slot()
    def confirm(self):self._decide(True)
    @Slot()
    def revert(self):self._decide(False)
    def _decide(self,keep):
        if self.closed or not self.data['pending'] or self.data['busy']:return
        def work():
            process=self.process
            if process is None:raise RuntimeError('Display transaction has already ended')
            try:
                try:process.stdin.write('KEEP\n' if keep else 'REVERT\n');process.stdin.flush()
                except (OSError,BrokenPipeError):pass
                return self._read(process)
            finally:self._retire(process)
        self._submit(work,'confirm' if keep else 'revert')
    @Slot(object)
    def _complete(self,result):
        if self.closed:return
        kind=result['kind'];self.data['busy']=False
        if result.get('error'):
            self.data['error']=result['error'];self.notice.emit(result['error'])
            if kind=='refresh':self.rows=[];self.data['available']=False
            if kind!='refresh':self.timer.stop();self.data.update(pending=False,secondsRemaining=0)
        elif kind=='refresh':
            self.rows=result['value'];self.data['available']=bool(self.rows) and (not os.environ.get('ORBIT_NATIVE_CONTROL') or self.native_supported)
            if os.environ.get('ORBIT_NATIVE_CONTROL') and not self.native_supported:self.data['error']='Native display mode changes and rollback are not supported by this backend yet'
            if self.data['pending'] and not any(r['name']==self.pending_output for r in self.rows):self.revert()
        elif kind=='apply':
            self.deadline=result['value'].get('deadline',time.monotonic()+15)
            self.data.update(pending=True,secondsRemaining=max(0,math.ceil(self.deadline-time.monotonic())));self.timer.start()
        else:
            self.timer.stop();self.data.update(pending=False,secondsRemaining=0);self.refresh()
        self.changed.emit()
    def _tick(self):
        if not self.data['pending']:self.timer.stop();return
        seconds=max(0,math.ceil(self.deadline-time.monotonic()))
        if seconds!=self.data['secondsRemaining']:self.data['secondsRemaining']=seconds;self.changed.emit()
        if not seconds and not self.data['busy']:self.revert()
    def close(self):
        if self.closed:return
        self.closed=True;self.timer.stop()
        process=self.process
        if process:
            try:process.stdin.close()
            except (OSError,ValueError):pass
        self.pool.shutdown(wait=True,cancel_futures=True)
        if self.process:self._retire(self.process)
