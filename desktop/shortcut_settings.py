"""Validated shortcut bindings, applied explicitly with no key-event polling."""
import json,os,re,tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from qt_compat import QObject,Property,Signal,Slot

ROOT=Path(__file__).resolve().parent
from shortcut_config import LABELS,DEFAULTS,ACTIONS,RESERVED,chord,validate,binding_line,config_lines

def atomic_write(path,bindings):
    path=Path(path)
    if path.is_symlink():raise ValueError('Refusing a linked shortcut configuration')
    path.parent.mkdir(parents=True,exist_ok=True)
    text='# Orbit shortcuts\n# orbit-shortcuts: '+json.dumps(bindings,separators=(',',':'))+'\n'+'\n'.join(config_lines(bindings))+'\n'
    fd,name=tempfile.mkstemp(prefix='.orbit-shortcuts-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:stream.write(text);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

class ShortcutSettings(QObject):
    changed=Signal();notice=Signal(str);completed=Signal(object)
    def __init__(self,enabled=True,path=None,command=None):
        super().__init__();self.native=None
        if os.environ.get('ORBIT_NATIVE_CONTROL') and command is None:
            from native_backend import NativeWindowActions
            self.native=NativeWindowActions()
        self.enabled=bool(enabled and (self.native or command is not None or os.environ.get('SWAYSOCK')))
        self.path=Path(path or Path(os.environ.get('ORBIT_DATA',str(ROOT/'data')))/'shortcuts.conf')
        self.values=dict(DEFAULTS);self.error='';self.busy=False;self.closed=False;self.pool=None
        if self.native:command=self.native.command
        if command is None:
            from sway_events import command as sway_command
            command=sway_command
        self.command=command
        try:
            if self.path.is_file() and not self.path.is_symlink() and self.path.stat().st_size<=16384:
                metadata=next((line[len('# orbit-shortcuts: '):] for line in self.path.read_text().splitlines() if line.startswith('# orbit-shortcuts: ')),None)
                if metadata:self.values=validate(json.loads(metadata))
        except (OSError,ValueError):pass
        self.desired=dict(self.values);self.completed.connect(self._finished)
        if self.native and self.enabled:self._start()
    state=Property('QVariantMap',lambda s:dict(available=s.enabled,busy=s.busy,error=s.error),notify=changed)
    bindings=Property('QVariantList',lambda s:[dict(action=a,label=LABELS[a],chord=s.values[a]) for a in LABELS],notify=changed)
    actions=Property('QVariantList',lambda s:[dict(value=a,label=label) for a,label in LABELS.items()],constant=True)
    @Slot(str,str)
    def setBinding(self,action,value):
        if self.closed:return
        try:
            if action not in ACTIONS:raise ValueError('Unknown shortcut action')
            desired=validate(dict(self.desired,**{action:value}))
        except ValueError as error:self.error=str(error);self.changed.emit();self.notice.emit(self.error);return
        if not self.enabled:return self.notice.emit('Shortcut controls require an Orbit Wayland session')
        self.desired=desired
        if not self.busy:self._start()
    @Slot(str)
    def resetBinding(self,action):
        if action in DEFAULTS:self.setBinding(action,DEFAULTS[action])
    def _start(self):
        values=dict(self.desired);previous=dict(self.values);self.busy=True;self.error='';self.changed.emit()
        if self.pool is None:self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='orbit-shortcuts')
        def apply(values,old):
            if self.native:self.native.configure_shortcuts(values);return
            removed=[f'unbindsym {value}' for value in set(old.values()) if value and value not in values.values()]
            # Missing bindings are harmless and Sway reports them as errors;
            # issue each removal separately, then require every new bind.
            for line in removed:
                try:self.command(line)
                except ValueError:pass
            for action,value in values.items():
                if value:self.command(binding_line(action,value))
        def work():
            try:
                if self.path.is_symlink():raise ValueError('Refusing a linked shortcut configuration')
                apply(values,previous);atomic_write(self.path,values);return dict(values=values)
            except Exception as error:
                try:apply(previous,values)
                except Exception:pass
                return dict(error=str(error),attempt=values)
        future=self.pool.submit(work);future.add_done_callback(lambda f:self.completed.emit(f.result()))
    @Slot(object)
    def _finished(self,result):
        self.busy=False
        if self.closed:return
        if 'error' in result:
            self.error=result['error'];self.notice.emit(self.error)
            if self.desired==result['attempt']:self.desired=dict(self.values)
        else:self.values=result['values']
        self.changed.emit()
        if self.desired!=self.values:self._start()
    @Slot()
    def refresh(self):self.changed.emit()
    def close(self):
        self.closed=True
        if self.pool:self.pool.shutdown(wait=True,cancel_futures=False)
