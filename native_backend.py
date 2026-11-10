"""Explicit native compositor adapter. No Sway socket, commands or idle polling."""
import os,re,socket,threading
from native_compositor import NativeCompositor
from window_actions import valid_rect

class NativeDesktopEvents:
    def __init__(self,bridge,path=None):
        self.bridge=bridge;self.client=NativeCompositor(path or os.environ['ORBIT_NATIVE_CONTROL']);self.connection=socket.socket(socket.AF_UNIX);self.closed=threading.Event()
        self.thread=threading.Thread(target=self.run,name='orbit-native-events',daemon=True);self.thread.start()
    def snapshot(self):
        state=self.client.snapshot();self.bridge.desktopSnapshot.emit(state);return state
    def run(self):
        # EOF can mean a bounded compositor subscription overflow, not shell
        # shutdown. A new subscription begins with an authoritative snapshot.
        delay=.1;reported=False
        while not self.closed.is_set():
            received=False
            try:
                for event in self.client.subscribe(self.connection):
                    if self.closed.is_set():break
                    received=True;reported=False
                    if event.get('event')=='snapshot':self.bridge.desktopSnapshot.emit(event['snapshot'])
                    elif event.get('event')=='action':
                        action=event.get('action','')
                        if action in ('launcher','screenshot','quick','notifications'):self.bridge.hotkey.emit(action)
                        elif action in ('switch-next','switch-back'):self.bridge.completed.emit(lambda delta=(-1 if action=='switch-back' else 1):self.bridge.cycleSwitch(delta))
                        elif action=='switch-accept':self.bridge.completed.emit(self.bridge.acceptSwitch)
                        elif action=='logout':self.bridge.completed.emit(self.bridge.quit)
                        elif action in ('volume-up','volume-down','volume-mute','microphone-mute','brightness-up','brightness-down','media-play-pause','media-pause','media-stop','media-next','media-previous'):self.bridge.hardwareKey.emit(action)
                        elif action in ('terminal','snap-left','snap-right','maximize','restore','next-layout','close-window','fullscreen-window') or re.fullmatch(r'move-space-[1-4]',action):self.bridge.actionRequested.emit(action)
            except (OSError,ValueError,RuntimeError) as error:
                if not self.closed.is_set() and not reported:
                    reported=True;self.bridge.completed.emit(lambda message=str(error):self.bridge.notify('Native desktop reconnecting: '+message))
            finally:self.connection.close()
            if self.closed.is_set():break
            if received:delay=.1
            if self.closed.wait(delay):break
            delay=min(delay*2,2)
            self.connection=socket.socket(socket.AF_UNIX)
        self.connection.close()
    def close(self):
        self.closed.set()
        try:self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:pass
        self.connection.close();self.thread.join(timeout=2)

