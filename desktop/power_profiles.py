"""Real system power profiles via the installed service client, on demand."""
import os,re,shutil,subprocess
from concurrent.futures import ThreadPoolExecutor
from qt_compat import QObject,Property,Signal,Slot
LABELS={'power-saver':'Power saver','balanced':'Balanced','performance':'Performance'}

def run(args):
    result=subprocess.run(args,capture_output=True,text=True,timeout=8,env={**os.environ,'LC_ALL':'C'})
    if result.returncode:raise RuntimeError(result.stderr.strip()[:220] or 'System power profile service unavailable')
    return result.stdout

def snapshot(runner=run):
    text=runner(['powerprofilesctl','list']);rows=[];active='';degraded={};current=''
    for line in text.splitlines()[:128]:
        match=re.fullmatch(r'\s*(\*)?\s*(power-saver|balanced|performance):\s*',line)
        if match:
            current=match[2]
            if not any(r['name']==current for r in rows):rows.append(dict(name=current,label=LABELS[current]))
            if match[1]:active=current
        elif current and 'Degraded:' in line:
            value=line.split('Degraded:',1)[1].strip()
            if value.lower() not in ('','no','none'):degraded[current]=value[:180]
    if not rows:raise RuntimeError('No system power profiles were reported')
    if not active:active=runner(['powerprofilesctl','get']).strip()
    if active not in [row['name'] for row in rows]:raise RuntimeError('The active system power profile is unavailable')
    return dict(active=active,profiles=rows,degraded=degraded.get(active,''))

def set_profile(name,runner=run):
    if name not in LABELS:raise ValueError('Invalid system power profile')
    before=snapshot(runner)
    if name not in [r['name'] for r in before['profiles']]:raise ValueError('This power profile is not supported')
    runner(['powerprofilesctl','set',name]);return snapshot(runner)

class PowerProfiles(QObject):
    changed=Signal();notice=Signal(str);completed=Signal(object)
    def __init__(self,enabled=True,runner=None):
        super().__init__();self.enabled=enabled;self.runner=runner or run;self.closed=False;self.pool=None;self.rows=[]
        self.supported=bool(enabled and (runner is not None or shutil.which('powerprofilesctl')))
        self.data=dict(available=False,busy=False,error='' if self.supported else 'Install power-profiles-daemon to choose a system power mode',active='',degraded='')
        self.completed.connect(self._finished)
    state=Property('QVariantMap',lambda self:dict(self.data),notify=changed)
    profiles=Property('QVariantList',lambda self:[dict(r) for r in self.rows],notify=changed)
    def _submit(self,work):
        if self.closed or self.data['busy']:return
        if not self.supported:self.changed.emit();return
        self.data.update(busy=True,error='');self.changed.emit()
        if self.pool is None:self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='orbit-power-profile')
        def task():
            try:return dict(value=work())
            except Exception as error:return dict(error=str(error)[:240])
        future=self.pool.submit(task);future.add_done_callback(lambda f:self.completed.emit(f.result()) if not self.closed else None)
    @Slot(object)
    def _finished(self,result):
        if self.closed:return
        self.data['busy']=False
        if 'error' in result:self.data.update(available=False,error=result['error']);self.rows=[];self.notice.emit(result['error'])
        else:
            value=result['value'];self.rows=value['profiles'];self.data.update(available=True,error='',active=value['active'],degraded=value['degraded'])
        self.changed.emit()
    @Slot()
    def refresh(self):self._submit(lambda:snapshot(self.runner))
    @Slot(str)
    def setProfile(self,name):self._submit(lambda:set_profile(name,self.runner))
    def close(self):
        self.closed=True
        if self.pool:self.pool.shutdown(wait=True,cancel_futures=True)
