#!/usr/bin/python3
"""Finite Chrome WebRTC capture of an owned private native Wayland output.

Uses a disposable profile/HOME, private D-Bus and PipeWire, and an owned loopback
page/CDP socket. Never connects to existing browser targets or physical devices.
"""
import asyncio,http.server,importlib.util,json,os,subprocess,sys,tempfile,threading,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE_ROOT=ROOT/'src' if (ROOT/'src').is_dir() else ROOT
spec=importlib.util.spec_from_file_location('private_screencast',ROOT/'tools/qa-screencast-native.py');fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
PAGE=b'''<!doctype html><title>Abstract private browser capture fixture</title><style>body{background:#05f;color:white}</style><h1>Private browser capture test</h1><video hidden muted></video><canvas hidden></canvas><script>
let flip=false;setInterval(()=>{flip=!flip;document.body.style.background=flip?'#ff5500':'#0055ff'},170);
window.qa={started:false,done:false,frames:0,hashes:[],width:0,height:0,error:''};
window.startCapture=async()=>{qa.requested=true;qa.activation=navigator.userActivation.isActive;qa.focus=document.hasFocus();qa.visibility=document.visibilityState;try{
 const stream=await navigator.mediaDevices.getDisplayMedia({video:{displaySurface:'monitor'},audio:false,selfBrowserSurface:'exclude',surfaceSwitching:'exclude',systemAudio:'exclude'});window.qaStream=stream;
 const video=document.querySelector('video');video.srcObject=stream;await video.play();qa.started=true;
 const canvas=document.querySelector('canvas');canvas.width=64;canvas.height=48;const ctx=canvas.getContext('2d',{willReadFrequently:true});
 const hashes=new Set();let last=-1;
 const sample=()=>{if(!video.videoWidth)return setTimeout(sample,100);if(video.currentTime===last)return setTimeout(sample,100);last=video.currentTime;
 ctx.drawImage(video,0,0,64,48);const pixels=ctx.getImageData(0,0,64,48).data;let hash=2166136261;for(const b of pixels){hash=Math.imul(hash^b,16777619)>>>0;}hashes.add(hash);
 qa.frames++;qa.width=video.videoWidth;qa.height=video.videoHeight;qa.hashes=[...hashes];
 if(qa.frames>=8&&hashes.size>=2){stream.getTracks().forEach(t=>t.stop());qa.stopped=stream.getTracks().every(t=>t.readyState==='ended');qa.done=true;}else if(qa.frames>=100){qa.error='Frames did not change';qa.done=true}else setTimeout(sample,120);};sample();
}catch(e){qa.error=e.name+': '+e.message;qa.done=true;}};
</script>'''
class PageHandler(http.server.BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path!='/':self.send_error(404);return
  self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(PAGE)));self.end_headers();self.wfile.write(PAGE)
 def log_message(self,*args):pass

