"""Explicit NetworkManager connection controls; metadata refresh only on demand."""
import os,re,shutil,subprocess
from concurrent.futures import ThreadPoolExecutor
from qt_compat import QObject,Property,Signal,Slot

UUID=re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}')
LABELS={'802-3-ethernet':'Ethernet','ethernet':'Ethernet','802-11-wireless':'Wi-Fi','wifi':'Wi-Fi','vpn':'VPN','wireguard':'WireGuard','bridge':'Bridge'}

def run(args):
    result=subprocess.run(args,capture_output=True,text=True,timeout=20,env={**os.environ,'LC_ALL':'C'})
    if result.returncode:raise RuntimeError(result.stderr.strip()[:220] or 'NetworkManager request failed')
    return result.stdout

def fields(line):
    """nmcli -t escaping includes both literal colons and backslashes."""
    result=[];part=[];escaped=False
    for char in line:
        if escaped:part.append(char);escaped=False
        elif char=='\\':escaped=True
        elif char==':':result.append(''.join(part));part=[]
        else:part.append(char)
    if escaped:part.append('\\')
    result.append(''.join(part));return result

def connections(runner=run):
    active={line.strip().lower() for line in runner(['nmcli','-t','-f','UUID','connection','show','--active']).splitlines()[:256] if UUID.fullmatch(line.strip())}
    raw=runner(['nmcli','-t','--escape','yes','-f','UUID,NAME,TYPE,DEVICE','connection','show'])
    rows=[];seen=set()
    for line in raw.splitlines()[:256]:
        parts=fields(line)
        if len(parts)!=4 or not UUID.fullmatch(parts[0]):continue
        ident,name,kind,device=parts;ident=ident.lower()
        if ident in seen:continue
        seen.add(ident);rows.append(dict(uuid=ident,name=name[:200] or 'Unnamed connection',type=kind,label=LABELS.get(kind,kind[:64]),device='' if device in ('','--') else device[:80],active=ident in active))
    return sorted(rows,key=lambda row:(not row['active'],row['label'],row['name'].casefold()))

def change(action,ident,runner=run):
    if action not in ('activate','disconnect','forget') or not isinstance(ident,str) or not UUID.fullmatch(ident):raise ValueError('Invalid network connection')
    row=next((row for row in connections(runner) if row['uuid']==ident.lower()),None)
    if row is None:raise ValueError('This connection is no longer available')
    if action=='disconnect' and not row['active']:raise ValueError('This connection is already disconnected')
    verb={'activate':'up','disconnect':'down','forget':'delete'}[action]
    runner(['nmcli','--wait','10','connection',verb,'uuid',row['uuid']])
    return connections(runner)

class NetworkControls(QObject):
    changed=Signal();notice=Signal(str);completed=Signal(object)
    def __init__(self,enabled=True,runner=None,launcher=None):
        super().__init__();self.enabled=enabled;self.runner=runner or run;self.launcher=launcher or subprocess.Popen;self.closed=False;self.pool=None;self.rows=[]
        self.data=dict(available=bool(enabled and (runner is not None or shutil.which('nmcli'))),busy=False,error='',advancedAvailable=bool(shutil.which('nm-connection-editor')))
        self.completed.connect(self._finished)
    state=Property('QVariantMap',lambda self:dict(self.data),notify=changed)
    connections=Property('QVariantList',lambda self:[dict(row) for row in self.rows],notify=changed)
    def _submit(self,work):
        if self.closed or self.data['busy']:return
        if not self.data['available']:self.data['error']='NetworkManager is unavailable';self.changed.emit();return
        self.data.update(busy=True,error='');self.changed.emit()
        if self.pool is None:self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='orbit-network')
        def task():
            try:return dict(rows=work())
            except Exception as error:return dict(error=str(error)[:240])
        future=self.pool.submit(task);future.add_done_callback(lambda f:self.completed.emit(f.result()) if not self.closed else None)
    @Slot(object)
    def _finished(self,result):
        if self.closed:return
        self.data['busy']=False
        if 'error' in result:self.data['error']=result['error'];self.notice.emit(result['error'])
        else:self.rows=result['rows'];self.data['error']=''
        self.changed.emit()
    @Slot()
    def refresh(self):self._submit(lambda:connections(self.runner))
    @Slot(str)
    def activate(self,ident):self._submit(lambda:change('activate',ident,self.runner))
    @Slot(str)
    def disconnect(self,ident):self._submit(lambda:change('disconnect',ident,self.runner))
    @Slot(str)
    def forget(self,ident):self._submit(lambda:change('forget',ident,self.runner))
    @Slot()
    def openAdvanced(self):
        if not self.enabled:return
        binary=shutil.which('nm-connection-editor')
        if not binary:return self.notice.emit('Install NetworkManager connection editor for advanced network settings')
        try:
            from desktop import application_environment
            self.launcher([binary],env=application_environment(),start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        except OSError as error:self.notice.emit(str(error)[:220])
    def close(self):
        self.closed=True
        if self.pool:self.pool.shutdown(wait=True,cancel_futures=True)
