"""On-demand Settings renderer; existing shell controllers remain the sole owners."""
import json,os,sys,subprocess,threading
from pathlib import Path
from project_paths import PROJECT_ROOT, SOURCE_ROOT
from qt_compat import QObject,QLocalServer,QTimer,Signal,QT5
from control import socket_path
from qt5_a11y_runtime import scoped_environment
ORBIT_PROPERTIES=('appearance','compact','economy','themeMode','accentColor','accentPresets','themePresets','outputs','apps','launcherApps','isWayland','nativeCompositor','nativePaletteSupported','nativeSnapSupported','settingsSection','settingsTarget','canSwitchUser','notice','workspaceMotion','systemActions')
ORBIT_METHODS={'moveQuickControl','setPreference','resetAppearance','applyTheme','applyAppearance','rememberSettingsSection','settingsPageOpened','showPanel','openSettingsSection','launch','switchUser','activateSystemAction'}
class SettingsHost(QObject):
    processExited=Signal(object)
    def __init__(self,bridge,objects):
        super().__init__(bridge);self.bridge=bridge;self.objects=objects;self.clients={};self.process=None;self.active=False;self.closed=False;self.centered=set();self.pending=set();self.ready=False;self.errors=[];self.show_pending=False;self.show_process=None
        self.show_timeout=QTimer(self);self.show_timeout.setSingleShot(True);self.show_timeout.setInterval(5000);self.show_timeout.timeout.connect(self.show_timed_out)
        self.processExited.connect(self.process_exited)
        self.path=socket_path()+'-settings';self.server=QLocalServer(self);self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        QLocalServer.removeServer(self.path)
        if not self.server.listen(self.path):raise RuntimeError(self.server.errorString())
        self.server.newConnection.connect(self.connected)
        self.schema={}
        for name,obj in objects.items():
            meta=obj.metaObject();props={};methods={};signals=set()
            for i in range(1,meta.propertyCount()):
                prop=meta.property(i);key=prop.name()
                if name=='Orbit' and key not in ORBIT_PROPERTIES:continue
                if not prop.isReadable():continue
                props[key]=str(prop.typeName())
                if prop.hasNotifySignal():signals.add(bytes(prop.notifySignal().name()).decode())
            for i in range(meta.methodCount()):
                method=meta.method(i);key=bytes(method.name()).decode()
                if method.methodType()!=(method.Slot if QT5 else method.MethodType.Slot) or key.startswith('_') or key in ('close','deleteLater'):continue
                if name=='Orbit' and key not in ORBIT_METHODS:continue
                types=[bytes(t).decode() for t in method.parameterTypes()]
                if any(t in ('QObject*','QQuickItem*') for t in types):continue
                methods.setdefault(key,[]).append(len(types))
            self.schema[name]={'properties':props,'methods':methods,'signals':list(signals)}
            for signal in signals:
                getattr(obj,signal).connect(lambda *args,n=name:self.queue(n))
        bridge.windowsChanged.connect(self.center_new_window)
        bridge.windowsChanged.connect(self.finish_show)
    def values(self,name):
        obj=self.objects[name]
        return {key:getattr(obj,key) for key in self.schema[name]['properties']}
    def send(self,client,value):
        raw=(json.dumps(value,separators=(',',':'))+'\n').encode()
        if len(raw)>2097152 or client.bytesToWrite()>2097152:client.disconnectFromServer();return
        client.write(raw);client.flush()
    def queue(self,name):
        if self.closed or not self.clients:return
        if not self.pending:QTimer.singleShot(0,self.flush)
        self.pending.add(name)
    def flush(self):
        names=list(self.pending);self.pending.clear()
        for name in names:
            for client in list(self.clients):self.send(client,{'object':name,'values':self.values(name)})
    def connected(self):
        client=self.server.nextPendingConnection()
        if len(self.clients)>=1:client.disconnectFromServer();return
        self.clients[client]=bytearray();self.active=True
        self.centered.update(w['id'] for w in self.bridge._windows if w['klass']=='orbit-settings')
        client.readyRead.connect(lambda:self.read(client));client.disconnected.connect(lambda:self.disconnected(client))
        self.send(client,{'schema':self.schema,'values':{name:self.values(name) for name in self.objects}})
    def disconnected(self,client):
        self.clients.pop(client,None);client.deleteLater()
        self.bridge.settingsPageOpened('');self.active=False;self.ready=False
        if not self.process and self.show_process is None:self.start_show_process()
    def read(self,client):
        buffer=self.clients.get(client)
        if buffer is None:return
        buffer.extend(bytes(client.readAll()))
        if len(buffer)>65536:client.disconnectFromServer();return
        while b'\n' in buffer:
            raw,_,tail=buffer.partition(b'\n');buffer[:]=tail
            try:
                call=json.loads(raw)
                if call.get('ready') is True:
                    self.ready=True;self.errors=[str(e)[:300] for e in call.get('errors',[])[:20]];self.finish_show();continue
                if call.get('closing') is True:
                    if self.show_process is self.process and self.process is not None:
                        self.show_pending=False;self.show_timeout.stop()
                    # The bridge accepts page updates only from an active
                    # Settings window. Release page resources before closing it.
                    self.bridge.settingsPageOpened('')
                    self.active=False;self.ready=False;continue
                if 'visible' in call:
                    if type(call['visible']) is not bool:raise ValueError('Invalid visibility')
                    if not call['visible']:self.bridge.settingsPageOpened('')
                    self.active=call['visible'];continue
                name,method,args=call['object'],call['method'],call.get('args',[])
                if not isinstance(args,list) or len(args) not in self.schema[name]['methods'][method]:raise ValueError('Unsupported Settings action')
                if name=='Orbit' and method=='settingsPageOpened':self.active=True
                getattr(self.objects[name],method)(*args)
            except (ValueError,TypeError,KeyError,AttributeError,OSError,RuntimeError) as error:
                self.send(client,{'error':str(error)[:220]})
    def show(self,section):
        if self.closed:return
        self.bridge.rememberSettingsSection(section)
        if self.show_pending:return
        self.show_pending=True;self.show_process=None
        if self.finish_show():return
        self.show_timeout.start()
        self.start_show_process()
    def start_show_process(self):
        if self.closed or not self.show_pending or self.clients or (self.process and self.process.poll() is None):return
        env=dict(os.environ);env['QT_WAYLAND_SHELL_INTEGRATION']='xdg-shell';env['QT_WAYLAND_DISABLE_WINDOWDECORATION']='1'
        for key in ('ORBIT_NATIVE_CONTROL','SWAYSOCK'):env.pop(key,None)
        root=PROJECT_ROOT
        env=scoped_environment(env,root)
        self.ready=False;self.errors=[]
        try:self.process=subprocess.Popen([sys.executable,str(SOURCE_ROOT/'settings_app.py'),'--endpoint',self.path],env=env,cwd=root,start_new_session=True)
        except OSError:
            self.fail_show('Settings could not start');return
        process=self.show_process=self.process
        def wait():
            process.wait()
            try:self.processExited.emit(process)
            except RuntimeError:pass
        threading.Thread(target=wait,name='orbit-settings-reap',daemon=True).start()
    def finish_show(self):
        if self.closed or not self.show_pending or not self.clients or not self.ready:return False
        row=next((w for w in self.bridge._windows if w['klass']=='orbit-settings'),None)
        if not row:return False
        self.show_pending=False;self.show_timeout.stop()
        for client in list(self.clients):self.send(client,{'show':True})
        self.bridge.focusWindow(row['id'])
        return True
    def process_exited(self,process):
        if self.closed or self.process is not process:return
        self.process=None
        if self.show_process is process:self.fail_show('Settings could not start')
        else:self.start_show_process()
    def fail_show(self,message):
        if self.show_pending:
            self.show_pending=False;self.show_timeout.stop();self.bridge.notify(message)
    def show_timed_out(self):
        process=self.show_process
        # Only retire a child that this request launched and that never
        # completed its handshake. A previously opened Settings window may
        # contain a draft and is not safe to terminate.
        retire=self.show_pending and process is not None and self.process is process and not self.ready
        self.fail_show('Settings is taking too long to open. Try again.')
        if not retire or process.poll() is not None:return
        self.show_process=None
        for client in list(self.clients):client.disconnectFromServer()
        try:process.terminate()
        except OSError:pass

        def kill_unready():
            if self.process is process and process.poll() is None and not self.ready:
                try:process.kill()
                except OSError:pass
        QTimer.singleShot(750,kill_unready)
    def center_new_window(self):
        if not self.bridge.windowActions:return
        for row in self.bridge._windows:
            if row['klass']!='orbit-settings' or row['id'] in self.centered:continue
            rect=row.get('rect',{})
            if rect.get('width',0)<100 or rect.get('height',0)<100:continue
            self.centered.add(row['id'])
            if row.get('snap') or row['klass'] in self.bridge.preferences.values['appPlacements']:continue
            screen=row.get('workarea') or self.bridge.screenMap()
            width=min(rect['width'],max(320,screen['width']-32));height=min(rect['height'],max(240,screen['height']-48))
            target=dict(x=screen['x']+(screen['width']-width)//2,y=screen['y']+(screen['height']-height)//2,width=width,height=height)
            self.bridge.windowTask(row['id'],'settings-center',lambda ident=int(row['id']),r=target:self.bridge.windowActions._resize(ident,r))
    def close(self):
        self.closed=True;self.show_timeout.stop();self.show_pending=False
        for client in list(self.clients):client.disconnectFromServer()
        self.server.close();QLocalServer.removeServer(self.path)
