"""Explicit, event-fed safe logout review. Never quits or signals processes.

The adapter must feed all current top-level windows, including minimized ones,
and cancel when the review is dismissed. close_window requests the compositor's
normal client close protocol; it must never implement a force kill.
ListInhibitors protects shutdown/sleep, not user logout. Query shutdown
protections only for reboot/power-off; every action still reviews application
windows and waits for their normal close/save flow.
"""
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from qt_compat import QObject, Property, Signal, Slot


def parse_inhibitors(raw):
    if not isinstance(raw, str) or len(raw)>262144:
        raise ValueError('Invalid system protection reply')
    value=json.loads(raw)
    if not isinstance(value,dict) or value.get('type')!='a(ssssuu)':
        raise ValueError('Unexpected system protection reply')
    data=value.get('data')
    if not isinstance(data,list) or len(data)!=1 or not isinstance(data[0],list) or len(data[0])>1024:
        raise ValueError('Invalid system protection list')
    result=[]
    for row in data[0]:
        if not isinstance(row,list) or len(row)!=6 or not all(isinstance(s,str) for s in row[:4]) or not all(type(n) is int and 0<=n<=0xffffffff for n in row[4:]):
            raise ValueError('Invalid system protection entry')
        what,who,why,mode,uid,pid=row
        if mode not in ('block','delay','block-weak'):
            raise ValueError('Unknown system protection mode')
        # Sleep-only inhibitors include Orbit's own before-sleep locker. They
        # must not deadlock exit. Shutdown protections gate only reboot/power-off.
        if 'shutdown' not in what.split(':'):continue
        result.append(dict(who=who[:160] or 'Application',reason=why[:500] or 'System operation in progress',mode=mode,pid=pid,uid=uid))
    return result


def read_inhibitors():
    """One read-only system-bus call; no elevated permission or override."""
    result=subprocess.run(['busctl','--system','--json=short','--timeout=3','call',
        'org.freedesktop.login1','/org/freedesktop/login1','org.freedesktop.login1.Manager','ListInhibitors'],
        capture_output=True,text=True,timeout=4,check=False)
    if result.returncode:
        raise RuntimeError('Could not check system protections. Return to work or try again.')
    return parse_inhibitors(result.stdout)


