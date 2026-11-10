#!/usr/bin/env python3
"""Optional isolated visual demo; never opens user files or changes the active session."""
import json,os,subprocess,sys,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from native_compositor import NativeCompositor

def client(socket_path,number):
    from PyQt5.QtWidgets import QApplication,QWidget,QVBoxLayout,QLabel,QPushButton
    control=NativeCompositor(socket_path);app=QApplication([]);app.setDesktopFileName('orbit-native-demo')
    window=QWidget();window.setWindowTitle('Orbit Native preview — workspace '+number);window.resize(640,420)
    window.setStyleSheet('QWidget {background:#101419;color:#e1e8ed;font-size:16px;} QLabel{padding:12px;} QPushButton{background:#203037;border:1px solid #ffb59e;padding:12px;}')
    layout=QVBoxLayout(window);layout.addWidget(QLabel('ORBIT NATIVE / WORKSPACE '+number))
    title=QLabel('Live workspace slide');title.setStyleSheet('font-size:30px;');layout.addWidget(title)
    text=QLabel('This is a real Wayland client inside the experimental compositor.\nBoth workspaces move from their live buffers.\nYour existing desktop and apps remain outside this preview.');text.setWordWrap(True);layout.addWidget(text)
    layout.addStretch(1)
    button=QPushButton('Next workspace ↑' if number=='1' else 'Previous workspace ↓');button.clicked.connect(lambda:control.request('step',direction=1 if number=='1' else -1));layout.addWidget(button)
    layout.addWidget(QLabel('Nested shortcut: Ctrl + Alt + PageUp / PageDown'))
    window.show();app.exec()

def main():
    binary=ROOT/'.native-runtime/bin/orbit-compositor'
    if not binary.exists():binary=ROOT/'compositor/target/debug/orbit-compositor'
    process=subprocess.Popen([str(binary)],cwd=ROOT,stdout=subprocess.PIPE,text=True,bufsize=1);fixtures=[]
    try:
        ready_rows=[];ready_event=threading.Event()
        def read_output():
            for line in process.stdout:
                if ready_event.is_set():continue
                try:row=json.loads(line)
                except ValueError:continue
                if row.get('ready'):ready_rows.append(row);ready_event.set()
        threading.Thread(target=read_output,daemon=True).start()
        deadline=time.monotonic()+20
        while not ready_event.wait(.1):
            if process.poll() is not None:raise RuntimeError('Native preview did not start')
            if time.monotonic()>deadline:raise RuntimeError('Native preview timed out')
        ready=ready_rows[0];print(json.dumps(ready),flush=True)
        control=NativeCompositor(ready['control'])
        env=os.environ.copy()
        for key in ('SWAYSOCK','ORBIT_QT','QT_PLUGIN_PATH','QML2_IMPORT_PATH','PYTHONPATH','LD_LIBRARY_PATH'):env.pop(key,None)
        env.update(WAYLAND_DISPLAY=ready['wayland_display'],QT_QPA_PLATFORM='wayland',QT_WAYLAND_SHELL_INTEGRATION='xdg-shell')
        for number in (1,2):
            existing={row['id'] for row in control.windows()}
            fixture=subprocess.Popen(['/usr/bin/python3',str(Path(__file__).resolve()),'--client',ready['control'],str(number)],env=env);fixtures.append(fixture)
            deadline=time.monotonic()+8;ident=None
            while time.monotonic()<deadline:
                ident=next((row['id'] for row in control.windows() if row['id'] not in existing),None)
                if ident is not None:break
                if fixture.poll() is not None:raise RuntimeError('Preview client failed')
                time.sleep(.03)
            if ident is None:raise RuntimeError('Preview client did not connect')
            time.sleep(.15);control.request('maximize',id=ident)
            if number==2:control.move(ident,2)
        process.wait()
    finally:
        for fixture in fixtures:
            if fixture.poll() is None:fixture.terminate()
        for fixture in fixtures:
            try:fixture.wait(timeout=3)
            except subprocess.TimeoutExpired:fixture.kill();fixture.wait()
        if process.poll() is None:process.terminate();process.wait(timeout=5)

if __name__=='__main__':
    if len(sys.argv)==4 and sys.argv[1]=='--client':client(sys.argv[2],sys.argv[3])
    else:main()
