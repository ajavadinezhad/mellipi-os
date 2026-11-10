#!/usr/bin/env python3
"""Finite real ScreenCast portal/PipeWire video test in owned private daemons.

No browser is automated. The test uses the public portal API, a PipeWire remote
FD and GStreamer video frames. No host compositor/bus/PipeWire is addressed, no
WirePlumber or physical audio/video-device manager is started.
"""
import hashlib,json,os,signal,subprocess,sys,tempfile,time,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def wait(check,seconds=20):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        value=check()
        if value:return value
        time.sleep(.03)
    raise AssertionError('Private ScreenCast QA timed out')

def stop(process):
    if process and process.poll() is None:
        try:os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError:return
        try:process.wait(timeout=4)
        except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=3)

def inside(base,browser_check=None):
    import gi
    gi.require_version('Gio','2.0');gi.require_version('Gst','1.0')
    from gi.repository import Gio,GLib,Gst
    Gst.init(None)
    runtime=base/'runtime';config=base/'config';data=base/'data'
    for directory in (runtime,config,data):directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    assert os.environ['XDG_RUNTIME_DIR']==str(runtime)
    bus=Gio.bus_get_sync(Gio.BusType.SESSION,None)
    assert bus.get_unique_name() and os.environ.get('ABSTRACT_PRIVATE_PORTAL_QA')=='1'
    env=dict(os.environ);processes=[];pipeline=None;remote_fd=None
    portal_binary=os.environ.get('ORBIT_QA_PORTAL_BINARY',str(ROOT/'.portal-runtime/xdg-desktop-portal-wlr'))
    assert Path(portal_binary).is_file(),'Build the project-local portal runtime first'
    log=open('/tmp/abstract-screencast-daemons.log','w')
    def launch(args,environment=None):
        p=subprocess.Popen(args,cwd=ROOT,env=environment or env,stdout=log,stderr=log,start_new_session=True);processes.append(p);return p
    def pump():
        context=GLib.MainContext.default()
        while context.pending():context.iteration(False)
    def wait_glib(check,seconds=20):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            pump();value=check()
            if value:return value
            time.sleep(.01)
        raise AssertionError('Private portal response timed out')
    try:
        parent_config=base/'sway.conf';parent_config.write_text('output HEADLESS-1 mode 1024x768\nseat seat0 fallback true\nfocus_follows_mouse no\nfor_window [app_id="orbit-native"] floating enable, border pixel 0, resize set width 860 px height 640 px, move absolute position 80 px 40 px\n')
        parent=launch(['bash','-c','source tools/wayland-env.sh; exec sway -c "$1"','abstract-portal-qa',str(parent_config)])
        parent_socket=wait(lambda:next((p for p in runtime.glob('wayland-*') if not p.name.endswith('.lock')),None))
        child=dict(env,WAYLAND_DISPLAY=parent_socket.name,WINIT_UNIX_BACKEND='wayland',ORBIT_NESTED='1',ORBIT_NATIVE_QA_TRANSFORM='normal')
        native_log=base/'native.log'
        with native_log.open('w') as stream:
            native=subprocess.Popen([os.environ.get('ORBIT_NATIVE_QA_BINARY',str(ROOT/'.native-runtime/bin/orbit-compositor'))],cwd=ROOT,env=child,stdout=stream,stderr=stream,start_new_session=True);processes.append(native)
        def ready():
            assert native.poll() is None,native_log.read_text()
            for line in native_log.read_text().splitlines():
                try:
                    row=json.loads(line)
                    if row.get('ready'):return row
                except ValueError:pass
        info=wait(ready)
        # Keep the nested EGL target at a stable size before video/capture.
        # Parent tiling must not race initial EGL surface creation.
        parent_ipc=wait(lambda:next(runtime.glob('sway-ipc*.sock'),None))
        os.environ['SWAYSOCK']=str(parent_ipc)
        from sway_events import request as sway_request,command as sway_command
        def native_view():
            def visit(node):
                if node.get('app_id')=='orbit-native':return node
                for child_node in node.get('nodes',[])+node.get('floating_nodes',[]):
                    found=visit(child_node)
                    if found:return found
            return visit(sway_request(4))
        view=wait(native_view);ident=int(view['id'])
        sway_command(f'[con_id={ident}] floating enable; [con_id={ident}] border pixel 0; [con_id={ident}] resize set width 860 px height 640 px; [con_id={ident}] move absolute position 80 px 40 px')
        time.sleep(.5)
        from native_compositor import NativeCompositor
        print('PRIVATE_SETUP',dict(view=native_view()['rect'],outputs=NativeCompositor(info['control']).snapshot()['outputs'],runtime=str(runtime),wayland_sockets=[p.name for p in runtime.glob('wayland-*')]),flush=True)
        display=info['wayland_display']
        if isinstance(display,dict):display=bytes(display['Unix']).decode()
        env.update(WAYLAND_DISPLAY=display,XDG_CURRENT_DESKTOP='Orbit',XDG_SESSION_DESKTOP='orbit-native',XDG_SESSION_TYPE='wayland')
        os.environ.update({key:env[key] for key in ('WAYLAND_DISPLAY','XDG_CURRENT_DESKTOP','XDG_SESSION_DESKTOP','XDG_SESSION_TYPE')})
        # D-Bus activations inherit only this owned test output/runtime.
        activation={key:env[key] for key in ('WAYLAND_DISPLAY','XDG_CURRENT_DESKTOP','XDG_SESSION_DESKTOP','XDG_SESSION_TYPE','XDG_CONFIG_HOME','XDG_CONFIG_DIRS','XDG_DATA_HOME','XDG_RUNTIME_DIR','PIPEWIRE_RUNTIME_DIR')}
        bus.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','UpdateActivationEnvironment',GLib.Variant('(a{ss})',(activation,)),None,Gio.DBusCallFlags.NONE,3000,None)
        portal_config=config/'xdg-desktop-portal-wlr';portal_config.mkdir();(portal_config/'config').write_text('[screencast]\nchooser_type=none\noutput_name=orbit-nested\nmax_fps=15\n')
        chooser=config/'xdg-desktop-portal';chooser.mkdir();(chooser/'orbit-portals.conf').write_text('[preferred]\ndefault=gtk\norg.freedesktop.impl.portal.ScreenCast=wlr\n')
        launch(['/usr/bin/pipewire'])
        wait(lambda:(runtime/'pipewire-0').exists())
        wlr=launch([portal_binary,'-l','TRACE','-c',str(portal_config/'config')])
        launch(['/usr/libexec/xdg-desktop-portal','-v'])
        def has_portal():
            try:return bus.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','NameHasOwner',GLib.Variant('(s)',('org.freedesktop.portal.Desktop',)),None,Gio.DBusCallFlags.NONE,1000,None).unpack()[0]
            except GLib.Error:return False
        wait_glib(has_portal)
        fixture='''from PyQt5.QtWidgets import QApplication,QWidget
from PyQt5.QtCore import QTimer
app=QApplication([]);w=QWidget();w.setWindowTitle("Abstract private video fixture");w.resize(360,240);state=[False]
def color():
 state[0]=not state[0];w.setStyleSheet("background:"+("#ff5500" if state[0] else "#0055ff"))
color();w.show();timer=QTimer();timer.timeout.connect(color);timer.start(170);app.exec()
'''
        fixture_env=dict(env,QT_QPA_PLATFORM='wayland',QT_WAYLAND_SHELL_INTEGRATION='xdg-shell')
        launch(['/usr/bin/python3','-c',fixture],fixture_env)
        time.sleep(.4)
        responses={}
        def response(connection,sender,path,interface,signal,params,*_):responses[path]=params.unpack()
        subscription=bus.signal_subscribe('org.freedesktop.portal.Desktop','org.freedesktop.portal.Request','Response',None,None,Gio.DBusSignalFlags.NONE,response,None)
        subprocess.run(['grim','-o','orbit-nested',str(base/'pre-stream.png')],env=dict(env,WAYLAND_DEBUG='client'),check=True,timeout=5,stdout=log,stderr=log)
        if browser_check is not None:
            return browser_check(base,env,launch,log)
        serial=[0]
        def request(method,signature,args,expected=0):
            path=bus.call_sync('org.freedesktop.portal.Desktop','/org/freedesktop/portal/desktop','org.freedesktop.portal.ScreenCast',method,GLib.Variant(signature,args),None,Gio.DBusCallFlags.NONE,10000,None).unpack()[0]
            result=wait_glib(lambda:responses.pop(path,None),25)
            assert result[0]==expected,(method,result)
            return result[1]
        options=dict(handle_token=GLib.Variant('s','create1'),session_handle_token=GLib.Variant('s','session1'))
        session=request('CreateSession','(a{sv})',(options,))['session_handle']
        request('SelectSources','(oa{sv})',(session,dict(handle_token=GLib.Variant('s','sources1'),types=GLib.Variant('u',1),multiple=GLib.Variant('b',False),cursor_mode=GLib.Variant('u',1))))
        result=request('Start','(osa{sv})',(session,'',dict(handle_token=GLib.Variant('s','start1'))))
        streams=result.get('streams');assert streams, result
        node=int(streams[0][0]);print('PASS ScreenCast CreateSession/SelectSources/Start returned private stream '+str(node),flush=True)
        reply,fds=bus.call_with_unix_fd_list_sync('org.freedesktop.portal.Desktop','/org/freedesktop/portal/desktop','org.freedesktop.portal.ScreenCast','OpenPipeWireRemote',GLib.Variant('(oa{sv})',(session,{})),None,Gio.DBusCallFlags.NONE,10000,None,None)
        remote_fd=fds.get(reply.unpack()[0])
        pipeline=Gst.parse_launch('pipewiresrc name=capture autoconnect=false do-timestamp=true client-name=abstract-capture-qa ! videoconvert ! video/x-raw,format=RGB ! appsink name=sink max-buffers=2 drop=true sync=false')
        source=pipeline.get_by_name('capture');source.set_property('fd',remote_fd);source.set_property('path',str(node));source.set_property('stream-properties',Gst.Structure.from_string('props,node.name=abstract-capture-qa,media.class=Stream/Input/Video')[0])
        # pipewiresrc may synchronously await format negotiation while entering
        # PLAYING. With no session manager, link the private ports concurrently.
        start_result=[]
        starter=threading.Thread(target=lambda:start_result.append(pipeline.set_state(Gst.State.PLAYING)),daemon=True)
        starter.start()
        def dump():
            result=subprocess.run(['/usr/bin/pw-dump'],env=env,text=True,capture_output=True,timeout=3,check=True)
            return json.loads(result.stdout)
        def ports():
            rows=dump();nodes={r['id']:r.get('info',{}).get('props',{}) for r in rows if r.get('type')=='PipeWire:Interface:Node'}
            consumer=next((i for i,p in nodes.items() if p.get('node.name')=='abstract-capture-qa'),None)
            out=[r['id'] for r in rows if r.get('type')=='PipeWire:Interface:Port' and r.get('info',{}).get('props',{}).get('node.id')==node and r.get('info',{}).get('props',{}).get('port.direction')=='out']
            inside=[r['id'] for r in rows if r.get('type')=='PipeWire:Interface:Port' and r.get('info',{}).get('props',{}).get('node.id')==consumer and r.get('info',{}).get('props',{}).get('port.direction')=='in']
            return (out[0],inside[0]) if out and inside else None
        outport,inport=wait_glib(ports,15)
        subprocess.run(['/usr/bin/pw-link',str(outport),str(inport)],env=env,check=True,timeout=5,stdout=log,stderr=log)
        starter.join(timeout=5);assert not starter.is_alive(),'GStreamer did not enter PLAYING after private link'
        assert start_result[0]!=Gst.StateChangeReturn.FAILURE,start_result
        sink=pipeline.get_by_name('sink');hashes=set();caps=[];sizes=[]
        for _ in range(8):
            sample=sink.emit('try-pull-sample',3*Gst.SECOND)
            if sample is None:
                message=pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR)
                raise AssertionError('No video frame: '+str(message.parse_error() if message else 'timeout'))
            buffer=sample.get_buffer();ok,mapping=buffer.map(Gst.MapFlags.READ);assert ok
            raw=bytes(mapping.data);hashes.add(hashlib.sha256(raw).hexdigest());sizes.append(len(raw));caps.append(sample.get_caps().to_string());buffer.unmap(mapping)
            time.sleep(.06)
        assert len(hashes)>1,'Video fixture colors did not change in captured frames'
        assert min(sizes)>10000,(caps,sizes)
        print('PASS actual PipeWire remote FD delivered changing RGB video frames to GStreamer',flush=True)
        bus.call_sync('org.freedesktop.portal.Desktop',session,'org.freedesktop.portal.Session','Close',None,None,Gio.DBusCallFlags.NONE,5000,None)
        wait_glib(lambda:all(not (row.get('id')==node and row.get('type')=='PipeWire:Interface:Node') for row in dump()),10)
        pipeline.set_state(Gst.State.NULL);pipeline=None
        print('PASS closing portal session removed the video source',flush=True)
        # A private rejecting chooser exercises cancellation without opening a
        # host permission dialog or granting a second stream.
        (portal_config/'config').write_text('[screencast]\nchooser_type=simple\nchooser_cmd=/bin/false\noutput_name=orbit-nested\nmax_fps=15\n')
        stop(wlr)
        wlr=launch([portal_binary,'-r','-l','DEBUG','-c',str(portal_config/'config')])
        time.sleep(.35)
        second=request('CreateSession','(a{sv})',(dict(handle_token=GLib.Variant('s','create2'),session_handle_token=GLib.Variant('s','session2')),))['session_handle']
        request('SelectSources','(oa{sv})',(second,dict(handle_token=GLib.Variant('s','sources2'),types=GLib.Variant('u',1),multiple=GLib.Variant('b',False),cursor_mode=GLib.Variant('u',1))),expected=1)
        assert all(not (row.get('id')==node and row.get('type')=='PipeWire:Interface:Node') for row in dump()),'Cancelled request recreated the original source'
        print('PASS declining source selection returns portal cancellation',flush=True)
        bus.signal_unsubscribe(subscription)
        print(json.dumps(dict(private_bus=True,private_pipewire=True,no_device_manager=True,browser_tested=False,frames=len(sizes),distinct_frames=len(hashes),caps=caps[0],bytes=sizes[0],node=node)))
    finally:
        if pipeline:pipeline.set_state(Gst.State.NULL)
        if remote_fd is not None:os.close(remote_fd)
        for process in reversed(processes):stop(process)
        if native_log.exists():Path('/tmp/abstract-screencast-native.log').write_text(native_log.read_text())
        log.close()

