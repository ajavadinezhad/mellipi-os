"""Small event-driven MPRIS controller; never launches players or polls metadata."""
import sys,threading
from qt_compat import QObject,Property,Signal,Slot
PREFIX='org.mpris.MediaPlayer2.'
PATH='/org/mpris/MediaPlayer2'
PLAYER='org.mpris.MediaPlayer2.Player'
EMPTY=dict(available=False,title='',artist='',playing=False,canPlay=False,canPause=False,canNext=False,canPrevious=False,canControl=False)

def plain_text(value,limit=256):
    if not isinstance(value,str):return ''
    return ' '.join(''.join(c if ord(c)>=32 else ' ' for c in value).split())[:limit]

def player_state(properties):
    """Bound untrusted metadata and preserve the player's real capability flags."""
    metadata=properties.get('Metadata',{})
    if not isinstance(metadata,dict):metadata={}
    artists=metadata.get('xesam:artist',[])
    if not isinstance(artists,(tuple,list)):artists=[]
    artist=', '.join(filter(None,(plain_text(a,100) for a in artists[:8])))[:256]
    control=properties.get('CanControl') is True
    return dict(available=True,canControl=control,title=plain_text(metadata.get('xesam:title','')),artist=artist,
                playing=properties.get('PlaybackStatus')=='Playing',
                canPlay=control and properties.get('CanPlay') is True,
                canPause=control and properties.get('CanPause') is True,
                canNext=control and properties.get('CanGoNext') is True,
                canPrevious=control and properties.get('CanGoPrevious') is True)

def choose_player(players,current=''):
    """Prefer playback, then retain selection to avoid jumps between paused apps."""
    if current in players and players[current]['playing']:return current
    playing=next((name for name,state in players.items() if state['playing']),None)
    return playing or (current if current in players else next(iter(players),''))

def action_method(state,action):
    if not state.get('available'):return None
    if action=='playPause':return 'PlayPause' if state.get('canPause' if state.get('playing') else 'canPlay') else None
    if action=='next':return 'Next' if state.get('canNext') else None
    if action=='previous':return 'Previous' if state.get('canPrevious') else None
    if action=='stop':return 'Stop' if state.get('canControl') else None
    return None

class MediaControls(QObject):
    changed=Signal();received=Signal(object)
    def __init__(self,enabled=True,parent=None):
        super().__init__(parent);self._state=EMPTY.copy();self.received.connect(self.apply)
        self.worker=MediaBus(self) if enabled else None
    state=Property('QVariantMap',lambda self:dict(self._state),notify=changed)
    @Slot(object)
    def apply(self,state):
        if state!=self._state:self._state=dict(state);self.changed.emit()
    def request(self,action):
        if self.worker and action_method(self._state,action):self.worker.schedule(lambda:self.worker.action(action))
    @Slot()
    def playPause(self):self.request('playPause')
    @Slot()
    def next(self):self.request('next')
    @Slot()
    def previous(self):self.request('previous')
    @Slot()
    def stop(self):self.request('stop')
    def close(self):
        if self.worker:self.worker.close();self.worker=None

class MediaBus:
    def __init__(self,owner):
        self.owner=owner;self.context=None;self.loop=None;self.connection=None;self.stopping=False
        self.records={};self.selected='';self.subscriptions=[]
        self.thread=threading.Thread(target=self.run,name='orbit-media',daemon=True);self.thread.start()
    def schedule(self,work):
        if not self.context or self.stopping:return
        source=self.GLib.idle_source_new()
        def invoke(*_):
            if self.stopping:return False
            try:work()
            except Exception:pass
            return False
        source.set_callback(invoke);source.attach(self.context)
    def call(self,name,path,interface,method,signature,args):
        return self.connection.call_sync(name,path,interface,method,self.GLib.Variant(signature,args),None,self.Gio.DBusCallFlags.NO_AUTO_START,1200,None).unpack()
    def run(self):
        try:
            if '/usr/lib/python3/dist-packages' not in sys.path:sys.path.append('/usr/lib/python3/dist-packages')
            from gi.repository import Gio,GLib
            self.Gio=Gio;self.GLib=GLib;self.context=GLib.MainContext.new();self.context.push_thread_default()
            self.loop=GLib.MainLoop.new(self.context,False);self.connection=Gio.bus_get_sync(Gio.BusType.SESSION,None)
            self.subscriptions.append(self.connection.signal_subscribe('org.freedesktop.DBus','org.freedesktop.DBus','NameOwnerChanged',None,None,Gio.DBusSignalFlags.NONE,self.name_changed))
            self.subscriptions.append(self.connection.signal_subscribe(None,'org.freedesktop.DBus.Properties','PropertiesChanged',PATH,PLAYER,Gio.DBusSignalFlags.NONE,self.properties_changed))
            names=self.call('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','ListNames','()',())[0]
            for name in names:
                if name.startswith(PREFIX):self.add(name)
            if not self.stopping:self.loop.run()
        except Exception:pass
        finally:
            if self.connection:
                for ident in self.subscriptions:self.connection.signal_unsubscribe(ident)
            if self.context:self.context.pop_thread_default()
    def publish(self):
        states={name:record['state'] for name,record in self.records.items() if record.get('state')}
        self.selected=choose_player(states,self.selected)
        self.owner.received.emit(states.get(self.selected,EMPTY).copy())
    def add(self,name,owner=None):
        if not name.startswith(PREFIX) or len(name)>255:return
        if name not in self.records and len(self.records)>=16:return
        try:
            owner=owner or self.call('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','GetNameOwner','(s)',(name,))[0]
        except Exception:return
        self.records[name]=dict(owner=owner,state=None);self.refresh(name)
    def refresh(self,name):
        record=self.records.get(name)
        if not record:return
        try:
            props=self.call(record['owner'],PATH,'org.freedesktop.DBus.Properties','GetAll','(s)',(PLAYER,))[0]
            record['state']=player_state(props)
        except Exception:record['state']=None
        self.publish()
    def name_changed(self,*args):
        name,old,new=args[-1].unpack()
        if not name.startswith(PREFIX):return
        if old:self.records.pop(name,None);self.publish()
        if new:self.add(name,new)
    def properties_changed(self,*args):
        sender=args[1]
        for name,record in list(self.records.items()):
            if record['owner']==sender:self.schedule(lambda name=name:self.refresh(name))
    def action(self,action):
        record=self.records.get(self.selected)
        if not record:return
        method=action_method(record.get('state') or EMPTY,action)
        if method:
            try:self.call(record['owner'],PATH,PLAYER,method,'()',())
            except Exception:self.refresh(self.selected)
    def close(self):
        self.stopping=True
        if self.loop:self.loop.quit()
        self.thread.join(timeout=3)
