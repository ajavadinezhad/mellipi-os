"""Sway IPC events, with bounded tracking for Sway's missing floating-move events."""
import json,os,select,socket,struct,threading,time
MAGIC=b'i3-ipc';HEADER=struct.Struct('<6sII')

def receive(sock):
    def exact(n):
        data=bytearray()
        while len(data)<n:
            part=sock.recv(n-len(data))
            if not part:raise ConnectionError('Sway disconnected')
            data.extend(part)
        return data
    magic,size,kind=HEADER.unpack(exact(HEADER.size))
    if magic!=MAGIC or size>8_000_000:raise ValueError('Invalid Sway response')
    return kind,json.loads(exact(size))

def request(kind,payload=''):
    data=payload.encode();sock=socket.socket(socket.AF_UNIX);sock.settimeout(3)
    try:
        sock.connect(os.environ['SWAYSOCK']);sock.sendall(HEADER.pack(MAGIC,len(data),kind)+data)
        return receive(sock)[1]
    finally:sock.close()

def command(text):
    result=request(0,text)
    if not all(item.get('success') for item in result):raise ValueError('Compositor action failed')
    return result

def frame_geometry(node,outer):
    height=node.get('deco_rect',{}).get('height',0)
    if not outer or height<=0 or node.get('border')!='normal' or node.get('fullscreen_mode'):return {}
    return dict(x=outer['x'],y=node['rect']['y']-height,width=outer['width'],height=height)

def parse_tree(tree):
    windows=[]
    def walk(node,workspace=0,minimized=False,outer=None,workarea=None):
        if node.get('type')=='workspace':workspace=node.get('num',0);minimized=node.get('name')=='__i3_scratch';workarea=node.get('rect',{})
        if node.get('type')=='floating_con':outer=node.get('rect')
        if node.get('app_id') or node.get('window'):
            appid=node.get('app_id') or (node.get('window_properties') or {}).get('class') or ''
            if not appid.startswith('orbit-shell') and node.get('pid')!=os.getpid():
                windows.append(dict(id=str(node['id']),desktop=workspace-1,pid=node.get('pid',0),klass=appid.lower(),title=node.get('name') or appid or 'Application',active=node.get('focused',False),minimized=minimized,xid=node.get('window',0),workarea=workarea or {},frame=(frame_geometry(node,outer) if not minimized else {})))
        for child in node.get('nodes',[])+node.get('floating_nodes',[]):walk(child,workspace,minimized,outer,workarea)
    walk(tree);return windows

def window_snapshot():
    """One on-demand window/workspace snapshot, shared by events and actions."""
    spaces=request(1);by_number={w['num']:w for w in spaces if w['num']>0}
    desktops=[dict(id=i-1,active=by_number.get(i,{}).get('focused',False),visible=by_number.get(i,{}).get('visible',False),output=by_number.get(i,{}).get('output',''),name=by_number.get(i,{}).get('name',f'Space {i}')) for i in sorted(set(range(1,5))|set(by_number))]
    return dict(windows=parse_tree(request(4)),desktops=desktops)

class FrameDiscovery:
    """Finite retries for decorations configured after the initial window event."""
    delays=(.2,.5,1.2,2.0)
    def __init__(self,now):self.reset(now)
    def reset(self,now):self.pending=[now+delay for delay in self.delays]
    @property
    def deadline(self):return self.pending[0] if self.pending else None
    def checked(self,now,found):
        self.pending=[] if found else [deadline for deadline in self.pending if deadline>now]

class FrameCadence:
    """Spend frame-rate IPC only during motion, never on a resting desktop.

    Sway supplies no floating-move event. First movement can therefore take up
    to the idle interval to discover; an external layer is not compositor-
    synchronized decoration even during the faster tracking burst.
    """
    idle=.1
    moving=1/60
    settle=.25
    def __init__(self):self.moving_until=0
    def interval(self,now,changed=False,enabled=True):
        if not enabled:self.moving_until=0
        elif changed:self.moving_until=now+self.settle
        return self.moving if enabled and now<self.moving_until else self.idle