class SessionExit(QObject):
    changed=Signal()
    readyToExit=Signal()
    focusRequested=Signal(str)
    completed=Signal(object)

    def __init__(self,close_window,inhibitor_reader=None,enabled=True,parent=None):
        super().__init__(parent)
        self.enabled=bool(enabled);self.close_window=close_window;self.reader=inhibitor_reader or read_inhibitors
        self._active=False;self._armed=False;self._busy=False;self._closed=False;self._action='logout'
        self._windows=[];self._inhibitors=[];self._error='';self._generation=0;self._revision=0
        self._requested=set();self._targets=set();self._pool=None;self._again=False;self._sending=False
        self.completed.connect(self._complete)

    state=Property('QVariantMap',lambda s:dict(active=s._active,armed=s._armed,checking=s._busy,
        error=s._error,enabled=s.enabled,windowCount=len(s._windows),action=s._action),notify=changed)
    windows=Property('QVariantList',lambda s:[dict(row,closeRequested=row['id'] in s._requested) for row in s._windows],notify=changed)
    inhibitors=Property('QVariantList',lambda s:[dict(row) for row in s._inhibitors],notify=changed)

    @Slot(object)
    def setWindows(self,rows):
        normalized=[];seen=set()
        for row in rows:
            ident=str(row.get('id',''))
            if not ident or ident in seen:continue
            seen.add(ident)
            normalized.append(dict(id=ident,title=str(row.get('title') or row.get('klass') or 'Application')[:300],
                app=str(row.get('klass') or '')[:160],minimized=bool(row.get('minimized'))))
        identities={row['id'] for row in normalized}
        previous={row['id'] for row in self._windows}
        if normalized==self._windows:return
        self._windows=normalized
        if identities!=previous:self._revision+=1
        self.changed.emit()
        if self._active and self._armed and not normalized and not self._sending:self._check()

    @Slot()
    @Slot(str)
    def openReview(self,action='logout'):
        if action not in ('logout','reboot','shutdown'):return
        if not self.enabled or self._closed:return
        self._action=action
        self._generation+=1;self._active=True;self._armed=False;self._error='';self._inhibitors=[]
        self._requested=set();self._targets=set();self.changed.emit();self._check()

    @Slot()
    def cancel(self):
        self._generation+=1;self._active=False;self._armed=False;self._again=False
        self._targets=set();self._error='';self.changed.emit()

    @Slot(str)
    def focusWindow(self,ident):
        if self._active and any(row['id']==ident for row in self._windows):self.focusRequested.emit(ident)

    @Slot()
    def closeAndWait(self):
        if not self._active or self._armed or self._closed:return
        self._generation+=1;self._armed=True;self._targets={row['id'] for row in self._windows}
        self._error='';self.changed.emit();self._check()

    @Slot()
    def recheck(self):
        if self._active and not self._closed:self._check()

    def closeFailed(self,ident,message,generation):
        if self._closed or not self._active or generation!=self._generation:return
        self._requested.discard(ident);self._armed=False
        self._error=str(message)[:500] or 'The application could not be asked to close.'
        self.changed.emit()

    def _check(self):
        if not self._active or self._closed:return
        if self._busy:self._again=True;return
        self._busy=True;self._again=False;self._error=''
        generation,revision,action=self._generation,self._revision,self._action
        self.changed.emit()
        if self._pool is None:self._pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='orbit-exit-check')
        def work():
            # A machine-wide updater/standing shutdown inhibitor must not
            # block signing out, or show unrelated shutdown guidance. Do not
            # query logind at all for logout: a bus failure is irrelevant too.
            try:return dict(generation=generation,revision=revision,
                            rows=self.reader() if action in ('reboot','shutdown') else [])
            except Exception as error:return dict(generation=generation,revision=revision,error=str(error)[:500])
        future=self._pool.submit(work)
        future.add_done_callback(lambda f:self.completed.emit(f.result()) if not self._closed and not f.cancelled() else None)

    @Slot(object)
    def _complete(self,result):
        self._busy=False
        if self._closed:return
        if not self._active:self.changed.emit();return
        if result['generation']!=self._generation or result['revision']!=self._revision:
            self._check();return
        self._inhibitors=result.get('rows',[]);self._error=result.get('error','')
        again=self._again;self._again=False
        self.changed.emit()
        # A delay inhibitor is a standing request for PrepareForShutdown, not
        # an operation already in progress. Waiting for its release before system
        # shutdown would deadlock ordinary browsers. Blocking protections remain visible
        # and conservatively prevent this flow; no logind override is issued.
        if self._error or any(row.get('mode')!='delay' for row in self._inhibitors):return
        if self._armed:
            if not self._windows:
                # Consume consent before emitting, so reentrant calls and late
                # replies cannot produce a second exit or override cancellation.
                self._armed=False;self._active=False;self._generation+=1
                consent=self._generation;self.changed.emit()
                if consent==self._generation and not self._closed:self.readyToExit.emit()
                return
            self._sending=True;generation=self._generation
            try:
                for row in list(self._windows):
                    ident=row['id']
                    if not self._active or not self._armed or generation!=self._generation:break
                    if ident not in self._targets or ident in self._requested:continue
                    # Mark before calling adapter: save dialogs/new windows and
                    # reentrant events must never cause a second close request.
                    self._requested.add(ident)
                    try:
                        if self.close_window(ident) is False:raise RuntimeError('The application could not be asked to close.')
                    except Exception as error:
                        self._requested.discard(ident)
                        self._error=str(error)[:500];self._armed=False;break
            finally:self._sending=False
            self.changed.emit()
            if self._active and self._armed and not self._windows:self._check()
        elif again:self._check()

    def close(self):
        self.cancel();self._closed=True
        if self._pool:self._pool.shutdown(wait=False,cancel_futures=True)
