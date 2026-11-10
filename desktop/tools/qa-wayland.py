#!/usr/bin/env python3
"""Finite checks of Orbit's own nested desktop and test windows."""
import json,os,socket,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from control import socket_path

def control(command):
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(3);sock.connect(socket_path());sock.sendall((command+'\n').encode());response=bytearray()
        while True:
            data=sock.recv(32768)
            if not data:break
            response.extend(data)
        return json.loads(response) if response else None

def wait(check,timeout=4):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        state=control('status')
        if check(state):return state
        time.sleep(.035)
    raise AssertionError(control('status'))

def shot(name):subprocess.run(['grim',str(ROOT/name)],check=True)
fixture_code='''from PyQt5.QtWidgets import QApplication,QWidget,QVBoxLayout,QLabel
from PyQt5.QtCore import QTimer
app=QApplication([]);app.setApplicationName("orbit-fixture");app.setDesktopFileName("orbit-fixture");windows=[]
for i in range(2):
 w=QWidget();w.setWindowTitle("Orbit QA fixture "+str(i+1));w.resize(360,220);layout=QVBoxLayout(w);layout.addWidget(QLabel("Native Wayland application test"));w.show();windows.append(w)
QTimer.singleShot(120000,app.quit);app.exec()
'''
env=os.environ.copy();env.update(PYTHONPATH=str(ROOT/'.wayland-runtime/usr/lib/python3/dist-packages'),QT_PLUGIN_PATH=str(ROOT/'.wayland-runtime/usr/lib/x86_64-linux-gnu/qt5/plugins'),LD_LIBRARY_PATH=str(ROOT/'.wayland-runtime/usr/lib/x86_64-linux-gnu')+':'+env.get('LD_LIBRARY_PATH',''));env['QT_QPA_PLATFORM']='wayland';env['QT_WAYLAND_SHELL_INTEGRATION']='xdg-shell'
fixture=subprocess.Popen([str(ROOT/'.venv/bin/python'),'-c',fixture_code],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
    wait(lambda s:any('fixture' in g['name'].lower() and g['windows']==2 for g in s['dock']),6)
    for page in ['launcher','overview','shelf','ai','capture','settings','quick','notifications']:
        control(page);time.sleep(.23);state=control('status');assert state['panel']==page;assert not state['qml_errors'],state['qml_errors']
    control('switch-next');state=wait(lambda s:s['switching']);first=state['switch_index'];control('switch-next');state=wait(lambda s:s['switch_index']!=first);control('switch-cancel');wait(lambda s:not s['switching'])
    control('qa-menu');wait(lambda s:s['context_open']);time.sleep(.16);shot('wayland-context-menu.png');control('qa-close-menu')
    control('qa-tip');state=wait(lambda s:bool(s['tooltip']));assert state['tooltip']['y']>=36;time.sleep(.15);shot('wayland-tooltip.png');control('qa-close-tip')
    control('qa-dark');control('settings');time.sleep(.25);shot('wayland-dark.png')
    control('qa-light');wait(lambda s:s['mode']=='light');time.sleep(.23);shot('wayland-light.png');control('settings');time.sleep(.16)
    control('workspace:2');wait(lambda s:s['workspace']==2);control('workspace:1');wait(lambda s:s['workspace']==1)
    control('qa-dark');state=control('status');assert not state['qml_errors'],state['qml_errors']
    print(json.dumps({'wayland':True,'native_windows_in_dock':2,'panels':8,'alt_tab_cycle':True,'right_click':True,'tooltip_bounds':True,'dark_light':True,'workspace_navigation':2,'qml_errors':state['qml_errors']},indent=2))
finally:
    fixture.terminate()
    try:fixture.wait(timeout=3)
    except subprocess.TimeoutExpired:fixture.kill()
