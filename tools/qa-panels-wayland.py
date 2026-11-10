#!/usr/bin/env python3
"""Bounded private panel switching, tab resizing and geometry stress checks."""
import importlib.util,json,os,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('qa_helpers',ROOT/'tools/qa-screenshots-wayland.py');h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
control,wait=h.control,h.wait
import sway_events
session=fixture=None;routed=False;completed=[]
widths={'quick':350,'tray':310,'music':350,'launcher':760,'overview':760,'settings':420,'battery':380}
code='''from PyQt5.QtWidgets import QApplication,QWidget,QLabel,QVBoxLayout
from PyQt5.QtCore import QTimer
app=QApplication([]);app.setApplicationName('orbit-panel-focus-fixture');app.setDesktopFileName('orbit-panel-focus-fixture');windows=[]
for index in range(2):
 w=QWidget();w.setWindowTitle('Orbit focus fixture '+str(index));w.resize(320,180);QVBoxLayout(w).addWidget(QLabel('Disposable focus test'));w.show();windows.append(w)
QTimer.singleShot(60000,app.quit);app.exec()
'''
def views(node):
 found=[node] if node.get('app_id')=='orbit-panel-focus-fixture' else []
 for child in node.get('nodes',[])+node.get('floating_nodes',[]):found.extend(views(child))
 return found
with tempfile.TemporaryDirectory(prefix='orbit-panel-stress-') as temporary:
 settings=Path(temporary)/'settings.json';settings.write_text(json.dumps({'compact':True,'profile':'economy','reducedMotion':False}));env=os.environ.copy();env.update(ORBIT_SETTINGS_FILE=str(settings),ORBIT_DATA=str(Path(temporary)/'data'),ORBIT_QA='1',XDG_CONFIG_HOME=str(Path(temporary)/'config'))
 log=open('/tmp/orbit-panel-stress.log','w')
 try:
  session=subprocess.Popen([str(ROOT/'run-wayland-session.sh'),'--headless'],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
  first_pid,native_env=wait(lambda:h.native_process(settings),30)
  for key in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS'):
   if key in native_env:os.environ[key]=native_env[key]
  routed=True;initial=wait(lambda:control('status'));output=initial['selected_output']
  sway_events.command('output '+output+' mode 1920x1080');wait(lambda:control('status')['screen_geometry']['width']==1920)
  print('READY1920',first_pid,flush=True)
  for index,panel in enumerate(list(widths)*8):
   control(panel);deadline=time.monotonic()+3
   while True:
    status=control('status');current=h.native_process(settings)
    assert current and current[0]==first_pid,('Native process restarted',index,panel,current)
    assert not status['qml_errors'],status['qml_errors'];geometry=status['panel_geometry']
    mask=status.get('panel_mask',{})
    if status['panel']==panel and mask.get('width')==widths[panel] and mask.get('height',0)>0:
     if panel in ('launcher','overview'):assert mask['height']==560,(panel,mask)
     assert (geometry['width'],geometry['height'])==(760,620),(panel,geometry)
     right=panel in ('quick','tray','music','battery');assert mask['x']==(760-mask['width'] if right else (760-mask['width']+1)//2),(panel,mask)
     assert mask['y']==(0 if right else (620-mask['height']+1)//2),(panel,mask)
     break
    assert time.monotonic()<deadline,('Panel did not settle',index,panel,status['panel'],geometry,control('qa-panel-state'))
    time.sleep(.025)
   time.sleep(.07);completed.append(panel)
   if len(completed)%7==0:print('SWITCHES',len(completed),'latest',panel,geometry,flush=True)
  print('PANELS_PASS',len(completed),flush=True)
  control('quick');wait(lambda:(s if (s:=control('status'))['panel']=='quick' and s.get('panel_mask',{}).get('width')==350 else None));time.sleep(.15)
  sizes=[]
  for index in (0,1,2,0,1,2,0):
   control('qa-quick-tab-'+str(index));time.sleep(.16);status=control('status')
   assert status['panel']=='quick',('Quick tab closed',index,status['panel'])
   assert not status['qml_errors'],status['qml_errors'];assert status.get('panel_mask',{}).get('width')==350
   sizes.append(status['panel_mask']['height'])
  assert len(set(sizes))>=2,('Quick sections did not change actual geometry',sizes)
  print('QUICK_TABS_PASS',sizes,flush=True)
  control('quick');wait(lambda:control('status')['panel']=='');time.sleep(.2)
  control('qa-comfortable');time.sleep(.2);control('tray');status=wait(lambda:(s if (s:=control('status'))['panel']=='tray' and s.get('panel_mask',{}).get('width')==310 else None),5)
  assert not status['qml_errors'];assert h.native_process(settings)[0]==first_pid;print('DENSITY_PASS',status['panel_geometry'],flush=True)
  control('tray');wait(lambda:control('status')['panel']=='');time.sleep(.2)
  sway_events.command('output '+output+' mode 1280x720');wait(lambda:control('status')['screen_geometry']['width']==1280)
  control('launcher');status=wait(lambda:(s if (s:=control('status'))['panel']=='launcher' and s.get('panel_mask',{}).get('width')==760 else None),5)
  assert status['panel_mask']['height']==620,status['panel_mask'];assert not status['qml_errors'];assert h.native_process(settings)[0]==first_pid;print('OUTPUT_PASS',status['panel_geometry'],flush=True)
  control('launcher');wait(lambda:control('status')['panel']=='');time.sleep(.2)
  fenv=native_env.copy();fenv['QT_WAYLAND_SHELL_INTEGRATION']='xdg-shell';fixture=subprocess.Popen(['/usr/bin/python3','-c',code],cwd=ROOT,env=fenv,stdout=log,stderr=log)
  two=wait(lambda:(v if len(v:=views(sway_events.request(4)))==2 else None));sway_events.command('[con_id='+str(two[0]['id'])+'] focus');time.sleep(.15)
  control('launcher');time.sleep(.25);before=control('status');sway_events.command('[con_id='+str(two[1]['id'])+'] focus');time.sleep(.2);after=control('status');seats=sway_events.request(101)
  focused=next((v['id'] for v in views(sway_events.request(4)) if v.get('focused')),None)
  focus_result=dict(before_active=before['panel_geometry']['active'],before_panel=before['panel'],after_panel=after['panel'],focused_fixture=focused,expected_fixture=two[1]['id'],seats=seats)
  if before['panel_geometry']['active']:assert after['panel']=='',focus_result
  assert focused==two[1]['id'],focus_result
  print('FOCUS_RESULT',json.dumps(focus_result),flush=True)
  control('quit');session.wait(timeout=12);assert session.returncode==0
  text=Path('/tmp/orbit-panel-stress.log').read_text(errors='replace');assert 'layer_surface has never been configured' not in text and 'fatal error' not in text,text[-1000:]
  print(json.dumps({'switches':len(completed),'quick_tabs':sizes,'density_and_output':True,'single_native_pid':first_pid,'focus_verified':bool(before['panel_geometry']['active']),'qml_errors':[]}),flush=True)
 finally:
  if fixture and fixture.poll() is None:fixture.terminate();fixture.wait(timeout=5)
  if session and session.poll() is None and routed:
   try:sway_events.command('exit')
   except Exception:pass
  if session and session.poll() is None:
   try:session.wait(timeout=5)
   except subprocess.TimeoutExpired:session.terminate();session.wait(timeout=5)
  log.close()