class SwayEvents:
    def __init__(self,bridge):
        self.bridge=bridge;self._lastState=None;self.readfd,self.writefd=os.pipe();self.thread=threading.Thread(target=self.run,name='orbit-sway',daemon=True);self.thread.start()
    def close(self):
        os.write(self.writefd,b'x');self.thread.join(timeout=4)
        if not self.thread.is_alive():os.close(self.readfd);os.close(self.writefd)
    def snapshot(self):
        self.publish(window_snapshot())
    def publish(self,state):
        # The GUI adds icon fields to incoming windows; keep an independent cache.
        self._lastState=dict(windows=[dict(w) for w in state['windows']],desktops=[dict(d) for d in state['desktops']])
        self.bridge.desktopSnapshot.emit(state)
    def tracking_frame(self):
        return bool(self._lastState and any(w.get('active') and w.get('frame',{}).get('height',0)>0 for w in self._lastState['windows']))
    def geometry_snapshot(self,force=False):
        """Sway has no floating geometry event; query only while SSD controls exist."""
        if not self._lastState or (not force and not getattr(self.bridge,'frameTrackingEnabled',True)):return
        state=dict(windows=parse_tree(request(4)),desktops=self._lastState['desktops'])
        changed=state!=self._lastState
        # A busy browser title or badge is not window motion. Only the active
        # decoration's geometry earns the temporary higher query budget.
        def active_frame(snapshot):
            return next(((w['id'],w.get('frame')) for w in snapshot['windows'] if w.get('active') and w.get('frame')),None)
        moved=active_frame(state)!=active_frame(self._lastState)
        if changed:self.publish(state)
        return moved
    def run(self):
        sock=socket.socket(socket.AF_UNIX)
        try:
            sock.connect(os.environ['SWAYSOCK']);payload=b'["window","workspace","output","shutdown","binding"]'
            sock.sendall(HEADER.pack(MAGIC,len(payload),2)+payload);receive(sock)
            self.snapshot();self.bridge.shortcutUpdate.emit('Print · screenshot / Alt Tab · windows / Ctrl Alt Space · launch / S · system')
            deadline=None;geometry_deadline=None;discovery=FrameDiscovery(time.monotonic());cadence=FrameCadence()
            if self.tracking_frame():discovery.checked(time.monotonic(),True)
            while True:
                now=time.monotonic()
                if self.tracking_frame():
                    if geometry_deadline is None:geometry_deadline=now+.1
                else:geometry_deadline=None
                due=min((d for d in (deadline,geometry_deadline,discovery.deadline) if d is not None),default=None)
                ready=select.select([sock,self.readfd],[],[],max(0,due-now) if due is not None else None)[0]
                if self.readfd in ready:break
                if sock in ready:
                    _,event=receive(sock)
                    if event.get('change')=='exit':break
                    if 'binding' in event:
                        command=event['binding'].get('command','')
                        if command=='nop orbit-switch-next':self.bridge.completed.emit(lambda:self.bridge.cycleSwitch(1))
                        elif command.startswith('nop orbit-action-'):
                            from shortcut_config import ACTIONS
                            action=command.removeprefix('nop orbit-action-')
                            if action in ACTIONS:self.bridge.actionRequested.emit(action)
                        elif command.startswith('nop orbit-hardware-'):
                            from hardware_bindings import ACTIONS
                            action=command.removeprefix('nop orbit-hardware-')
                            if action in ACTIONS:self.bridge.hardwareKey.emit(action)
                        elif command=='nop orbit-switch-prev':self.bridge.completed.emit(lambda:self.bridge.cycleSwitch(-1))
                        elif command=='nop orbit-switch-accept':self.bridge.completed.emit(self.bridge.acceptSwitch)
                        elif command.startswith('nop orbit-panel-'):
                            page=command.removeprefix('nop orbit-panel-')
                            if page in ('launcher','ai','quick','settings','screenshot'):self.bridge.hotkey.emit(page)
                        elif command.startswith('nop orbit-workspace-'):
                            target=command.removeprefix('nop orbit-workspace-')
                            if target in ('next','previous'):self.bridge.completed.emit(lambda step=1 if target=='next' else -1:self.bridge.stepDesktop(step))
                            elif target.isdigit() and 1<=int(target)<=10:self.bridge.completed.emit(lambda i=int(target)-1:self.bridge.switchDesktop(i))
                        continue
                    if deadline is None:deadline=time.monotonic()+.08
                    if 'container' in event and event.get('change') in ('new','focus','floating','fullscreen_mode'):
                        # Decorations may not exist yet in the first "new" snapshot.
                        # Sway emits no later configure event; finite retries discover them.
                        discovery.reset(time.monotonic())
                now=time.monotonic()
                if deadline and now>=deadline:
                    self.snapshot();deadline=None;geometry_deadline=now+.1 if self.tracking_frame() else None
                    discovery.checked(time.monotonic(),self.tracking_frame())
                elif geometry_deadline and now>=geometry_deadline:
                    try:changed=self.geometry_snapshot()
                    except (OSError,ValueError,ConnectionError):
                        # A transient geometry query must not kill the event subscriber.
                        geometry_deadline=time.monotonic()+1
                    else:
                        # Schedule from completion: a slow compositor must not cause
                        # catch-up bursts of queued tree queries.
                        finished=time.monotonic()
                        interval=cadence.interval(finished,changed=bool(changed),enabled=getattr(self.bridge,'frameTrackingEnabled',True))
                        geometry_deadline=finished+interval if self.tracking_frame() else None
                        if self.tracking_frame():discovery.checked(time.monotonic(),True)
                if discovery.deadline is not None and time.monotonic()>=discovery.deadline:
                    try:self.geometry_snapshot(force=True)
                    except (OSError,ValueError,ConnectionError):pass
                    discovery.checked(time.monotonic(),self.tracking_frame())
        except (OSError,ValueError,ConnectionError) as e:self.bridge.shortcutUpdate.emit('Compositor connection: '+str(e))
        finally:sock.close()