def browser_check(base,env,launch,log):
 profile=base/'browser-profile';home=base/'browser-home';profile.mkdir(mode=0o700);home.mkdir(mode=0o700)
 server=http.server.HTTPServer(('127.0.0.1',0),PageHandler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 try:
  target='http://127.0.0.1:'+str(server.server_port)+'/'
  browser_env=dict(env,HOME=str(home),QT_QPA_PLATFORM='wayland')
  for key in ('DISPLAY','XAUTHORITY','SWAYSOCK'):browser_env.pop(key,None)
  arguments=['/opt/google/chrome/chrome','--ozone-platform=wayland','--user-data-dir='+str(profile),'--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-component-update','--disable-sync','--disable-extensions','--disable-default-apps','--password-store=basic','--use-mock-keychain','--disable-gpu','--enable-features=WebRTCPipeWireCapturer','--auto-select-screen-capture-source','--remote-debugging-address=127.0.0.1','--remote-debugging-port=0','--window-size=640,480',target]
  browser=subprocess.Popen(arguments,cwd=ROOT,env=browser_env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
  def drain_browser():
   for line in browser.stdout:
    if b'DevTools listening on ' not in line:
     log.write(line.decode('utf-8','replace'));log.flush()
  browser_log=threading.Thread(target=drain_browser,daemon=True);browser_log.start()
  marker=profile/'DevToolsActivePort'
  def devtools():
   if browser.poll() is not None:raise AssertionError('Owned Chrome exited before local debugging startup')
   if marker.is_file():
    lines=marker.read_text().splitlines()
    if len(lines)>=2:return int(lines[0])
  port=fixture.wait(devtools,45)
  def own_page():
   try:
    with urllib.request.urlopen('http://127.0.0.1:'+str(port)+'/json',timeout=2) as response:rows=json.load(response)
    return next((row for row in rows if row.get('type')=='page' and row.get('url')==target),None)
   except OSError:return None
  page=fixture.wait(own_page,35)
  endpoint=page['webSocketDebuggerUrl'];assert endpoint.startswith('ws://127.0.0.1:'+str(port)+'/')
  def dump():
   result=subprocess.run(['/usr/bin/pw-dump'],env=env,text=True,capture_output=True,timeout=3,check=True);return json.loads(result.stdout)
  linked=set();sources=set()
  def link_private_ports():
   rows=dump();nodes={r['id']:r.get('info',{}).get('props',{}) for r in rows if r.get('type')=='PipeWire:Interface:Node'}
   output_nodes={i for i,p in nodes.items() if p.get('media.class')=='Video/Source'}
   # No session/device manager runs here. Only this disposable browser can own
   # a Stream/Input/Video node; connect those exact ports to the portal source.
   inputs={i for i,p in nodes.items() if p.get('media.class')=='Stream/Input/Video'}
   outs=[r['id'] for r in rows if r.get('type')=='PipeWire:Interface:Port' and r.get('info',{}).get('props',{}).get('node.id') in output_nodes and r.get('info',{}).get('props',{}).get('port.direction')=='out']
   ins=[r['id'] for r in rows if r.get('type')=='PipeWire:Interface:Port' and r.get('info',{}).get('props',{}).get('node.id') in inputs and r.get('info',{}).get('props',{}).get('port.direction')=='in']
   for out in outs:
    for inp in ins:
     if (out,inp) not in linked:
      result=subprocess.run(['/usr/bin/pw-link',str(out),str(inp)],env=env,timeout=3,stdout=log,stderr=log)
      if result.returncode==0:linked.add((out,inp));sources.update(output_nodes)
  async def check():
   import websockets
   async with websockets.connect(endpoint,max_size=262144) as ws:
    serial=0
    async def command(method,params):
     nonlocal serial
     serial+=1;ident=serial;await ws.send(json.dumps(dict(id=ident,method=method,params=params)))
     while True:
      reply=json.loads(await asyncio.wait_for(ws.recv(),5))
      if reply.get('id')==ident:
       assert 'error' not in reply,reply;return reply.get('result',{})
    ready_until=time.monotonic()+15
    while time.monotonic()<ready_until:
     ready=await command('Runtime.evaluate',dict(expression="document.readyState==='complete' && typeof window.startCapture==='function'",returnByValue=True))
     if ready.get('result',{}).get('value') is True:break
     await asyncio.sleep(.1)
    else:raise AssertionError('Owned browser test page did not initialize')
    started=await command('Runtime.evaluate',dict(expression='window.startCapture()',userGesture=True,awaitPromise=False))
    assert 'exceptionDetails' not in started,('Capture invocation failed',started)
    deadline=time.monotonic()+35;status={}
    while time.monotonic()<deadline:
     link_private_ports()
     result=await command('Runtime.evaluate',dict(expression='JSON.stringify(window.qa)',returnByValue=True))
     status=json.loads(result.get('result',{}).get('value','{}'))
     if status.get('error'):raise AssertionError('Browser capture failed: '+status['error'])
     if status.get('done'):break
     await asyncio.sleep(.15)
    assert status.get('done') and status.get('stopped'),('Browser video did not finish/stop',status)
    assert status['frames']>=8 and len(status['hashes'])>=2 and status['width']>0 and status['height']>0,status
    assert sources,'Browser never received the private portal PipeWire source'
    until=time.monotonic()+8
    while time.monotonic()<until:
     if not any(row.get('id') in sources and row.get('type')=='PipeWire:Interface:Node' for row in dump()):break
     await asyncio.sleep(.1)
    else:raise AssertionError('Stopping the browser track did not release the private source')
    print('PASS actual Chrome getDisplayMedia delivered changing video frames and stopped its source',flush=True)
    print(json.dumps(dict(browser_tested=True,private_profile=True,private_bus=True,private_pipewire=True,no_device_manager=True,frames=status['frames'],distinct_frames=len(status['hashes']),width=status['width'],height=status['height'],stopped=status['stopped'])),flush=True)
  asyncio.run(check())
 finally:
  if 'browser' in locals():fixture.stop(browser)
  if 'browser_log' in locals():browser_log.join(timeout=2)
  server.shutdown();server.server_close();thread.join(timeout=2)

def main():
 if len(sys.argv)==3 and sys.argv[1]=='--inside-private-bus':return fixture.inside(Path(sys.argv[2]),browser_check=browser_check)
 with tempfile.TemporaryDirectory(prefix='abstract-browser-capture-',ignore_cleanup_errors=True) as temporary:
  base=Path(temporary);runtime=base/'runtime';runtime.mkdir(mode=0o700)
  env={key:value for key,value in os.environ.items() if key not in ('WAYLAND_DISPLAY','SWAYSOCK','DISPLAY','ORBIT_NATIVE_CONTROL','DBUS_SESSION_BUS_ADDRESS','PIPEWIRE_REMOTE','PIPEWIRE_RUNTIME_DIR','PULSE_SERVER','XDG_DESKTOP_PORTAL_DIR')}
  env.update(ABSTRACT_PRIVATE_PORTAL_QA='1',XDG_RUNTIME_DIR=str(runtime),PIPEWIRE_RUNTIME_DIR=str(runtime),PIPEWIRE_REMOTE='pipewire-0',XDG_CONFIG_HOME=str(base/'config'),XDG_CONFIG_DIRS=str(SOURCE_ROOT/'session/configs')+':/etc/xdg',XDG_DATA_HOME=str(base/'data'),WLR_BACKENDS='headless',WLR_LIBINPUT_NO_DEVICES='1',WLR_RENDERER='pixman',ORBIT_NESTED='1',LIBGL_ALWAYS_SOFTWARE='1',GALLIUM_DRIVER='llvmpipe',PULSE_SERVER='unix:'+str(runtime/'no-audio'))
  try:return subprocess.run(['dbus-run-session','--','/usr/bin/python3',str(Path(__file__).resolve()),'--inside-private-bus',str(base)],cwd=ROOT,env=env,check=True).returncode
  finally:subprocess.run(['fusermount3','-uz',str(runtime/'doc')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
if __name__=='__main__':main()