def main():
    if len(sys.argv)==3 and sys.argv[1]=='--inside-private-bus':return inside(Path(sys.argv[2]))
    with tempfile.TemporaryDirectory(prefix='abstract-screencast-',ignore_cleanup_errors=True) as temp:
        base=Path(temp);runtime=base/'runtime';runtime.mkdir(mode=0o700)
        env={key:value for key,value in os.environ.items() if key not in ('WAYLAND_DISPLAY','SWAYSOCK','DISPLAY','ORBIT_NATIVE_CONTROL','DBUS_SESSION_BUS_ADDRESS','PIPEWIRE_REMOTE','PIPEWIRE_RUNTIME_DIR','PULSE_SERVER','XDG_DESKTOP_PORTAL_DIR')}
        env.update(ABSTRACT_PRIVATE_PORTAL_QA='1',XDG_RUNTIME_DIR=str(runtime),PIPEWIRE_RUNTIME_DIR=str(runtime),PIPEWIRE_REMOTE='pipewire-0',XDG_CONFIG_HOME=str(base/'config'),XDG_CONFIG_DIRS=str(ROOT/'session/configs')+':/etc/xdg',XDG_DATA_HOME=str(base/'data'),WLR_BACKENDS='headless',WLR_LIBINPUT_NO_DEVICES='1',WLR_RENDERER='pixman',ORBIT_NESTED='1',LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe',PULSE_SERVER='unix:'+str(runtime/'no-audio'))
        try:
            return subprocess.run(['dbus-run-session','--','/usr/bin/python3',str(Path(__file__).resolve()),'--inside-private-bus',str(base)],cwd=ROOT,env=env,check=True).returncode
        finally:
            # The private portal may briefly leave its private document FUSE
            # mount while bus shutdown propagates. Never target another path.
            subprocess.run(['fusermount3','-uz',str(runtime/'doc')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            time.sleep(.2)
if __name__=='__main__':main()