class NativeWindowActions:
    def __init__(self,client=None,path=None):
        self.client=client or NativeCompositor(path or os.environ['ORBIT_NATIVE_CONTROL']);self.lock=threading.RLock();self.saved={};self.minimized={};self.snapped={};self._maximized=frozenset();self._snapshot=None;self._shortcuts={}
    def update(self,snapshot):
        self._snapshot=snapshot
        self._maximized=frozenset(int(row['id']) for row in snapshot.get('windows',[]) if row.get('maximized'))
    def snapshot(self):
        result=self.client.snapshot();self.update(result);return result
    def _row(self,ident):
        if type(ident) is not int or ident<=0:raise ValueError('Invalid native window identifier')
        row=next((row for row in self.snapshot()['windows'] if int(row['id'])==ident),None)
        if row is None:raise ValueError('Window has closed')
        return row
    def is_maximized(self,ident):return ident in self._maximized
    def window_rect(self,ident):
        row=self._row(int(ident));rect=dict(row['rect']);frame=row.get('frame',{})
        if valid_rect(frame):
            left=min(rect['x'],frame['x']);top=min(rect['y'],frame['y']);right=max(rect['x']+rect['width'],frame['x']+frame['width']);bottom=max(rect['y']+rect['height'],frame['y']+frame['height']);rect=dict(x=left,y=top,width=right-left,height=bottom-top)
        return rect
    def focus(self,ident):return self.client.request('focus',id=int(ident))
    def close(self,ident):return self.client.request('close',id=int(ident))
    def fullscreen(self,ident,desired=None):
        row=self._row(int(ident));return self.client.request('fullscreen',id=int(ident),enabled=not row.get('fullscreen') if desired is None else bool(desired))
    def minimize(self,ident):return self.client.request('minimize',id=int(ident))
    def restore(self,ident):return self.client.request('focus',id=int(ident))
    def maximize(self,ident,desired=None,prepare=None):
        with self.lock:
            row=self._row(ident);enabled=not row.get('maximized') if desired is None else bool(desired)
            if enabled:
                if prepare:prepare(True)
                self.saved.setdefault(ident,(dict(row['rect']),True))
            result=self.client.request('maximize',id=ident,restore=not enabled)
            if enabled:self._maximized=self._maximized|{ident}
            else:self.saved.pop(ident,None);self._maximized=self._maximized-{ident}
            return result
    def snap(self,ident,side):
        if side not in ('left','right','top','bottom'):raise ValueError('Invalid snap side')
        with self.lock:
            row=self._row(ident);self.snapped.setdefault(ident,(dict(row['rect']),True));return self.client.request('snap',id=ident,side=side)
    def restore_size(self,ident):
        with self.lock:
            if ident in self.saved:self.maximize(ident,False)
            saved=self.snapped.pop(ident,None)
            if saved:return self._resize(ident,saved[0])
    def constrain_workarea(self,ident):return self.client.request('constrain',id=ident)
    def reflow_maximized(self):
        for ident in self._maximized:self.client.request('maximize',id=ident)
    def _resize(self,ident,rect):
        if not valid_rect(rect):raise ValueError('Invalid native window geometry')
        return self.client.request('resize',id=ident,rect=rect)
    def _persist(self):pass # Session restore geometry is owned by the compositor.
    def prune(self,tree=None):
        alive={int(row['id']) for row in self.snapshot()['windows']}
        for table in (self.saved,self.minimized,self.snapped):
            for ident in set(table)-alive:table.pop(ident,None)
        self._maximized=self._maximized&alive
    def request(self,kind,payload=None):
        """Internal arrangement-model compatibility from a typed native snapshot."""
        snapshot=self.snapshot();outputs=snapshot.get('outputs',[]);desktops=snapshot.get('desktops',[])
        if kind==100:return self.client.request('input_get')['inputs']
        if kind==3:return outputs
        if kind==1:return [dict(num=row['id']+1,name=str(row['id']+1),focused=row['active'],visible=row['active'],rect=outputs[0]['workarea'] if outputs else {},output=outputs[0]['name'] if outputs else '') for row in desktops]
        if kind!=4:raise ValueError('Unsupported native query')
        root=dict(type='root',nodes=[],floating_nodes=[])
        for output in outputs:
            node=dict(type='output',name=output['name'],rect=output['rect'],nodes=[],floating_nodes=[]);root['nodes'].append(node)
            for desktop in desktops:
                space=dict(type='workspace',num=desktop['id']+1,name=str(desktop['id']+1),rect=output['workarea'],nodes=[],floating_nodes=[]);node['nodes'].append(space)
                for window in snapshot['windows']:
                    if window.get('minimized'):continue
                    rect=window['rect'];area=output['rect']
                    def overlap(candidate):
                        box=candidate['rect'];return max(0,min(rect['x']+rect['width'],box['x']+box['width'])-max(rect['x'],box['x']))*max(0,min(rect['y']+rect['height'],box['y']+box['height'])-max(rect['y'],box['y']))
                    assigned=max(outputs,key=overlap)['name'] if outputs else ''
                    if window['desktop']!=desktop['id'] or assigned!=output['name']:continue
                    view=dict(type='con',id=int(window['id']),app_id=window['klass'] or 'native-window',pid=window['pid'],name=window['title'],rect=rect,deco_rect=dict(height=0),focused=window['active'],fullscreen_mode=1 if window.get('fullscreen') else 0,nodes=[],floating_nodes=[])
                    space['floating_nodes'].append(dict(type='floating_con',id=int(window['id'])+2**48,rect=rect,nodes=[view],floating_nodes=[]))
        return root
    def configure_input(self,values,keys,device=''):return self.client.request('input_configure',values=values,keys=list(keys),device=device)
    def configure_output(self,settings):return self.client.request('output_configure',settings=settings)
    def output_power(self,on):return self.client.request('output_power',on=bool(on))
    def configure_shortcuts(self,bindings):
        from shortcut_config import validate
        values=validate(bindings);self.client.request('shortcuts',bindings=values);self._shortcuts=values
    def command(self,text):
        # Only the finite arrangement engine operations are accepted. This is not
        # a general compositor command language or a shell evaluation path.
        binding=re.fullmatch(r'bindsym --no-warn (?:--no-repeat )?([^ ]+) nop orbit-action-([a-z-]+)',text)
        if binding:
            from shortcut_config import DEFAULTS,ACTIONS,chord
            if binding[2] not in ACTIONS:raise ValueError('Unknown native shortcut action')
            values=dict(self._shortcuts or DEFAULTS);values[binding[2]]=chord(binding[1]);self.client.request('shortcuts',bindings=values);self._shortcuts=values;return [{'success':True}]
        unbind=re.fullmatch(r'unbindsym ([^ ]+)',text)
        if unbind:
            values={action:('' if value==unbind[1] else value) for action,value in self._shortcuts.items()};self.client.request('shortcuts',bindings=values);self._shortcuts=values;return [{'success':True}]
        operations=text.split(';')
        if len(operations)>16:raise ValueError('Too many native arrangement operations')
        for operation in operations:
            match=re.fullmatch(r'\s*\[con_id=([1-9][0-9]*)\]\s+(.+?)\s*',operation)
            if not match:raise ValueError('Unsupported native arrangement operation')
            ident=int(match[1]);action=match[2]
            if action=='focus':self.focus(ident)
            elif action in ('fullscreen enable','fullscreen disable'):self.client.request('fullscreen',id=ident,enabled=action.endswith('enable'))
            elif action in ('floating enable','floating disable'):self._row(ident) # Native scene windows always stack.
            elif re.fullmatch(r'resize set width [1-9][0-9]* px height [1-9][0-9]* px',action):
                dimensions=re.findall(r'[0-9]+',action);rect=dict(self._row(ident)['rect']);rect.update(width=int(dimensions[0]),height=int(dimensions[1]));self._resize(ident,rect)
            elif re.fullmatch(r'move absolute position -?[0-9]+ px -?[0-9]+ px',action):
                coordinates=re.findall(r'-?[0-9]+',action);rect=dict(self._row(ident)['rect']);rect.update(x=int(coordinates[0]),y=int(coordinates[1]));self._resize(ident,rect)
            elif re.fullmatch(r'move container to workspace number [1-4]',action):self.client.move(ident,int(action.rsplit(' ',1)[1]))
            else:raise ValueError('Unsupported native arrangement operation')
        return [{'success':True}]
