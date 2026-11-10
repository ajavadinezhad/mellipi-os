#!/usr/bin/env python3
"""Thin, ordinary xdg-shell Settings window. No hardware controllers or timers."""
import argparse,json,sys
from pathlib import Path
from project_paths import PROJECT_ROOT
from qt_compat import QObject,Property,Signal,Slot,QTimer,QApplication,QQmlApplicationEngine,QUrl,QIcon,QQuickWindow,QT5
if QT5:
    from PyQt5.QtNetwork import QLocalSocket
else:
    from PySide6.QtNetwork import QLocalSocket
class Connection(QObject):
    def __init__(self):
        super().__init__();self.socket=QLocalSocket(self);self.buffer=bytearray();self.proxies={};self.window=None;self.retries=0;self.endpoint="";self.reconnecting=False
    def send(self,value):self.socket.write((json.dumps(value,separators=(',',':'))+'\n').encode());self.socket.flush()
    @Slot(bool)
    def setVisible(self,visible):self.send({'visible':visible})
    def call(self,obj,method,args):self.send({'object':obj,'method':method,'args':list(args)})
    def read(self):
        self.buffer.extend(bytes(self.socket.readAll()))
        if len(self.buffer)>2097152:raise ValueError('Oversized Settings state')
        rows=[]
        while b'\n' in self.buffer:
            raw,_,tail=self.buffer.partition(b'\n');self.buffer[:]=tail;rows.append(json.loads(raw))
        return rows
    def reconnect(self):
        if self.reconnecting:return
        self.reconnecting=True;self.retries=0;QTimer.singleShot(100,self.retry)
    def retry(self):
        self.socket.abort();self.socket.connectToServer(self.endpoint)
        if self.socket.waitForConnected(150):
            self.reconnecting=False;self.buffer.clear();return
        self.retries+=1
        if self.retries>=15:QApplication.instance().quit();return
        QTimer.singleShot(min(1000,100*(self.retries+1)),self.retry)
    def update(self):
        for message in self.read():
            if 'schema' in message:
                # A shell-only reload must not reset the still-open app's page.
                section=self.proxies['Orbit'].data.get('settingsSection',10)
                message['values']['Orbit']['settingsSection']=section
                self.call('Orbit','rememberSettingsSection',[section])
                for name,values in message['values'].items():
                    proxy=self.proxies.get(name)
                    if proxy:
                        proxy.data=values
                        for signal in proxy.signal_names:getattr(proxy,signal).emit()
                if self.window:
                    visible=self.window.isVisible() and self.window.visibility()!=2
                    self.setVisible(visible)
                    page=self.window.findChild(QObject,'systemSettingsPanel')
                    if visible and page:self.call('Orbit','settingsPageOpened',[page.property('pageName')])
            elif 'object' in message:
                proxy=self.proxies[message['object']];proxy.data.update(message['values'])
                for signal in proxy.signal_names:getattr(proxy,signal).emit()
            elif message.get('show') and self.window:
                (self.window.showMaximized() if self.window.property('wasMaximized') else self.window.showNormal()) if self.window.visibility()==2 else self.window.show()
                self.window.requestActivate()
            elif 'error' in message:
                proxy=self.proxies['Orbit'];proxy.data['notice']=message['error'];proxy.settingsChanged.emit()
def proxy_type(name,schema):
    attrs={'__module__':__name__}
    signals=set(schema['signals'])|{'remoteChanged'}
    if name=='Orbit':signals|={'settingsChanged','interactionChanged'}
    for signal in signals:attrs[signal]=Signal()
    for key in schema['properties']:
        attrs[key]=Property('QVariant',lambda self,k=key:self.data.get(k),notify=attrs['remoteChanged'])
    for method,counts in schema['methods'].items():
        def make(key):
            def invoke(self,*args):
                if name=='Orbit' and key=='showPanel' and args and args[0] in ('settings','system-settings'):
                    if args[0]=='settings':self.connection.call('Orbit','rememberSettingsSection',[10])
                    return
                return self.connection.call(name,key,args)
            for count in counts:invoke=Slot(*(['QVariant']*count),name=key)(invoke)
            return invoke
        attrs[method]=make(method)
    if name=='Orbit':
        attrs['queueItemTooltip']=Slot(QObject,str,float,float,name='queueItemTooltip')(lambda *args:None)
        attrs['hideTooltip']=Slot(name='hideTooltip')(lambda *args:None)
        attrs['dismiss']=Slot(name='dismiss')(lambda self:self.connection.window.showMinimized())
    return type(name+'Remote',(QObject,),attrs),signals

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--endpoint',required=True);args=parser.parse_args()
    QQuickWindow.setDefaultAlphaBuffer(True)
    app=QApplication(sys.argv[:1]);app.setApplicationName('orbit-settings');app.setDesktopFileName('orbit-settings');app.setQuitOnLastWindowClosed(True)
    from icon_theme import configure as configure_icons
    configure_icons();app.setWindowIcon(QIcon.fromTheme('preferences-system'))
    connection=Connection();connection.endpoint=args.endpoint;connection.socket.connectToServer(args.endpoint)
    if not connection.socket.waitForConnected(4000) or not connection.socket.waitForReadyRead(4000):return 1
    messages=connection.read()
    while not messages and connection.socket.waitForReadyRead(1000):messages=connection.read()
    if len(messages)!=1 or 'schema' not in messages[0]:return 1
    initial=messages[0];engine=QQmlApplicationEngine();errors=[]
    def warnings(rows):
        errors.extend(row.toString() for row in rows)
        if connection.window:connection.send({'ready':True,'errors':errors[-20:]})
    engine.warnings.connect(warnings)
    for name,schema in initial['schema'].items():
        cls,signals=proxy_type(name,schema);proxy=cls();proxy.data=initial['values'][name];proxy.connection=connection;proxy.signal_names=signals
        connection.proxies[name]=proxy;engine.rootContext().setContextProperty(name,proxy)
    from native_app import Icons
    engine.addImageProvider('icons',Icons());engine.rootContext().setContextProperty('SettingsConnection',connection)
    engine.load(QUrl.fromLocalFile(str(PROJECT_ROOT/'native/SettingsWindow.qml')))
    if not engine.rootObjects():return 1
    connection.window=engine.rootObjects()[0]
    from shell_cursor import apply as apply_cursor
    def sync_cursor():
        data=connection.proxies['Orbit'].data
        apply_cursor([connection.window],data.get('themeMode','dark'),data.get('accentColor') if data.get('appearance',{}).get('cursorAccent',True) else None)
    connection.proxies['Orbit'].remoteChanged.connect(sync_cursor);sync_cursor()
    connection.send({'ready':True,'errors':errors})
    connection.socket.readyRead.connect(connection.update);connection.socket.disconnected.connect(connection.reconnect)
    result=app.exec();connection.socket.disconnected.disconnect(connection.reconnect);connection.socket.disconnectFromServer();return result
if __name__=='__main__':sys.exit(main())
