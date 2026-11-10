"""Event-driven Xwayland minimize/maximize compatibility for Orbit on Sway."""
import importlib,importlib.util,os,queue,select,sys,threading,time
from pathlib import Path
from project_paths import PROJECT_ROOT as ROOT, SOURCE_ROOT
MAX_PENDING=128


_xlib_load_lock=threading.RLock()
def load_xlib():
    with _xlib_load_lock:return _load_xlib()

def _load_xlib():
    """Load only the pure-Python Xlib package; never inject the venv's sys.path."""
    try:return importlib.import_module('Xlib')
    except ModuleNotFoundError as error:
        if error.name!='Xlib':raise
    preferred=ROOT/'.venv/lib'/f'python{sys.version_info.major}.{sys.version_info.minor}'/'site-packages/Xlib/__init__.py'
    candidates=[preferred]+sorted((ROOT/'.venv/lib').glob('python*/site-packages/Xlib/__init__.py'))
    for path in dict.fromkeys(candidates):
        if not path.is_file():continue
        spec=importlib.util.spec_from_file_location('Xlib',path,submodule_search_locations=[str(path.parent)])
        module=importlib.util.module_from_spec(spec);sys.modules['Xlib']=module
        try:spec.loader.exec_module(module);return module
        except Exception:sys.modules.pop('Xlib',None);raise
    raise ImportError('The Xwayland compatibility Xlib package is missing')


def managed_window(tree,xid=None,con_id=None):
    """Find only an actual Xwayland application container, never a shell surface."""
    pending=[tree];visited=0
    while pending and visited<10000:
        node=pending.pop();visited+=1
        window=node.get('window');ident=node.get('id')
        if type(window) is int and window>0 and type(ident) is int and ident>0 and node.get('pid')!=os.getpid():
            if (xid is None or window==xid) and (con_id is None or ident==con_id):return node
        pending.extend(node.get('nodes',[]));pending.extend(node.get('floating_nodes',[]))
    return None


class ClientRequests:
    """Pure request routing shared by the X listener and isolated fixture tests."""
    def __init__(self,actions,request,atoms,prepare=None,cancel=None):self.actions=actions;self.request=request;self.atoms=atoms;self.prepare=prepare;self.cancel=cancel
    def handle(self,xid,message,values):
        if type(xid) is not int or xid<=0 or len(values)<3:return None
        is_minimize=message==self.atoms['WM_CHANGE_STATE'] and values[0]==3
        is_maximize=message==self.atoms['_NET_WM_STATE'] and values[0] in (0,1,2) and any(v in (self.atoms['_NET_WM_STATE_MAXIMIZED_VERT'],self.atoms['_NET_WM_STATE_MAXIMIZED_HORZ']) for v in values[1:3])
        if not is_minimize and not is_maximize:return None
        tree=self.request(4);node=managed_window(tree,xid=xid)
        if node is None:return None
        ident=node['id']
        if self.cancel:self.cancel(ident)
        if is_minimize:self.actions.minimize(ident);return dict(xid=xid,minimized=True)
        desired=None if values[0]==2 else values[0]==1
        if self.prepare:maximized=self.actions.maximize(ident,desired=desired,prepare=lambda state:self.prepare(xid,state))
        else:maximized=self.actions.maximize(ident,desired=desired)
        return dict(xid=xid,maximized=bool(maximized),normal=bool(maximized))


