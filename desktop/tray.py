"""Event-driven StatusNotifier host; all application D-Bus work stays off the UI thread."""
import os,sys,threading,time
from qt_compat import QObject,Property,Signal,Slot,QQuickImageProvider,QImage,QColor,QIcon,QSize,QPainter,Qt
WATCH='org.kde.StatusNotifierWatcher'; PATH='/StatusNotifierWatcher'; ITEM='org.kde.StatusNotifierItem'
XML='''<node><interface name="org.kde.StatusNotifierWatcher">
<method name="RegisterStatusNotifierItem"><arg type="s" direction="in"/></method>
<method name="RegisterStatusNotifierHost"><arg type="s" direction="in"/></method>
<property name="RegisteredStatusNotifierItems" type="as" access="read"/>
<property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
<property name="ProtocolVersion" type="i" access="read"/>
<signal name="StatusNotifierItemRegistered"><arg type="s"/></signal>
<signal name="StatusNotifierItemUnregistered"><arg type="s"/></signal>
<signal name="StatusNotifierHostRegistered"/>
</interface></node>'''

def menu_rows(node,parents=(),depth=0):
    """Bound and flatten submenus while preserving labels, enabled and checked state."""
    rows=[]
    if depth>5:return rows
    ident,props,children=node
    for child in children[:64]:
        if hasattr(child,'unpack'):child=child.unpack()
        key,p,kids=child
        if not p.get('visible',True) or p.get('type')=='separator':continue
        label=str(p.get('label','')).replace('_','')[:120]
        if not label:continue
        if kids:rows.extend(menu_rows(child,parents+(label,),depth+1))
        else:rows.append(dict(id=int(key),label=(' › '.join(parents+(label,))),enabled=bool(p.get('enabled',True)),checked=p.get('toggle-state',0)==1))
        if len(rows)>=64:break
    return rows[:64]

class TrayImages(QQuickImageProvider):
    def __init__(self,owner):super().__init__(QQuickImageProvider.Image);self.owner=owner
    def requestImage(self,ident,*sizes):
        from qt_compat import QT5
        image=self.owner.images.get(ident.split('?')[0],QImage())
        if image.isNull():image=QImage(20,20,QImage.Format_ARGB32);image.fill(QColor('#86b9a2'))
        # Recolor symbolic/monochrome artwork only; preserve multicolor application logos.
        sample=image.scaled(24,24)
        neutral=[sample.pixelColor(x,y) for x in range(sample.width()) for y in range(sample.height()) if sample.pixelColor(x,y).alpha()>40 and max(sample.pixelColor(x,y).red(),sample.pixelColor(x,y).green(),sample.pixelColor(x,y).blue())-min(sample.pixelColor(x,y).red(),sample.pixelColor(x,y).green(),sample.pixelColor(x,y).blue())<24]
        # Keep two-tone logos intact; tint neutral symbolic strokes, preserving colored badges.
        if neutral and max(c.red() for c in neutral)-min(c.red() for c in neutral)<100:
            image=image.scaled(32,32,Qt.KeepAspectRatio,Qt.SmoothTransformation);ink=QColor('#24372f' if self.owner.bridge.themeMode=='light' else '#deeee7')
            for x in range(image.width()):
                for y in range(image.height()):
                    c=image.pixelColor(x,y)
                    if max(c.red(),c.green(),c.blue())-min(c.red(),c.green(),c.blue())<24:
                        color=QColor(ink);color.setAlpha(c.alpha());image.setPixelColor(x,y,color)
        if QT5:return image,image.size()
        sizes[0].setWidth(image.width());sizes[0].setHeight(image.height());return image

