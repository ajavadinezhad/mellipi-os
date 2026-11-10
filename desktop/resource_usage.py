"""Bounded /proc snapshots, sampled only while Orbit's usage panel is open."""
import os,pwd,re
from pathlib import Path
from qt_compat import QObject,Property,Signal,Slot,QTimer
EMPTY=dict(cpuPercent=0.0,cpuReady=False,cpuAvailable=False,memoryUsed=0.0,memoryTotal=0.0,memoryPercent=0.0,memoryReady=False,swapUsed=0.0,swapTotal=0.0,swapPercent=0.0,error='')


def parse_cpu(text):
    """Return aggregate CPU total/idle ticks without double-counting guest time."""
    for line in str(text)[:16384].splitlines()[:128]:
        fields=line.split()
        if not fields or fields[0]!='cpu':continue
        try:values=[int(value) for value in fields[1:9]]
        except ValueError:return None
        if len(values)<4 or any(value<0 or value>0xffffffffffffffff for value in values):return None
        return sum(values),values[3]+(values[4] if len(values)>4 else 0)
    return None


def cpu_delta(previous,current):
    if previous is None or current is None:return dict(cpuPercent=0.0,cpuReady=False)
    total=current[0]-previous[0];idle=current[1]-previous[1]
    if total<=0 or idle<0 or idle>total:return dict(cpuPercent=0.0,cpuReady=False)
    return dict(cpuPercent=round(max(0.0,min(100.0,100.0*(total-idle)/total)),1),cpuReady=True)


def parse_memory(text):
    wanted={'MemTotal','MemAvailable','MemFree','Buffers','Cached','SReclaimable','Shmem','SwapTotal','SwapFree'}
    values={}
    for line in str(text)[:65536].splitlines()[:512]:
        match=re.fullmatch(r'([A-Za-z_]+):\s*([0-9]{1,18})\s+kB\s*',line)
        if match and match[1] in wanted:
            number=int(match[2])
            if number<=0xffffffffffff:values[match[1]]=number
    total=values.get('MemTotal',0)
    available=values.get('MemAvailable',values.get('MemFree',0)+values.get('Buffers',0)+values.get('Cached',0)+values.get('SReclaimable',0)-values.get('Shmem',0))
    used=total-max(0,min(total,available))
    swap=values.get('SwapTotal',0);swap_used=swap-max(0,min(swap,values.get('SwapFree',swap)))
    return dict(memoryUsed=round(used/1024,1),memoryTotal=round(total/1024,1),memoryPercent=round(100*used/total,1) if total else 0.0,memoryReady=total>0,
                swapUsed=round(swap_used/1024,1),swapTotal=round(swap/1024,1),swapPercent=round(100*swap_used/swap,1) if swap else 0.0)


def read_bounded(path,limit):
    with Path(path).open() as handle:return handle.read(limit)


class ResourceUsage(QObject):
    changed=Signal()
    def __init__(self,enabled=True,parent=None,proc_root='/proc'):
        super().__init__(parent);self.enabled=bool(enabled);self.proc_root=Path(proc_root);self._active=False;self._closed=False;self._previous=None;self._state=EMPTY.copy()
        try:
            user=pwd.getpwuid(os.getuid());self._username=user.pw_name[:128];self._display_name=' '.join(user.pw_gecos.split(',')[0].split())[:160]
        except (KeyError,OSError):self._username=str(os.getuid());self._display_name=''
        self.timer=QTimer(self);self.timer.setInterval(2000);self.timer.timeout.connect(self.sample)
    username=Property(str,lambda self:self._username,constant=True)
    displayName=Property(str,lambda self:self._display_name,constant=True)
    state=Property('QVariantMap',lambda self:dict(self._state),notify=changed)
    active=Property(bool,lambda self:self._active,notify=changed)
    @Slot(bool)
    def setActive(self,active):
        active=bool(active) and self.enabled and not self._closed
        if active==self._active:return
        self._active=active;self._previous=None
        if active:self.sample();self.timer.start();self.changed.emit()
        else:self.timer.stop();self._state={**self._state,'cpuReady':False};self.changed.emit()
    @Slot()
    def sample(self):
        if not self._active or self._closed:return
        cpu=None;memory=EMPTY.copy();error=False
        try:cpu=parse_cpu(read_bounded(self.proc_root/'stat',16384))
        except (OSError,UnicodeError):error=True
        try:memory=parse_memory(read_bounded(self.proc_root/'meminfo',65536))
        except (OSError,UnicodeError):error=True
        result={**EMPTY,**memory,**cpu_delta(self._previous,cpu),'cpuAvailable':cpu is not None,'error':'Some usage information is unavailable' if error else ''}
        self._previous=cpu
        if result!=self._state:self._state=result;self.changed.emit()
    def close(self):
        if self._closed:return
        self.setActive(False);self.timer.stop();self._previous=None;self._closed=True