class Controls:
    def __init__(self,enabled=True,actions=None,request=None):
        if request is None:
            from sway_events import request
        if actions is None:
            from window_actions import WindowActions
            actions=WindowActions(request=request)
        self.actions=actions;self.request=request;self._available=False;self._error='';self._closed=False
        self.readfd=self.writefd=None;self.thread=None;self.pending=queue.Queue(maxsize=MAX_PENDING)
        self._lifecycle_lock=threading.RLock();self._ready=threading.Event();self.settling={}
        if enabled:self.start()
    def start(self):
        """Connect lazily after the compositor reports its first Xwayland window."""
        with self._lifecycle_lock:
            if self._closed or (self.thread is not None and self.thread.is_alive()):return False
            if not os.environ.get('SWAYSOCK') or not os.environ.get('DISPLAY'):
                self._error='Sway Xwayland display is unavailable';return False
            # A disconnected Xwayland server can be replaced. Retire only an
            # already-finished observer's pipe before starting its replacement.
            for fd in (self.readfd,self.writefd):
                if fd is not None:
                    try:os.close(fd)
                    except OSError:pass
            self.readfd=self.writefd=None;self._available=False;self._error='';self._ready.clear()
            try:
                self.readfd,self.writefd=os.pipe2(os.O_NONBLOCK|os.O_CLOEXEC)
                self.thread=threading.Thread(target=self.run,name='orbit-xwayland-controls',daemon=True);self.thread.start()
            except (OSError,RuntimeError) as error:
                self._error=str(error)[:200]
                for fd in (self.readfd,self.writefd):
                    if fd is not None:
                        try:os.close(fd)
                        except OSError:pass
                self.readfd=self.writefd=None;self.thread=None
                return False
            return True
    def ensure_ready(self,timeout=2.0):
        """Wait for lazy observer startup only from a window-action worker.

        The first Xwayland app can become clickable before Xlib connects. Do
        not select a geometry-only maximize fallback on the GUI thread then.
        """
        if self._closed:return False
        if self._available:return True
        self.start()
        thread=self.thread
        if thread is None or not thread.is_alive():return False
        self._ready.wait(max(0,min(2.0,timeout)))
        return self._available and not self._closed
    @property
    def available(self):return self._available
    @property
    def error(self):return self._error
    @property
    def status(self):return dict(available=self._available,error=self._error)
    def restore_state(self,con_id):
        """Queue WM_STATE synchronization after the shared WindowActions.restore()."""
        if self._closed or self.writefd is None or type(con_id) is not int or con_id<=0:return False
        try:self.pending.put_nowait(con_id)
        except queue.Full:return False
        try:os.write(self.writefd,b'r')
        except OSError:pass
        return True
    def maximize(self,con_id,desired=None):
        """Run an Orbit button request on the X owner thread; call off the UI thread."""
        if type(con_id) is not int or con_id<=0:raise ValueError('Invalid window identifier')
        if self._closed or not self._available or self.writefd is None:raise ValueError('Xwayland window controls are unavailable')
        done=threading.Event();reply={};job=('maximize',con_id,desired,done,reply,time.monotonic()+10)
        try:self.pending.put_nowait(job)
        except queue.Full:raise ValueError('Window controls are busy')
        try:os.write(self.writefd,b'm')
        except OSError:reply['cancelled']=True;raise ValueError('Xwayland window controls disconnected')
        if not done.wait(10):reply['cancelled']=True;raise TimeoutError('Window control did not respond')
        if 'error' in reply:raise reply['error']
        return reply['value']
    def change_state(self,xid,minimized=None,maximized=None,normal=False):
        # Xlib calls remain exclusively on the observer thread.
        from Xlib import X,Xatom
        window=self.connection.create_resource_object('window',xid)
        prop=window.get_full_property(self.atoms['_NET_WM_STATE'],X.AnyPropertyType)
        states=[int(value) for value in prop.value] if prop is not None else []
        def state(atom,enabled):
            if enabled and atom not in states:states.append(atom)
            elif not enabled:
                while atom in states:states.remove(atom)
        if maximized is not None:
            state(self.atoms['_NET_WM_STATE_MAXIMIZED_VERT'],maximized);state(self.atoms['_NET_WM_STATE_MAXIMIZED_HORZ'],maximized)
        if minimized is not None or normal:
            iconic=bool(minimized) and not normal;state(self.atoms['_NET_WM_STATE_HIDDEN'],iconic)
            old=window.get_full_property(self.atoms['WM_STATE'],X.AnyPropertyType)
            icon=int(old.value[1]) if old is not None and len(old.value)>1 else 0
            window.change_property(self.atoms['WM_STATE'],self.atoms['WM_STATE'],32,[3 if iconic else 1,icon])
        window.change_property(self.atoms['_NET_WM_STATE'],Xatom.ATOM,32,states);self.connection.flush()
    def prepare_maximize(self,xid,maximized):
        # GTK records normal bounds when it sees MAXIMIZED. Deliver this state
        # before Sway's resize ConfigureNotify, after saving the actual normal rect.
        tree=self.request(4);node=managed_window(tree,xid=xid)
        if node:
            ident=node['id'];self.settling.pop(ident,None)
            if not maximized:
                from window_actions import find_window
                found=find_window(tree,ident);saved=self.actions.saved.get(ident)
                if found and saved:
                    hints=self.connection.create_resource_object('window',xid).get_wm_normal_hints() or {}
                    def increment(name):
                        try:value=hints[name]
                        except (KeyError,TypeError,AttributeError):value=1
                        return value if type(value) is int and 1<=value<=128 else 1
                    width_inc=increment('width_inc');height_inc=increment('height_inc')
                    border=max(0,min(32,found[0].get('current_border_width',0)))
                    deco=max(0,min(64,found[0].get('deco_rect',{}).get('height',0)))
                    now=time.monotonic()
                    if len(self.settling)>=128:self.settling.pop(next(iter(self.settling)))
                    tolerance=dict(x=width_inc+2*border,y=height_inc+deco+2*border,width=width_inc+2*border,height=height_inc+deco+2*border)
                    self.settling[ident]=dict(xid=xid,normal=dict(saved[0]),previous=found[0]['_outer_rect'],tolerance=tolerance,deadlines=[now+.08,now+.22,now+.55])
        self.change_state(xid,maximized=maximized,normal=True)
        self.connection.sync()
    def settle_timeout(self):
        return max(0,min(row['deadlines'][0] for row in self.settling.values())-time.monotonic()) if self.settling else None
    def settle_windows(self):
        """Repair only a GTK bounce back to the previous maximized bounds."""
        with self.actions.lock:self._settle_windows_locked()
    def _settle_windows_locked(self):
        now=time.monotonic();due=[ident for ident,row in self.settling.items() if row['deadlines'][0]<=now]
        if not due:return
        from window_actions import find_window
        from Xlib import X
        tree=self.request(4)
        def same(a,b):return all(abs(a[k]-b[k])<=1 for k in ('x','y','width','height'))
        for ident in due:
            row=self.settling.get(ident)
            if not row:continue
            row['deadlines'].pop(0)
            try:
                found=find_window(tree,ident)
                if not found or not found[1] or found[1].get('name')=='__i3_scratch' or self.actions.is_maximized(ident):self.settling.pop(ident,None);continue
                actual=found[0]['_outer_rect']
                if not same(actual,row['normal']):
                    if not all(abs(actual[k]-row['previous'][k])<=row['tolerance'].get(k,1) for k in ('x','y','width','height')):self.settling.pop(ident,None);continue
                    window=self.connection.create_resource_object('window',row['xid']);prop=window.get_full_property(self.atoms['_NET_WM_STATE'],X.AnyPropertyType)
                    states=list(prop.value) if prop is not None else []
                    if any(self.atoms[name] in states for name in ('_NET_WM_STATE_MAXIMIZED_VERT','_NET_WM_STATE_MAXIMIZED_HORZ')):self.settling.pop(ident,None);continue
                    self.actions._resize(ident,row['normal'])
            except (OSError,ValueError,ConnectionError):self.settling.pop(ident,None)
            if not row['deadlines']:self.settling.pop(ident,None)
    def drain_commands(self):
        while not self._closed:
            try:ident=self.pending.get_nowait()
            except queue.Empty:return
            if isinstance(ident,tuple):
                _,con_id,desired,done,reply,deadline=ident
                try:
                    self.settling.pop(con_id,None)
                    if reply.get('cancelled') or time.monotonic()>=deadline:raise TimeoutError('Window control request expired')
                    node=managed_window(self.request(4),con_id=con_id)
                    if not node:raise ValueError('Window has closed')
                    value=self.actions.maximize(con_id,desired=desired,prepare=lambda state:self.prepare_maximize(node['window'],state))
                    self.change_state(node['window'],maximized=value,normal=True);reply['value']=value
                except Exception as error:reply['error']=error
                finally:done.set()
                continue
            try:
                self.settling.pop(ident,None)
                node=managed_window(self.request(4),con_id=ident)
                if node:
                    with self.actions.lock:maximized=ident in self.actions.saved
                    self.change_state(node['window'],maximized=maximized,normal=True)
            except (OSError,ValueError,ConnectionError):pass
    def run(self):
        self.connection=None
        try:
            load_xlib()
            from Xlib import X,display
            self.connection=display.Display();self.connection.set_error_handler(lambda *_:1)
            names=('WM_CHANGE_STATE','WM_STATE','_NET_WM_STATE','_NET_WM_STATE_MAXIMIZED_VERT','_NET_WM_STATE_MAXIMIZED_HORZ','_NET_WM_STATE_HIDDEN')
            self.atoms={name:self.connection.intern_atom(name) for name in names};handler=ClientRequests(self.actions,self.request,self.atoms,self.prepare_maximize,lambda ident:self.settling.pop(ident,None))
            self.connection.screen().root.change_attributes(event_mask=X.SubstructureNotifyMask);self.connection.flush();self._available=True;self._ready.set()
            while not self._closed:
                if not self.connection.pending_events():
                    ready=select.select([self.connection.fileno(),self.readfd],[],[],self.settle_timeout())[0]
                    if self.readfd in ready:
                        try:os.read(self.readfd,4096)
                        except BlockingIOError:pass
                        if self._closed:break
                        self.drain_commands()
                while not self._closed and self.connection.pending_events():
                    event=self.connection.next_event()
                    if event.type!=X.ClientMessage or event.data[0]!=32:continue
                    try:
                        xid=int(event.window.id if hasattr(event.window,'id') else event.window)
                        result=handler.handle(xid,int(event.client_type),[int(v) for v in event.data[1]])
                        if result:self.change_state(**result)
                    except (OSError,ValueError,ConnectionError):pass
                self.settle_windows()
        except Exception as error:
            if not self._closed:self._error=str(error)[:200]
        finally:
            self._available=False;self._ready.set()
            if self.connection:
                try:self.connection.close()
                except Exception:pass
    def close(self):
        with self._lifecycle_lock:
            if self._closed:return
            self._closed=True;self._ready.set()
            if self.writefd is not None:
                try:os.write(self.writefd,b'c')
                except OSError:pass
            if self.thread:self.thread.join(timeout=4)
            if not self.thread or not self.thread.is_alive():
                for fd in (self.readfd,self.writefd):
                    if fd is not None:
                        try:os.close(fd)
                        except OSError:pass
                self.readfd=self.writefd=None
