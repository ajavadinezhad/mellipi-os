"""Blocking X11 event subscription: shortcuts and window updates, with no idle polling."""
import os, select, threading, time
import desktop

class DesktopEvents:
    def __init__(self,bridge,shortcuts=True):
        self.bridge=bridge; self.shortcuts=shortcuts; self.readfd,self.writefd=os.pipe()
        self.thread=threading.Thread(target=self.run,name='orbit-x11',daemon=True); self.thread.start()
    def close(self):
        try: os.write(self.writefd,b'x')
        except OSError: pass
        self.thread.join(timeout=3)
        if not self.thread.is_alive():
            os.close(self.readfd); os.close(self.writefd)
    def run(self):
        try:
            from Xlib import X, XK, display, error
            d=display.Display(); root=d.screen().root; atom=d.intern_atom
            d.set_error_handler(lambda e,r:1) # Windows may vanish between the event and property read.
            root.change_attributes(event_mask=X.PropertyChangeMask)
            keys={'space':'launcher','q':'quit'}
            codes={d.keysym_to_keycode(XK.string_to_keysym(k)):v for k,v in keys.items()} if self.shortcuts else {}
            conflicts=[]
            def on_error(err,req): conflicts.append(str(err)); return 1
            printcode=d.keysym_to_keycode(XK.string_to_keysym('Print'))
            tab=d.keysym_to_keycode(XK.string_to_keysym('Tab'));altcodes={d.keysym_to_keycode(XK.string_to_keysym(k)) for k in ('Alt_L','Alt_R')}
            special={d.keysym_to_keycode(XK.string_to_keysym(k)):k for k in ('Escape','Return','Left','Right','Up','Down')}
            for code in codes:
                for lock in (0,X.LockMask,X.Mod2Mask,X.LockMask|X.Mod2Mask):
                    root.grab_key(code,X.ControlMask|X.Mod1Mask|lock,False,X.GrabModeAsync,X.GrabModeAsync,onerror=lambda e,r,c=code:(conflicts.append('key '+str(c)),1)[1])
            if self.shortcuts:
                for lock in ((0,X.LockMask,X.Mod2Mask,X.LockMask|X.Mod2Mask) if printcode else ()):root.grab_key(printcode,lock,False,X.GrabModeAsync,X.GrabModeAsync,onerror=lambda e,r:(conflicts.append('Print'),1)[1])
                for shift in (0,X.ShiftMask):
                    for lock in (0,X.LockMask,X.Mod2Mask,X.LockMask|X.Mod2Mask):root.grab_key(tab,X.Mod1Mask|shift|lock,False,X.GrabModeAsync,X.GrabModeAsync,onerror=lambda e,r:(conflicts.append('Alt Tab'),1)[1])
            d.sync()
            status='Shortcut conflicts: '+', '.join(sorted(set(conflicts))) if conflicts else 'Print · screenshot / Alt Tab · windows / Ctrl Alt Space · launch / Q · quit'
            self.bridge.shortcutUpdate.emit(status)
            watched=set(); root_atoms={atom(n) for n in ('_NET_CLIENT_LIST','_NET_CLIENT_LIST_STACKING','_NET_CURRENT_DESKTOP','_NET_NUMBER_OF_DESKTOPS','_NET_ACTIVE_WINDOW')}
            client_atoms={atom(n) for n in ('_NET_WM_NAME','WM_NAME','_NET_WM_DESKTOP','WM_CLASS')}
            def snapshot():
                ids=root.get_full_property(atom('_NET_CLIENT_LIST'),X.AnyPropertyType)
                ids=set(int(i) for i in ids.value) if ids else set()
                stacking=root.get_full_property(atom('_NET_CLIENT_LIST_STACKING'),X.AnyPropertyType)
                if stacking:ids.update(int(i) for i in stacking.value)
                for ident in ids-watched:
                    try: d.create_resource_object('window',ident).change_attributes(event_mask=X.PropertyChangeMask)
                    except error.XError: pass
                watched.clear(); watched.update(ids)
                self.bridge.desktopSnapshot.emit(desktop.x11_state(d)); d.flush()
            snapshot(); deadline=None
            while True:
                if not d.pending_events():
                    ready=select.select([d.fileno(),self.readfd],[],[],max(0,deadline-time.monotonic()) if deadline is not None else None)[0]
                    if self.readfd in ready: break
                while d.pending_events():
                    event=d.next_event()
                    if event.type==X.KeyPress and event.detail==printcode and self.shortcuts:
                        self.bridge.hotkey.emit('screenshot');continue
                    if event.type==X.KeyRelease and event.detail in altcodes and self.bridge._switchActive:self.bridge.completed.emit(self.bridge.acceptSwitch)
                    if event.type==X.KeyPress and event.detail==tab and event.state & X.Mod1Mask:
                        delta=-1 if event.state & X.ShiftMask else 1
                        self.bridge.completed.emit(lambda value=delta:self.bridge.cycleSwitch(value))
                        continue
                    if event.type==X.KeyPress and self.bridge._switchActive and event.detail in special:
                        key=special[event.detail]
                        if key=='Escape':self.bridge.completed.emit(self.bridge.cancelSwitch)
                        elif key=='Return':self.bridge.completed.emit(self.bridge.acceptSwitch)
                        else:self.bridge.completed.emit(lambda value=(-1 if key in ('Left','Up') else 1):self.bridge.cycleSwitch(value))
                        continue
                    if event.type==X.KeyPress and event.detail in codes:
                        if codes[event.detail]=='quit': self.bridge.completed.emit(self.bridge.quit)
                        else: self.bridge.hotkey.emit(codes[event.detail])
                    if event.type==X.PropertyNotify:
                        if event.atom in (root_atoms if event.window.id==root.id else client_atoms):
                            # One trailing snapshot per batch, bounded even during a busy title stream.
                            if deadline is None: deadline=time.monotonic()+.12
                if deadline is not None and time.monotonic()>=deadline: snapshot(); deadline=None
            for code in list(codes)+([tab,printcode] if self.shortcuts else []): root.ungrab_key(code,X.AnyModifier)
            d.close()
        except Exception as e:
            self.bridge.shortcutUpdate.emit('X11 event connection unavailable · '+str(e))
