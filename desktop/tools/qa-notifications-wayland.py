"""Finite card, toast and action-button clicks in a disposable headless session only."""
import importlib.util,json,os,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
def load(name,file):
 spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
qa=load('qa','qa-screenshots-wayland.py');vp=load('vp','qa_wayland_input.py')
fixture='''import sys,json\nfrom gi.repository import Gio,GLib\nfrom pathlib import Path\nbus=Gio.bus_get_sync(Gio.BusType.SESSION,None);loop=GLib.MainLoop()\ndef received(*args):\n Path(sys.argv[1]).write_text(json.dumps(args[5].unpack()));loop.quit()\nbus.signal_subscribe(None,'org.freedesktop.Notifications','ActionInvoked',None,None,0,received)\nident=bus.call_sync('org.freedesktop.Notifications','/org/freedesktop/Notifications','org.freedesktop.Notifications','Notify',GLib.Variant('(susssasa{sv}i)',('Disposable QA',0,'','Click fixture','Only a private test notification',(['default','Open','reply','Reply'] if len(sys.argv)>2 else ['default','Open']),{},15000)),None,0,3000,None).unpack()[0]\nPath(sys.argv[1]+'.ready').write_text(str(ident));GLib.timeout_add_seconds(12,lambda:(loop.quit(),False)[1]);loop.run()\n'''
session=pointer=client=None;routed=False
with tempfile.TemporaryDirectory(prefix='orbit-notification-ui-') as temp,open('/tmp/orbit-notification-ui.log','w') as log:
 settings=Path(temp)/'settings.json';settings.write_text(json.dumps({'profile':'economy','reducedMotion':True,'desktopIcons':False}));env=os.environ.copy();env.update(ORBIT_SETTINGS_FILE=str(settings),ORBIT_DATA=temp+'/data',ORBIT_QA='1',XDG_CONFIG_HOME=temp+'/config')
 try:
  session=subprocess.Popen([str(ROOT/'run-wayland-session.sh'),'--headless'],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
  pid,native=qa.wait(lambda:qa.native_process(settings),30)
  for key in ('SWAYSOCK','WAYLAND_DISPLAY','DISPLAY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS'):
   if key in native:os.environ[key]=native[key]
  routed=True;qa.wait(lambda:qa.control('status'));pointer=vp.VirtualPointer(native)
  for case in ('toast','card','button'):
   output=Path(temp)/case
   client=subprocess.Popen(['/usr/bin/python3','-c',fixture,str(output)]+(['named'] if case=='button' else []),env=native,stdout=log,stderr=log)
   qa.wait(lambda:Path(str(output)+'.ready').exists(),8);time.sleep(.3)
   if case in ('card','button'):qa.control('notifications');time.sleep(.3);pointer.click(1000,234 if case=='button' else 188)
   else:pointer.click(1060,74)
   qa.wait(output.exists,4);assert json.loads(output.read_text())[1]==('reply' if case=='button' else 'default');assert client.wait(timeout=3)==0;client=None
   assert qa.control('status')['panel']=='';print('PASS',case,'click returned expected app action',flush=True)
  assert not qa.control('status')['qml_errors'],qa.control('status')['qml_errors'];print('PASS QML clean',flush=True)
  pointer.close();pointer=None;qa.control('quit');session.wait(timeout=12)
 finally:
  if client and client.poll() is None:client.terminate();client.wait(timeout=3)
  if pointer:pointer.close()
  if session and session.poll() is None and routed:
   import sway_events
   try:sway_events.command('exit')
   except Exception:pass
  if session and session.poll() is None:
   try:session.wait(timeout=5)
   except subprocess.TimeoutExpired:session.terminate();session.wait(timeout=5)
