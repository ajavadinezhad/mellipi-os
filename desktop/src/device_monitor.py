"""One page-scoped GLib event loop for GIO volumes and on-demand settings work."""
import threading
from qt_compat import QObject,Signal
from system_tools_data import plain_label
class DeviceMonitor(QObject):
    result=Signal(object)
    def __init__(self,parent=None):
        super().__init__(parent);self.thread=None;self.loop=None;self.GLib=None;self.Gio=None;self.pending=[];self.lock=threading.RLock();self.generation=0;self.objects={};self.desired=False;self.runningGeneration=0;self.operations=0
    def start(self):
        self.desired=True
        if self.thread and self.thread.is_alive():return
        self.generation+=1;generation=self.generation;self.runningGeneration=generation
        self.thread=threading.Thread(target=self.run,args=(generation,),name='abstract-system-tools',daemon=True);self.thread.start()
    def stop(self):
        self.desired=False
        if not self.operations:self.generation+=1
        with self.lock:
            self.pending=[]
            if self.loop and not self.operations:self.loop.quit()
    def submit(self,callback):
        self.start()
        with self.lock:
            if self.loop and self.GLib and self.runningGeneration==self.generation:self.GLib.idle_add(self.perform,callback,self.generation)
            else:self.pending.append(callback)
    def perform(self,callback,generation):
        if generation!=self.generation:return False
        try:callback(self.Gio)
        except Exception as error:self.result.emit(dict(error=str(error)[:240]))
        return False
    def run(self,generation):
        handlers=[];monitor=None
        try:
            import gi;gi.require_version('Gio','2.0');from gi.repository import Gio,GLib
            self.Gio=Gio;self.GLib=GLib
            loop=GLib.MainLoop.new(None,False)
            monitor=Gio.VolumeMonitor.get()
            def refresh(*_):
                if generation!=self.generation or not self.desired:return
                rows=[];objects={};seen=set()
                for volume in monitor.get_volumes()[:64]:
                    mount=volume.get_mount();root=mount.get_root().get_uri() if mount else ''
                    ident=volume.get_uuid() or volume.get_identifier('unix-device') or volume.get_name()
                    ident='volume:'+str(ident);objects[ident]=(volume,mount)
                    if mount:seen.add(root)
                    rows.append(dict(id=ident,name=plain_label(volume.get_name()),mounted=bool(mount),uri=root,canMount=volume.can_mount(),canUnmount=bool(mount and mount.can_unmount()),canEject=volume.can_eject() or bool(mount and mount.can_eject())))
                for mount in monitor.get_mounts()[:64]:
                    uri=mount.get_root().get_uri()
                    if uri in seen or mount.is_shadowed():continue
                    ident='mount:'+uri;objects[ident]=(None,mount)
                    rows.append(dict(id=ident,name=plain_label(mount.get_name()),mounted=True,uri=uri,canMount=False,canUnmount=mount.can_unmount(),canEject=mount.can_eject()))
                self.objects=objects;self.result.emit(dict(devices=rows))
            for signal in ('volume-added','volume-removed','volume-changed','mount-added','mount-removed','mount-changed','drive-connected','drive-disconnected','drive-changed'):handlers.append(monitor.connect(signal,refresh))
            self.refresh=refresh
            with self.lock:
                if generation!=self.generation:return
                self.loop=loop;pending=self.pending;self.pending=[]
            refresh();self.result.emit(dict(monitorAvailable=True))
            for callback in pending:GLib.idle_add(self.perform,callback,generation)
            loop.run()
        except Exception as error:
            self.result.emit(dict(monitorAvailable=False,error='System integration unavailable: '+str(error)[:180]))
        finally:
            if monitor:
                for ident in handlers:monitor.disconnect(ident)
            with self.lock:self.loop=None;self.objects={};self.thread=None
            if self.desired and generation!=self.generation:self.start()
    def action(self,ident,action):
        def work(Gio):
            pair=self.objects.get(ident)
            if not pair:raise ValueError('This device is no longer connected')
            volume,mount=pair
            def finished(obj,result):
                self.operations=max(0,self.operations-1)
                try:
                    if action=='mount':obj.mount_finish(result)
                    elif action=='eject':obj.eject_with_operation_finish(result)
                    else:obj.unmount_with_operation_finish(result)
                    self.result.emit(dict(operationDone=True));self.refresh()
                except Exception as error:self.result.emit(dict(operationDone=True,error='Device operation failed: '+str(error)[:170]+'. Open Files if a password is required.'))
                finally:
                    if not self.desired and self.loop:self.loop.quit()
            supported=(action=='mount' and volume and volume.can_mount()) or (action=='eject' and ((mount and mount.can_eject()) or (volume and volume.can_eject()))) or (action=='unmount' and mount and mount.can_unmount())
            if not supported:raise ValueError('This device does not support that operation')
            self.operations+=1
            try:
                if action=='mount':volume.mount(Gio.MountMountFlags.NONE,None,None,finished)
                elif action=='eject' and mount and mount.can_eject():mount.eject_with_operation(Gio.MountUnmountFlags.NONE,None,None,finished)
                elif action=='eject':volume.eject_with_operation(Gio.MountUnmountFlags.NONE,None,None,finished)
                else:mount.unmount_with_operation(Gio.MountUnmountFlags.NONE,None,None,finished)
            except Exception:
                self.operations=max(0,self.operations-1)
                if not self.desired and self.loop:self.loop.quit()
                raise
        self.submit(work)
