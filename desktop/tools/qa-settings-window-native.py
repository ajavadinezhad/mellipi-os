#!/usr/bin/env python3
"""Ordinary Settings window QA on a disposable native compositor; never physical."""
import importlib.util,json,os,sys,subprocess,tempfile,time,socket,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT;sys.path.insert(0,str(SOURCE_ROOT))
spec=importlib.util.spec_from_file_location('native_shell_qa',ROOT/'tools/qa-native-shell.py');base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base);qa=base.qa
from native_compositor import NativeCompositor

def main():
    parent=native=None
    with tempfile.TemporaryDirectory(prefix='orbit-settings-native-') as temp,open('/tmp/orbit-settings-native-qa.log','w') as log:
        directory=Path(temp);settings=directory/'parent.json';settings.write_text(json.dumps(dict(profile='economy',desktopIcons=False,reducedMotion=True)))
        config=directory/'config';config.mkdir();apps=directory/'share/applications';apps.mkdir(parents=True);(apps/'orbit-settings.desktop').write_text((ROOT/'orbit-settings.desktop').read_text())
        env=dict(os.environ,ORBIT_QA='1',ORBIT_SETTINGS_FILE=str(settings),ORBIT_DATA=str(directory/'parent-data'),XDG_CONFIG_HOME=str(config),PULSE_SERVER='unix:'+str(directory/'no-audio'),LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe')
        try:
            parent=subprocess.Popen([str(ROOT/'run-wayland-session.sh'),'--headless'],env=env,cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
            _,parent_env=qa.wait(lambda:qa.native_process(settings),30)
            settings=directory/'native.json';settings.write_text(json.dumps(dict(profile='economy',desktopIcons=False,reducedMotion=True,shellLayout='fold')))
            env=dict(parent_env,ORBIT_SETTINGS_FILE=str(settings),ORBIT_DATA=str(directory/'native-data'),ORBIT_FOLD_DIR=str(directory),ORBIT_QA='1',XDG_CONFIG_HOME=str(config),XDG_DATA_HOME=str(apps.parent),PULSE_SERVER='unix:'+str(directory/'no-audio'),LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe')
            native=subprocess.Popen([str(ROOT/'run-native-session.sh'),'--nested'],env=env,cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
            _,child=qa.wait(lambda:base.process(settings),40)
            for key in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS','ORBIT_NATIVE_CONTROL'):
                os.environ.pop(key,None)
                if key in child:os.environ[key]=child[key]
            client=NativeCompositor(child['ORBIT_NATIVE_CONTROL']);qa.wait(lambda:qa.control('status'),20)
            qa.control('system-settings')
            def window():return next((w for w in client.snapshot()['windows'] if w['klass']=='orbit-settings'),None)
            row=qa.wait(window,15);ident=int(row['id'])
            def centered():
                row=window();rect=row['rect'];output=client.snapshot()['outputs'][0]['workarea']
                return row if rect['width']>400 and abs(rect['x']+rect['width']/2-output['x']-output['width']/2)<2 and abs(rect['y']+rect['height']/2-output['y']-output['height']/2)<2 else None
            
            try:row=qa.wait(centered,10)
            except AssertionError:
                print('CENTER DEBUG',window(),client.snapshot()['outputs'],qa.control('status')['settings_window'],flush=True);raise
            assert not qa.control('status')['qml_errors'];assert qa.control('status')['panel']=='',qa.control('status')['panel']
            original=dict(row['rect']);print('PASS Settings maps as one centered xdg toplevel, separate from panels',flush=True)
            for section in (10,0,1,2,3,4,5,6,7,8,9,12,15,16):
                qa.control('qa-system-section:'+str(section));time.sleep(.15);assert not qa.control('status')['settings_window']['errors'],(section,qa.control('status')['settings_window']['errors'])
            print('PASS every Settings page loads through the shared-controller transport without QML errors',flush=True)
            client.request('maximize',id=ident);qa.wait(lambda:window().get('maximized'),5)
            client.request('maximize',id=ident,restore=True);qa.wait(lambda:not window().get('maximized'),5)
            client.request('minimize',id=ident);qa.wait(lambda:window().get('minimized'),5)
            qa.control('system-settings');qa.wait(lambda:not window().get('minimized'),5)
            assert int(window()['id'])==ident
            print('PASS maximize, restore, minimize and Settings/task restoration reuse the same window',flush=True)
            client.request('resize',id=ident,rect=dict(original,x=original['x']+8,y=original['y']+8));qa.wait(lambda:window()['rect']['x']==original['x']+8,5)
            time.sleep(.2);assert window()['rect']['x']==original['x']+8
            print('PASS window position remains freely movable instead of recentering on updates',flush=True)
            # Feed input to the disposable parent, translated into the native
            # compositor's client area. Never target the physical input seat.
            from sway_events import HEADER,MAGIC,receive
            with socket.socket(socket.AF_UNIX) as channel:
                channel.connect(parent_env['SWAYSOCK']);channel.sendall(HEADER.pack(MAGIC,0,4));tree=receive(channel)[1]
            def native_view(node):
                if node.get('app_id')=='orbit-native':return node
                for child_node in node.get('nodes',[])+node.get('floating_nodes',[]):
                    found=native_view(child_node)
                    if found:return found
            view=native_view(tree);assert view
            offset_x=view['rect']['x']+view.get('window_rect',{}).get('x',0)
            offset_y=view['rect']['y']+view.get('window_rect',{}).get('y',0)
            output=client.snapshot()['outputs'][0]['rect'];inner=view.get('window_rect',view['rect'])
            border=max(0,(inner['width']-output['width'])//2)
            offset_x+=border;offset_y+=max(0,inner['height']-output['height']-border)
            spec=importlib.util.spec_from_file_location('settings_pointer',ROOT/'tools/qa_wayland_input.py');inputs=importlib.util.module_from_spec(spec);spec.loader.exec_module(inputs)
            pointer=inputs.VirtualPointer(parent_env);bounds=tree['rect']
            try:
                r=dict(window()['rect']);x=offset_x+r['x']+120;y=offset_y+r['y']+26
                pointer.move(x,y,bounds['width'],bounds['height']);time.sleep(.45);stamp=int(time.monotonic()*1000)&0xffffffff
                pointer.send(5,2,struct.pack('=III',stamp,272,1));pointer.send(5,4);pointer.roundtrip();time.sleep(.1)
                pointer.move(x+12,y+10,bounds['width'],bounds['height']);time.sleep(.2)
                pointer.move(x+28,y+20,bounds['width'],bounds['height']);time.sleep(.15)
                pointer.send(5,2,struct.pack('=III',stamp+1,272,0));pointer.send(5,4);pointer.roundtrip()
                
                try:qa.wait(lambda:window()['rect']['x']!=r['x'],5)
                except AssertionError:
                    Path('/tmp/orbit-settings-renderer-protocol.log').write_bytes((directory/'native-data/native-session.log').read_bytes())
                    print('DRAG DEBUG',{'view':view['rect'],'inner':view.get('window_rect'),'bounds':bounds,'rect':r,'pointer':client.status()['pointer'],'errors':qa.control('status')['settings_window']['errors']},flush=True)
                    subprocess.run(['/usr/bin/grim','-o','orbit-nested','/tmp/orbit-private-settings-drag.png'],env=child,stdout=log,stderr=log,timeout=8);raise
                print('PASS real titlebar pointer drag moves the Settings toplevel',flush=True)
                client.request('resize',id=ident,rect=original);qa.wait(lambda:window()['rect']['x']==original['x'],5)
                def title_click(right):
                    rect=window()['rect'];pointer.click(offset_x+rect['x']+rect['width']-right,offset_y+rect['y']+26,bounds['width'],bounds['height'])
                title_click(60)
                try:qa.wait(lambda:window().get('maximized'),5)
                except AssertionError:
                    Path('/tmp/orbit-settings-max-debug.log').write_bytes((directory/'native-data/native-session.log').read_bytes())
                    print('MAX DEBUG',window(),client.status()['pointer'],qa.control('status')['settings_window'],flush=True);raise
                title_click(60);qa.wait(lambda:not window().get('maximized'),5)
                title_click(96);qa.wait(lambda:window().get('minimized'),5)
                qa.control('system-settings');qa.wait(lambda:not window().get('minimized'),5)
                print('PASS actual titlebar maximize/restore and minimize buttons',flush=True)
                title_click(24);qa.wait(lambda:window() is None,5)
            finally:pointer.close()

            qa.control('system-settings');qa.wait(window,10)
            print('PASS close and reopen creates a new Settings window cleanly',flush=True)
        finally:base.stop(native);base.stop(parent)
if __name__=='__main__':main()
