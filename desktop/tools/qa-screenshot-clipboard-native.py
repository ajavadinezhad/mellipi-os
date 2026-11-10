#!/usr/bin/env python3
"""PNG clipboard transfer QA on a disposable native output; never the physical clipboard."""
import importlib.util,json,os,sys,subprocess,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT;sys.path.insert(0,str(SOURCE_ROOT))
spec=importlib.util.spec_from_file_location('native_shell_qa',ROOT/'tools/qa-native-shell.py');base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base);qa=base.qa
from native_compositor import NativeCompositor
from panel_policy import panel_rect,panel_body_origin

def main():
    parent=native=None;checks=[]
    with tempfile.TemporaryDirectory(prefix='orbit-screenshot-clipboard-') as temp,open('/tmp/orbit-screenshot-clipboard-native.log','w') as log:
        directory=Path(temp);settings=directory/'parent.json';settings.write_text(json.dumps(dict(profile='economy',desktopIcons=False,reducedMotion=True)))
        config=directory/'config';config.mkdir()
        env=dict(os.environ,RUST_LOG='info',ORBIT_QA='1',ORBIT_SETTINGS_FILE=str(settings),ORBIT_DATA=str(directory/'parent-data'),XDG_CONFIG_HOME=str(config),PULSE_SERVER='unix:'+str(directory/'no-audio'),LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe')
        for key in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','ORBIT_NATIVE_CONTROL','MESA_LOADER_DRIVER_OVERRIDE'):env.pop(key,None)
        try:
            parent=subprocess.Popen([str(ROOT/'run-wayland-session.sh'),'--headless'],env=env,cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
            _,parent_env=qa.wait(lambda:qa.native_process(settings),30)
            settings=directory/'native.json';settings.write_text(json.dumps(dict(profile='economy',desktopIcons=False,reducedMotion=True,shellLayout='fold',panelPosition='left')))
            env=dict(parent_env,RUST_LOG='info',ORBIT_SETTINGS_FILE=str(settings),ORBIT_DATA=str(directory/'native-data'),ORBIT_FOLD_DIR=str(directory),ORBIT_QA='1',XDG_CONFIG_HOME=str(config),PULSE_SERVER='unix:'+str(directory/'no-audio'),LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe')
            native=subprocess.Popen([str(ROOT/'run-native-session.sh'),'--nested'],env=env,cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
            initial_pid,child=qa.wait(lambda:base.process(settings),40)
            for key in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS','ORBIT_NATIVE_CONTROL'):
                os.environ.pop(key,None)
                if key in child:os.environ[key]=child[key]
            client=NativeCompositor(child['ORBIT_NATIVE_CONTROL']);qa.wait(lambda:qa.control('status'),20)
            from PyQt5.QtGui import QImage,QColor
            import random
            pixels=random.Random(0).randbytes(640*480*4);image=QImage(pixels,640,480,QImage.Format_ARGB32).copy();path=directory/'fixture.png';image.save(str(path))
            reader=directory/'reader.py';result=directory/'received.png';ready=directory/'consumer-ready';gate=directory/'read-gate'
            reader.write_text("from PyQt5.QtWidgets import QApplication,QLabel\nfrom PyQt5.QtCore import QTimer\nfrom pathlib import Path\nimport sys\na=QApplication(['orbit-clipboard-test']);w=QLabel('Paste fixture');w.setWindowTitle('Clipboard fixture');w.resize(120,80);w.show()\ndef read():\n if not Path(sys.argv[3]).exists():return\n Path(sys.argv[2]).touch()\n d=bytes(a.clipboard().mimeData().data('image/png'))\n if d:Path(sys.argv[1]).write_bytes(d);a.quit()\nt=QTimer();t.timeout.connect(read);t.start(100);QTimer.singleShot(12000,lambda:a.exit(1));sys.exit(a.exec_())\n")
            consumer=subprocess.Popen(['/usr/bin/python3',str(reader),str(result),str(ready),str(gate)],env=dict(child,QT_QPA_PLATFORM='wayland',QT_WAYLAND_SHELL_INTEGRATION='xdg-shell'),stdout=log,stderr=log)
            window=qa.wait(lambda:next((w for w in client.snapshot()['windows'] if w['title']=='Clipboard fixture' and w['pid']==consumer.pid and w['rect']['width']>0),None),10)
            client.request('focus',id=int(window['id']));gate.touch();qa.wait(lambda:ready.exists(),10)
            assert client.status()['capabilities']['native_png_clipboard']
            assert client.request('clipboard_png',path=str(path))=={'ok':True}
            try:
                qa.wait(lambda:result.exists(),12)
                assert result.read_bytes()==path.read_bytes(),'Clipboard PNG changed in transfer'
                consumer.wait(timeout=3)
                # An independent Xwayland client can paste the same native selection.
                result.unlink();ready.unlink();gate.unlink()
                consumer=subprocess.Popen(['/usr/bin/python3',str(reader),str(result),str(ready),str(gate)],env=dict(child,QT_QPA_PLATFORM='xcb'),stdout=log,stderr=log)
                window=qa.wait(lambda:next((w for w in client.snapshot()['windows'] if w['title']=='Clipboard fixture' and w['pid']==consumer.pid and w['rect']['width']>0),None),10)
                def focused_receiver():
                    row=next((w for w in client.snapshot()['windows'] if w['pid']==consumer.pid),None)
                    if row and not row['active']:client.request('focus',id=int(row['id']))
                    return row and row['active']
                qa.wait(focused_receiver,10);gate.touch()
                try:qa.wait(lambda:result.exists(),12)
                except AssertionError:
                    print('XCB DEBUG',client.snapshot()['windows'],flush=True);raise
                assert result.read_bytes()==path.read_bytes();consumer.wait(timeout=3)
                qa.control('system-settings')
                for section in (10,0,1,2,3,4,5,6,7,8,9,12,15,16):
                    qa.control('qa-system-section:'+str(section));time.sleep(.1)
                    assert not qa.control('status')['settings_window']['errors']
                print('PASS large native PNG pasted unchanged into independent Wayland and Xwayland clients; no clipboard helper process',flush=True)
            finally:
                if consumer.poll() is None:consumer.terminate();consumer.wait(timeout=3)
        finally:
            native_log=directory/'native-data/native-session.log'
            if native_log.exists():Path('/tmp/orbit-clipboard-owned-native-session.log').write_bytes(native_log.read_bytes())
            base.stop(native);base.stop(parent)
if __name__=='__main__':main()
