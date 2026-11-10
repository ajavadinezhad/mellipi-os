"""XEmbed tray compatibility for older X11 applications; no polling or extra process."""
from qt_compat import QSocketNotifier

class LegacyTray:
    def __init__(self,host,window):
        from Xlib import X,display,protocol
        self.X=X;self.protocol=protocol;self.host=host;self.window=window;self.icons=[];self.shown=False;self.offset=(0,0);self.notifier=None;self.d=display.Display();self.d.set_error_handler(lambda *_:1)
        self.root=self.d.screen().root;self.atom=self.d.intern_atom;self.selection=self.atom('_NET_SYSTEM_TRAY_S'+str(self.d.get_default_screen()))
        if self.d.get_selection_owner(self.selection):self.d.close();self.d=None;return
        self.owner=self.root.create_window(-1,-1,1,1,0,self.d.screen().root_depth,X.InputOutput,X.CopyFromParent,event_mask=X.StructureNotifyMask|X.PropertyChangeMask)
        self.owner.change_property(self.atom('_NET_SYSTEM_TRAY_ORIENTATION'),self.atom('CARDINAL'),32,[0])
        self.owner.change_property(self.atom('_NET_SYSTEM_TRAY_VISUAL'),self.atom('VISUALID'),32,[self.d.screen().root_visual])
        self.owner.set_selection_owner(self.selection,X.CurrentTime);self.d.sync()
        if self.d.get_selection_owner(self.selection).id!=self.owner.id:self.close();return
        self.root.send_event(protocol.event.ClientMessage(window=self.root,client_type=self.atom('MANAGER'),data=(32,[X.CurrentTime,self.selection,self.owner.id,0,0])),event_mask=X.StructureNotifyMask)
        self.d.flush();self.notifier=QSocketNotifier(self.d.fileno(),QSocketNotifier.Type.Read,host);self.notifier.activated.connect(self.events)
    def events(self,*_):
        X=self.X
        while self.d and self.d.pending_events():
            e=self.d.next_event()
            if e.type==X.ClientMessage and e.client_type==self.atom('_NET_SYSTEM_TRAY_OPCODE'):
                data=e.data[1]
                if data[1]==0 and int(data[2]) not in self.icons and len(self.icons)<32:
                    ident=int(data[2]);icon=self.d.create_resource_object('window',ident)
                    try:
                        icon.get_attributes();icon.change_attributes(event_mask=X.StructureNotifyMask,override_redirect=1);icon.change_save_set(X.SetModeInsert)
                        icon.reparent(int(self.window.winId()),0,0);self.icons.append(ident)
                        icon.send_event(self.protocol.event.ClientMessage(window=icon,client_type=self.atom('_XEMBED'),data=(32,[X.CurrentTime,0,0,int(self.window.winId()),0])))
                        if self.shown:icon.map()
                        else:icon.unmap()
                        self.layout();self.host.changed.emit()
                    except Exception:pass
            elif e.type==X.DestroyNotify and e.window.id in self.icons:
                self.icons.remove(e.window.id);self.layout();self.host.changed.emit()
            elif e.type==X.SelectionClear:self.close();self.host.changed.emit();return
        if self.d:self.d.flush()
    def show(self,shown):
        self.shown=shown
        if not self.d:return
        for ident in self.icons:
            icon=self.d.create_resource_object('window',ident)
            if shown:icon.map()
            else:icon.unmap()
        self.d.flush()
    def position(self,x,y):self.offset=(x,y);self.layout()
    def layout(self):
        if not self.d:return
        for index,ident in enumerate(self.icons):
            self.d.create_resource_object('window',ident).configure(x=self.offset[0]+(index%8)*30+6,y=self.offset[1]+(index//8)*30+6,width=18,height=18)
        self.d.flush()
    def close(self):
        if self.notifier:self.notifier.setEnabled(False)
        if not self.d:return
        for ident in self.icons:
            try:
                icon=self.d.create_resource_object('window',ident);icon.unmap();icon.reparent(self.root,0,0);icon.change_save_set(self.X.SetModeDelete)
            except Exception:pass
        self.icons=[]
        if hasattr(self,'owner'):self.owner.destroy()
        self.d.flush();self.d.close();self.d=None