class TrayHost(QObject):
    changed=Signal();received=Signal(object);menuReady=Signal(object);notice=Signal(str)
    def __init__(self,bridge,enabled=True):
        super().__init__();self.bridge=bridge;self.rows={};self.images={};self.revision=0;self.worker=None;self.legacy=None;self.knownApps={}
        self.received.connect(self.apply);self.menuReady.connect(self.showMenu)
        if hasattr(bridge,"settingsChanged"):bridge.settingsChanged.connect(self.retheme)
        if enabled:self.worker=TrayBus(self)
    def retheme(self):
        self.revision+=1
        for key,row in self.rows.items():row['iconSource']='image://tray/'+key+'?v='+str(self.revision)
        self.changed.emit()
    legacyCount=Property(int,lambda s:len(s.legacy.icons) if s.legacy else 0,notify=changed)
    @Slot(bool)
    def showLegacy(self,shown):
        if self.legacy:self.legacy.show(shown)
    @Slot(int,int)
    def positionLegacy(self,x,y):
        if self.legacy:self.legacy.position(x,y)
    def displayItems(self):
        result=[]
        for row in self.rows.values():
            if row['status']=='Passive':continue
            row=dict(row);app=self.knownApps.get(row.get('pid',0))
            if app and (row['name'].startswith('chrome_status_icon_') or row['name']=='Background app'):row['name']=app['name']
            result.append(row)
        return result
    def setKnownApps(self,apps):
        if apps!=self.knownApps:self.knownApps=dict(apps);self.changed.emit()
    items=Property('QVariantList',lambda s:s.displayItems(),notify=changed)
    @Slot(object)
    def apply(self,data):
        key=data['key']
        if data.get('remove'):self.rows.pop(key,None);self.images.pop(key,None)
        else:
            self.revision+=1;pix=data.pop('pix',[]);image=QImage()
            valid=[p for p in pix if 0<int(p[0])<=512 and 0<int(p[1])<=512 and len(p[2])==int(p[0])*int(p[1])*4]
            if valid:
                w,h,raw=min([p for p in valid if int(p[0])>=32] or valid,key=lambda p:abs(int(p[0])-32));raw=bytes(raw)
                # SNI pixels are network-order ARGB, QImage RGBA is byte-order independent.
                rgba=bytearray(len(raw));rgba[0::4]=raw[1::4];rgba[1::4]=raw[2::4];rgba[2::4]=raw[3::4];rgba[3::4]=raw[0::4]
                image=QImage(bytes(rgba),w,h,w*4,QImage.Format_RGBA8888).copy()
            if image.isNull():
                icon=QIcon(data.get('icon','')) if data.get('icon','').startswith('/') else QIcon.fromTheme(data.get('icon',''))
                if icon.isNull():icon=QIcon.fromTheme('application-x-executable')
                image=icon.pixmap(QSize(24,24)).toImage()
            self.images[key]=image
            data['iconSource']='image://tray/'+key+'?v='+str(self.revision)
            self.rows[key]=data
        self.changed.emit()
    @Slot(str,int,int)
    def activate(self,key,x,y):
        if self.worker:self.worker.schedule(lambda:self.worker.activate(key,x,y))
    @Slot(str,int,int)
    def menu(self,key,x,y):
        if self.worker:self.worker.schedule(lambda:self.worker.menu(key,x,y))
    @Slot(str,int)
    def scroll(self,key,delta):
        if self.worker:self.worker.schedule(lambda:self.worker.action(key,'Scroll','(is)',(delta,'vertical')))
    def clickMenu(self,key,ident):
        if self.worker:self.worker.schedule(lambda:self.worker.clickMenu(key,ident))
    @Slot(object)
    def showMenu(self,data):
        self.bridge.hideTooltip();self.bridge._context=dict(x=data['x'],y=data['y'],items=[dict(label=('✓ ' if r['checked'] else '')+r['label'],enabled=r['enabled'],action='tray-menu',value=[data['key'],r['id']]) for r in data['rows']]);self.bridge.interactionChanged.emit()
    def close(self):
        if self.legacy:self.legacy.close()
        if self.worker:self.worker.close()

