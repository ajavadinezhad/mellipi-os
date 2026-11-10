#!/usr/bin/env python3
"""Run under dbus-run-session to test registration, menu actions and item removal."""
import sys,subprocess,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT;sys.path.insert(0,str(SOURCE_ROOT));os.environ['QT_QPA_PLATFORM']='offscreen'
from qt_compat import QApplication,QTimer,QObject,Signal
from tray import TrayHost
class Bridge(QObject):
    interactionChanged=Signal()
    themeMode="light"
    def hideTooltip(self):pass
app=QApplication([]);bridge=Bridge();host=TrayHost(bridge);fixture=None;stage=0;failure=[]
def check():
    global fixture,stage
    if stage==0 and host.worker.owned:
        fixture=subprocess.Popen(['/usr/bin/python3',str(ROOT/'tools/qa-tray-item.py')],stdout=subprocess.PIPE,text=True);stage=1
    elif stage==1 and host.rows:
        key=next(iter(host.rows));assert host.rows[key]['name']=='Orbit tray fixture';host.activate(key,10,30);host.menu(key,10,30);stage=2
    elif stage==2 and hasattr(bridge,'_context'):
        items=bridge._context['items'];assert items[0]['label']=='Open' and items[1]['enabled'] is False
        host.clickMenu(*items[0]['value']);stage=3;QTimer.singleShot(250,fixture.terminate)
    elif stage==3 and fixture.poll() is not None and not host.rows:
        output=fixture.stdout.read();assert 'Activate' in output and 'Event' in output;print('PASS: tray registration, activation, menu states/actions, process-exit cleanup');timer.stop();app.quit()
def tick():
    try:check()
    except Exception as e:failure.append(str(e));app.exit(1)
timer=QTimer();timer.timeout.connect(tick);timer.start(40)
QTimer.singleShot(10000,lambda:(failure.append('timeout stage '+str(stage)),app.exit(1)))
result=app.exec()
if fixture and fixture.poll() is None:fixture.terminate();fixture.wait()
host.close()
if failure:print(failure,file=sys.stderr)
sys.exit(result)