class TrayBus:
    def __init__(self,owner):
        self.owner=owner;self.context=None;self.loop=None;self.connection=None;self.records={};self.owned=False;self.stopping=False
        self.thread=threading.Thread(target=self.run,name='orbit-tray',daemon=True);self.thread.start()
    def schedule(self,fn):
        if not self.context or self.stopping:return
        source=self.GLib.idle_source_new()
        def call(*_):
            try:fn()
            except Exception:pass
            return False
        source.set_callback(call);source.attach(self.context)
    def call(self,bus,path,interface,method,signature,args):
        return self.connection.call_sync(bus,path,interface,method,self.GLib.Variant(signature,args),None,self.Gio.DBusCallFlags.NONE,1200,None).unpack()
    def emit(self,name,value):self.connection.emit_signal(None,PATH,WATCH,name,self.GLib.Variant('(s)',(value,)))
    def run(self):
        try:
            if '/usr/lib/python3/dist-packages' not in sys.path:sys.path.append('/usr/lib/python3/dist-packages')
            from gi.repository import Gio,GLib
            self.Gio=Gio;self.GLib=GLib;self.context=GLib.MainContext.new();self.context.push_thread_default();self.loop=GLib.MainLoop.new(self.context,False)
            self.connection=Gio.bus_get_sync(Gio.BusType.SESSION,None)
            self.connection.signal_subscribe('org.freedesktop.DBus','org.freedesktop.DBus','NameOwnerChanged',None,None,Gio.DBusSignalFlags.NONE,self.nameChanged)
            self.connection.signal_subscribe(None,ITEM,None,None,None,Gio.DBusSignalFlags.NONE,self.itemChanged)
            self.connection.signal_subscribe(None,'org.freedesktop.DBus.Properties','PropertiesChanged',None,ITEM,Gio.DBusSignalFlags.NONE,self.itemChanged)
            self.connection.signal_subscribe(WATCH,WATCH,'StatusNotifierItemRegistered',PATH,None,Gio.DBusSignalFlags.NONE,lambda *a:self.add(a[-1].unpack()[0],None))
            self.connection.signal_subscribe(WATCH,WATCH,'StatusNotifierItemUnregistered',PATH,None,Gio.DBusSignalFlags.NONE,lambda *a:self.remove(a[-1].unpack()[0]))
            self.claim()
            self.loop.run()
            if self.owned:self.call('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','ReleaseName','(s)',(WATCH,))
            self.context.pop_thread_default()
        except Exception as e:self.owner.notice.emit('System tray unavailable: '+str(e)[:120])
    def claim(self):
        result=self.call('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','RequestName','(su)',(WATCH,4))[0]
        self.owned=result in (1,4)
        if self.owned:
            if not hasattr(self,'registration'):
                info=self.Gio.DBusNodeInfo.new_for_xml(XML);self.registration=self.connection.register_object(PATH,info.interfaces[0],self.method,self.prop,None)
        else:
            try:
                self.call(WATCH,PATH,WATCH,'RegisterStatusNotifierHost','(s)',(self.connection.get_unique_name(),))
                values=self.call(WATCH,PATH,'org.freedesktop.DBus.Properties','Get','(ss)',(WATCH,'RegisteredStatusNotifierItems'))[0]
                for value in values:self.add(value,None)
            except Exception:pass
        # Discover already-running named items as well as future registrations.
        names=self.call('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','ListNames','()',())[0]
        for name in names:
            if name.startswith(('org.kde.StatusNotifierItem-','org.freedesktop.StatusNotifierItem-')):self.add(name,None)
    def prop(self,connection,sender,path,interface,name):
        value={'RegisteredStatusNotifierItems':('as',list(self.records)),'IsStatusNotifierHostRegistered':('b',True),'ProtocolVersion':('i',0)}[name]
        return self.GLib.Variant(*value)
    def method(self,connection,sender,path,interface,name,params,invocation):
        value=params.unpack()[0]
        if name=='RegisterStatusNotifierItem':
            invocation.return_value(self.GLib.Variant('()',()));self.schedule(lambda:self.add(value,sender))
        elif name=='RegisterStatusNotifierHost':invocation.return_value(self.GLib.Variant('()',()))
        else:invocation.return_dbus_error('org.freedesktop.DBus.Error.UnknownMethod','Unsupported method')
    def add(self,value,sender):
        if value.startswith('/'):
            if not sender:return
            bus,path=sender,value
        else:
            bus,sep,path=value.partition('/');path='/'+path if sep else '/StatusNotifierItem'
        key=bus+path
        if key in self.records:return
        if len(self.records)>=64:return
        try:owner=self.call('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','GetNameOwner','(s)',(bus,))[0]
        except Exception:return
        try:pid=int(self.call('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','GetConnectionUnixProcessID','(s)',(owner,))[0])
        except Exception:pid=0
        self.records[key]=dict(bus=bus,path=path,owner=owner,menu='/',pid=pid)
        if self.owned:self.emit('StatusNotifierItemRegistered',key)
        self.refresh(key)
    def refresh(self,key):
        r=self.records.get(key)
        if not r:return
        try:
            p=self.call(r['bus'],r['path'],'org.freedesktop.DBus.Properties','GetAll','(s)',(ITEM,))[0]
            r['menu']=p.get('Menu','/');r['menuOnly']=p.get('ItemIsMenu',False)
            attention=p.get('Status')=='NeedsAttention'
            self.owner.received.emit(dict(key=key,pid=r.get('pid',0),name=str(p.get('Title') or p.get('Id') or 'Background app')[:160],status=p.get('Status','Active'),icon=p.get('AttentionIconName' if attention else 'IconName',''),pix=p.get('AttentionIconPixmap' if attention else 'IconPixmap',[])))
        except Exception:self.remove(key)
    def remove(self,key):
        if key not in self.records:return
        self.records.pop(key);self.owner.received.emit(dict(key=key,remove=True))
        if self.owned:self.emit('StatusNotifierItemUnregistered',key)
    def nameChanged(self,*args):
        name,old,new=args[-1].unpack()
        if old and old!=new:
            for key,r in list(self.records.items()):
                if name in (r['bus'],r['owner']):self.remove(key)
        if name==WATCH and not new and not self.stopping:self.schedule(self.claim)
    def itemChanged(self,*args):
        connection,sender,path,interface,signal,params=args
        for key,r in list(self.records.items()):
            if sender==r['owner'] and path==r['path']:self.schedule(lambda k=key:self.refresh(k))
    def action(self,key,method,signature,args):
        r=self.records.get(key)
        if r:self.call(r['bus'],r['path'],ITEM,method,signature,args)
    def activate(self,key,x,y):
        r=self.records.get(key)
        if not r:return
        if r.get('menuOnly'):return self.menu(key,x,y)
        try:self.action(key,'Activate','(ii)',(x,y))
        except Exception:self.menu(key,x,y)
    def menu(self,key,x,y):
        r=self.records.get(key)
        if not r:return
        if r['menu']!='/':
            try:
                try:self.call(r['bus'],r['menu'],'com.canonical.dbusmenu','AboutToShow','(i)',(0,))
                except Exception:pass
                layout=self.call(r['bus'],r['menu'],'com.canonical.dbusmenu','GetLayout','(iias)',(0,6,[]))[1]
                rows=menu_rows(layout)
                if rows:self.owner.menuReady.emit(dict(key=key,x=x,y=y,rows=rows));return
            except Exception:pass
        self.action(key,'ContextMenu','(ii)',(x,y))
    def clickMenu(self,key,ident):
        r=self.records.get(key)
        if r and r['menu']!='/':self.call(r['bus'],r['menu'],'com.canonical.dbusmenu','Event','(isvu)',(ident,'clicked',self.GLib.Variant('i',0),int(time.time())&0xffffffff))
    def close(self):
        self.stopping=True
        if self.loop:self.loop.quit()
        self.thread.join(timeout=3)
