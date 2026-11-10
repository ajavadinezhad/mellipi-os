#!/usr/bin/env python3
"""Boot and inspect an Abstract installer ISO in an owned disposable QEMU VM.

Only a private qcow2 target is writable. No host disks, USB/GPU passthrough,
shared folders, host display, public listening sockets, or guest SSH setup.
Pixel checks detect display content; they never certify installer/desktop health.
"""
import argparse, hashlib, importlib.util, json, os, re, secrets, shutil, signal, socket, stat, subprocess, sys, time
from pathlib import Path
KIND='abstract-live-iso-qa'
TOOLS=('qemu-system-x86_64','qemu-img')
FIRMWARE_CACHE=Path.home()/'Projects/.abstract-live-qa-firmware'

def run(args,**kwargs):return subprocess.run([str(a) for a in args],check=True,**kwargs)
def sha256(path):
 with Path(path).open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()
def safe_path(path):
 raw=Path(path)
 if raw.is_symlink():raise ValueError('Refusing a symbolic-link input/directory')
 path=raw.resolve()
 if any(path==p or p in path.parents for p in map(Path,('/dev','/proc','/sys'))):raise ValueError('Host device and pseudo-filesystem paths are forbidden')
 if ',' in str(path) or any(ord(c)<32 for c in str(path)):raise ValueError('QEMU paths cannot contain commas or controls')
 return path

def owned_output(path):
 if path.exists() or path.is_symlink():
  info=path.lstat()
  if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1:raise ValueError('QA output must be an unlinked owned regular file: '+str(path))
 return path

def private_json(path,value):
 if path.is_symlink():raise ValueError('Refusing symbolic-link metadata')
 tmp=path.with_name(path.name+'.new')
 fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 try:
  with os.fdopen(fd,'w') as stream:json.dump(value,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
  os.replace(tmp,path)
 finally:tmp.unlink(missing_ok=True)

def load(work):
 work=safe_path(work);info=work.stat()
 if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise ValueError('QA work directory must be private and owned by this user')
 path=work/'vm.json';info=path.lstat()
 if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_size>32768:raise ValueError('Unsafe QA metadata file')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 with os.fdopen(fd) as source:state=json.load(source)
 if state.get('kind')!=KIND or not re.fullmatch(r'abstract-live-qa-[0-9a-f]{16}',state.get('name','')):raise ValueError('Not an owned Abstract live-ISO QA VM')
 if state.get('workdir')!=str(work):raise ValueError('QA metadata work directory mismatch')
 return work,state

def owned_pid(work,state,allow_stopped=False):
 pid=state.get('pid')
 if type(pid) is not int or pid<2:raise ValueError('Invalid VM PID')
 proc=Path('/proc')/str(pid)
 if not proc.exists():
  if allow_stopped:return None
  raise RuntimeError('Owned QA VM is not running')
 try:
  if proc.stat().st_uid!=os.getuid():raise ValueError('VM PID belongs to another user')
  args=(proc/'cmdline').read_bytes().split(b'\0');start=(proc/'stat').read_text().rsplit(')',1)[1].split()[19]
 except (FileNotFoundError,ProcessLookupError):
  if allow_stopped:return None
  raise RuntimeError('Owned QA VM has stopped')
 if not args or not args[0]:
  if allow_stopped:return None
  raise RuntimeError('Owned QA VM has exited')
 expected=[state['name'].encode(),('unix:'+str(work/'qmp.sock')+',server=on,wait=off').encode()]
 if state.get('process_start')!=start or not Path(os.fsdecode(args[0])).name.startswith('qemu-system-') or any(value not in args for value in expected):raise ValueError('PID identity differs from the owned QA VM; refusing to act')
 if not any(str(work/'target.qcow2').encode() in arg for arg in args):raise ValueError('VM does not use the private QA target disk')
 return pid

class Qmp:
 def __init__(self,path):self.path=path;self.connection=None;self.stream=None
 def __enter__(self):
  self.connection=socket.socket(socket.AF_UNIX);self.connection.settimeout(10);self.connection.connect(str(self.path));self.stream=self.connection.makefile('rwb');self.row();self.execute('qmp_capabilities');return self
 def __exit__(self,*args):
  if self.stream:self.stream.close()
  if self.connection:self.connection.close()
 def row(self):
  line=self.stream.readline(1048577)
  if not line or len(line)>1048576:raise OSError('Missing/oversized QMP response')
  return json.loads(line)
 def execute(self,command,arguments=None):
  ident=secrets.token_hex(8);self.stream.write((json.dumps({'execute':command,'arguments':arguments or {},'id':ident})+'\n').encode());self.stream.flush()
  while True:
   row=self.row()
   if row.get('id')==ident:
    if 'error' in row:raise RuntimeError(str(row['error']))
    return row.get('return')

def firmware_paths(cache=FIRMWARE_CACHE):
 roots=[Path('/usr/share/OVMF'),Path(cache)/'root/usr/share/OVMF']
 for root in roots:
  for suffix in ('_4M',''):
   code=root/('OVMF_CODE'+suffix+'.fd');variables=root/('OVMF_VARS'+suffix+'.fd')
   if code.is_file() and variables.is_file():return code,variables
 return None,None

def tools_status(args):
 code,variables=firmware_paths(args.firmware_cache)
 return {'tools':{name:shutil.which(name) for name in TOOLS},'kvm_available':os.access('/dev/kvm',os.R_OK|os.W_OK),'uefi_code':str(code) if code else None,'uefi_variables':str(variables) if variables else None,'pillow_available':importlib.util.find_spec('PIL') is not None,'host_changed':False}

def fetch_firmware(args):
 cache=safe_path(args.cache)
 if cache.exists() and (cache.stat().st_uid!=os.getuid() or cache.stat().st_mode&0o077):raise ValueError('Firmware cache must be private and owned by this user')
 cache.mkdir(parents=True,exist_ok=True,mode=0o700);cache.chmod(0o700)
 if not shutil.which('apt-get') or not shutil.which('dpkg-deb'):raise RuntimeError('Official Ubuntu package tools are required')
 run(['apt-get','download','ovmf'],cwd=cache)
 packages=sorted(cache.glob('ovmf_*.deb'),key=lambda p:p.stat().st_mtime)
 if not packages:raise RuntimeError('Official OVMF package was not downloaded')
 package=packages[-1];name=run(['dpkg-deb','-f',package,'Package'],capture_output=True,text=True).stdout.strip();assert name=='ovmf'
 run(['dpkg-deb','-x',package,cache/'root'])
 code,variables=firmware_paths(cache)
 if not code:raise RuntimeError('The downloaded OVMF package lacks compatible firmware')
 return {'package':str(package),'sha256':sha256(package),'code':str(code),'variables':str(variables),'host_packages_installed':False}

def disk_info(work):
 disk=work/'target.qcow2';info=disk.lstat()
 if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1:raise ValueError('Target must be an owned standalone regular qcow2 file')
 details=json.loads(run(['qemu-img','info','--output=json',disk],capture_output=True,text=True).stdout)
 if details.get('format')!='qcow2' or details.get('backing-filename') or details.get('full-backing-filename') or details.get('format-specific',{}).get('data',{}).get('data-file'):raise ValueError('Target must be standalone qcow2 without external backing/data files')
 return details

def command(work,state,boot='iso'):
 accel=state['acceleration'];disk=work/'target.qcow2';media=state.get('media','cdrom')
 if media not in ('cdrom','usb'):raise ValueError('Invalid QA media metadata')
 if accel not in ('kvm','tcg') or state.get('firmware') not in ('bios','uefi'):raise ValueError('Invalid VM acceleration/firmware metadata')
 args=['qemu-system-x86_64','-name',state['name'],'-machine','q35,accel='+accel,'-cpu','host' if accel=='kvm' else 'max','-smp','2','-m','4096','-device','virtio-vga','-display','none','-vnc','unix:'+str(work/'vnc.sock'),'-qmp','unix:'+str(work/'qmp.sock')+',server=on,wait=off','-serial','file:'+str(work/'serial.log'),'-monitor','none','-boot',('menu=on' if boot=='iso' and media=='usb' else 'order='+('d' if boot=='iso' else 'c')+',menu=on'),'-blockdev',json.dumps({'driver':'qcow2','node-name':'qa-target','file':{'driver':'file','filename':str(disk)},'backing':None},separators=(',',':')),'-device','virtio-blk-pci,drive=qa-target,serial=ABSTRACT_QA_DISK'+(',bootindex=2' if boot=='iso' and media=='usb' else ''),'-device','qemu-xhci','-device','usb-tablet','-netdev','user,id=qa-net','-device','virtio-net-pci,netdev=qa-net']
 if state.get('serial_transport')=='socket':
  serial_at=args.index('-serial');args[serial_at:serial_at+2]=['-chardev','socket,id=qa-serial,path='+str(work/'serial.sock')+',server=on,wait=off,logfile='+str(work/'serial.log'),'-serial','chardev:qa-serial']
 if boot=='iso':
  if media=='usb':args+=['-drive','file='+state['iso']+',if=none,id=install-media,format=raw,readonly=on','-device','usb-storage,drive=install-media,id=install-usb,removable=on,bootindex=1']
  else:args+=['-drive','file='+state['iso']+',if=none,id=install-media,media=cdrom,format=raw,readonly=on','-device','ide-cd,drive=install-media,id=install-cd']
 if state['firmware']=='uefi':
  code=safe_path(state['ovmf_code']);variables=owned_output(work/'OVMF_VARS.fd')
  if not code.is_file() or not variables.is_file():raise ValueError('UEFI firmware files are unavailable')
  args+=['-drive','if=pflash,format=raw,unit=0,readonly=on,file='+state['ovmf_code'],'-drive','if=pflash,format=raw,unit=1,file='+str(work/'OVMF_VARS.fd')]
 return args

def launch(work,state,boot='iso'):
 disk_info(work)
 if boot=='iso':
  iso=safe_path(state['iso'])
  if not iso.is_file() or sha256(iso)!=state['iso_sha256']:raise ValueError('ISO is missing or changed from its recorded SHA256')
 for filename in ('qmp.sock','vnc.sock',*(['serial.sock'] if state.get('serial_transport')=='socket' else [])):
  path=work/filename
  if path.exists():
   if not stat.S_ISSOCK(path.lstat().st_mode):raise ValueError('Unexpected file at QA socket path')
   path.unlink()
 owned_output(work/'serial.log')
 with owned_output(work/'qemu.log').open('ab') as log:
  process=subprocess.Popen(['nice','-n','10',*command(work,state,boot)],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
  state.update(pid=process.pid,boot=boot,boot_started=time.time());deadline=time.monotonic()+15
  while time.monotonic()<deadline:
   if process.poll() is not None:raise RuntimeError('QEMU failed; inspect '+str(work/'qemu.log'))
   if (work/'qmp.sock').is_socket():break
   time.sleep(.1)
  else:process.terminate();raise RuntimeError('QEMU did not create its private QMP socket')
 state['process_start']=(Path('/proc')/str(process.pid)/'stat').read_text().rsplit(')',1)[1].split()[19];private_json(work/'vm.json',state)
 with Qmp(work/'qmp.sock') as qmp:status=qmp.execute('query-status')
 return {'workdir':str(work),'pid':process.pid,'firmware':state['firmware'],'boot':boot,'acceleration':state['acceleration'],'media':state.get('media','cdrom'),'status':status,'guest_install_target':'/dev/vda (serial ABSTRACT_QA_DISK)','vcpu':2,'memory_mib':4096,'host_disks_attached':False,'guest_ssh_enabled':False,'vnc_socket':str(work/'vnc.sock')}

def start(args):
 for tool in TOOLS:
  if not shutil.which(tool):raise RuntimeError('Missing QA tool: '+tool)
 iso=safe_path(args.iso)
 if not iso.is_file() or iso.suffix.lower()!='.iso' or iso.stat().st_size<16*1024*1024:raise ValueError('Use a completed regular installer ISO file')
 checksum=sha256(iso)
 if args.sha256 and checksum!=args.sha256.lower():raise ValueError('ISO SHA256 mismatch')
 work=safe_path(args.workdir)
 if work.exists() and any(work.iterdir()):raise ValueError('Use a new empty private work directory')
 work.mkdir(mode=0o700,parents=True,exist_ok=True);work.chmod(0o700)
 if len(str(work/'qmp.sock').encode())>=100:raise ValueError('Work directory is too long for private Unix sockets')
 if not 16<=args.disk_gib<=64:raise ValueError('QA disk size must be16–64GiB')
 accel='kvm' if os.access('/dev/kvm',os.R_OK|os.W_OK) else 'tcg'
 if args.acceleration!='auto':accel=args.acceleration
 if accel=='kvm' and not os.access('/dev/kvm',os.R_OK|os.W_OK):raise ValueError('KVM access is unavailable')
 state={'kind':KIND,'name':'abstract-live-qa-'+secrets.token_hex(8),'workdir':str(work),'iso':str(iso),'iso_sha256':checksum,'firmware':args.firmware,'media':args.media,'acceleration':accel,'serial_transport':'socket','guest_target':'/dev/vda','target_serial':'ABSTRACT_QA_DISK','host_disks_attached':False}
 if args.firmware=='uefi':
  code,variables=firmware_paths(args.firmware_cache)
  if args.ovmf_code or args.ovmf_vars:
   if not args.ovmf_code or not args.ovmf_vars:raise ValueError('Pass both OVMF code and variables files')
   code,variables=safe_path(args.ovmf_code),safe_path(args.ovmf_vars)
  if not code or not code.is_file() or not variables.is_file():raise ValueError('UEFI firmware unavailable: use fetch-firmware or pass both OVMF files')
  state['ovmf_code']=str(code.resolve());shutil.copyfile(variables,work/'OVMF_VARS.fd');(work/'OVMF_VARS.fd').chmod(0o600)
 run(['qemu-img','create','-f','qcow2',work/'target.qcow2',str(args.disk_gib)+'G'],stdout=subprocess.DEVNULL)
 return launch(work,state)

def pixel_report(ppm):
 from PIL import Image
 with Image.open(ppm) as image:
  if image.width>8192 or image.height>8192 or image.width*image.height>16000000:raise ValueError('Display geometry exceeds QA bound')
  rgb=image.convert('RGB');rgb.thumbnail((160,100));samples=list(rgb.getdata());colors=len(set(samples));nonblack=sum(max(p)>8 for p in samples)/len(samples)
  return {'width':image.width,'height':image.height,'sampled_distinct_colors':colors,'nonblack_fraction':round(nonblack,4),'display_content_detected':colors>=8 and nonblack>=.005,'desktop_ready':False,'visual_acceptance':'Operator must inspect the screenshot; pixel content alone is not desktop or installer acceptance.'}

def screenshot(args,work,state,qmp):
 if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,70}',args.name) or args.name in ('.','..'):raise ValueError('Use a simple screenshot basename')
 ppm=owned_output(work/(args.name+'.ppm'));qmp.execute('screendump',{'filename':str(ppm)})
 result={'ppm':str(ppm),'boot_elapsed_seconds':round(time.time()-state['boot_started'],1),'firmware':state['firmware']}
 if importlib.util.find_spec('PIL') is not None:
  from PIL import Image
  result.update(pixel_report(ppm));png=owned_output(work/(args.name+'.png'))
  with Image.open(ppm) as image:image.save(png)
  result['png']=str(png);state['screen']={'width':result['width'],'height':result['height']};private_json(work/'vm.json',state)
 private_json(work/(args.name+'.json'),result)
 if args.require_content and not result.get('display_content_detected'):raise RuntimeError('Display is blank/cursor-only or Pillow is unavailable; inspect '+str(ppm))
 return result

PUNCT={' ':('spc',False),'-':('minus',False),'_':('minus',True),'=':('equal',False),'+':('equal',True),'.':('dot',False),'>':('dot',True),',':('comma',False),'<':('comma',True),'/':('slash',False),'?':('slash',True),'\\':('backslash',False),'|':('backslash',True),';':('semicolon',False),':':('semicolon',True),"'":('apostrophe',False),'"':('apostrophe',True),'[':('bracket_left',False),'{':('bracket_left',True),']':('bracket_right',False),'}':('bracket_right',True),'`':('grave_accent',False),'~':('grave_accent',True),'\n':('ret',False),'\t':('tab',False)}
for normal,shifted in zip('1234567890','!@#$%^&*()'):PUNCT[shifted]=(normal,True)
def send_key(qmp,keys):
 if not keys or not all(re.fullmatch(r'[a-z0-9_]+',key) for key in keys):raise ValueError('Use QEMU qcode names separated by hyphens')
 qmp.execute('send-key',{'keys':[{'type':'qcode','data':key} for key in keys],'hold-time':60})
def text_input(qmp,text,interval=.25):
 if not 1<=len(text)<=4096:raise ValueError('Text must contain1–4096characters')
 keys=[]
 for char in text:
  if char.isascii() and char.isalnum():key,shift=char.lower(),char.isupper()
  elif char in PUNCT:key,shift=PUNCT[char]
  else:raise ValueError('Text input supports printable ASCII, tab and newline only')
  keys.append((key,shift))
 for key,shift in keys:
  send_key(qmp,['shift',key] if shift else [key]);time.sleep(interval)
 return {'characters_sent':len(text),'text_logged':False}

def action(args):
 work,state=load(args.workdir)
 if args.action=='boot-disk':
  if owned_pid(work,state,allow_stopped=True) is not None:raise ValueError('Shut down the owned QA VM before booting its disk')
  return launch(work,state,'disk')
 if args.action=='status':
  pid=owned_pid(work,state,allow_stopped=True)
  if pid is None:return {'running':False,'firmware':state['firmware'],'workdir':str(work)}
 else:pid=owned_pid(work,state)
 if args.action=='serial':
  if state.get('serial_transport')!='socket':raise ValueError('This older QA VM uses a log-only serial device')
  endpoint=work/'serial.sock';info=endpoint.lstat()
  if not stat.S_ISSOCK(info.st_mode) or info.st_uid!=os.getuid():raise ValueError('Unsafe private serial socket')
  value=sys.stdin.read(4097) if args.stdin else (args.text or '')
  if len(value)>4096:raise ValueError('Private serial input exceeds4096characters')
  output=bytearray();deadline=time.monotonic()+args.wait_seconds
  with socket.socket(socket.AF_UNIX) as connection:
   connection.settimeout(2);connection.connect(str(endpoint))
   if value:connection.sendall(value.encode())
   while time.monotonic()<deadline and len(output)<32768:
    connection.settimeout(min(.2,max(.001,deadline-time.monotonic())))
    try:part=connection.recv(32768-len(output))
    except socket.timeout:continue
    if not part:break
    output.extend(part)
  return {'serial_output':output.decode('utf-8','replace'),'characters_sent':len(value),'private_socket':True}
 if args.action=='stop':
  try:
   with Qmp(work/'qmp.sock') as qmp:qmp.execute('system_powerdown')
  except (OSError,RuntimeError):pass
  deadline=time.monotonic()+args.grace_seconds
  while time.monotonic()<deadline:
   if owned_pid(work,state,allow_stopped=True) is None:return {'stopped':True,'graceful':True}
   time.sleep(.2)
  try:
   with Qmp(work/'qmp.sock') as qmp:qmp.execute('quit')
  except (OSError,RuntimeError):pass
  deadline=time.monotonic()+5
  while time.monotonic()<deadline:
   if owned_pid(work,state,allow_stopped=True) is None:return {'stopped':True,'graceful':False,'method':'owned-QMP-quit'}
   time.sleep(.1)
  owned_pid(work,state);os.killpg(pid,signal.SIGTERM);return {'stop_requested':True,'method':'owned-process-group-SIGTERM'}
 with Qmp(work/'qmp.sock') as qmp:
  if args.action=='status':return {'running':True,'firmware':state['firmware'],'qemu':qmp.execute('query-status'),'pid':pid,'workdir':str(work)}
  if args.action=='screenshot':return screenshot(args,work,state,qmp)
  if args.action=='key':send_key(qmp,args.keys.split('-'));return {'key_sent':True}
  if args.action=='text':
   value=sys.stdin.read(4097) if args.stdin else args.text
   return text_input(qmp,value+('\n' if args.enter else ''),args.interval_ms/1000)
  if args.action=='mouse':
   screen=state.get('screen',{});width=args.width or screen.get('width');height=args.height or screen.get('height')
   if not width or not height or not 0<=args.x<width or not 0<=args.y<height:raise ValueError('Capture a screenshot first or provide valid width/height and in-bounds coordinates')
   events=[{'type':'abs','data':{'axis':'x','value':round(args.x*32767/max(1,width-1))}},{'type':'abs','data':{'axis':'y','value':round(args.y*32767/max(1,height-1))}}]
   qmp.execute('input-send-event',{'events':events})
   if args.button:
    qmp.execute('input-send-event',{'events':[{'type':'btn','data':{'button':args.button,'down':True}}]});time.sleep(.08)
    qmp.execute('input-send-event',{'events':[{'type':'btn','data':{'button':args.button,'down':False}}]})
   return {'pointer_sent':True,'button':args.button}
  if args.action=='eject-iso':qmp.execute('eject',{'id':'install-usb' if state.get('media')=='usb' else 'install-cd','force':True});return {'iso_ejected':True}
  if args.action=='powerdown':qmp.execute('system_powerdown');return {'guest_powerdown_requested':True}
 raise ValueError('Unknown QA action')

def main():
 os.umask(0o077);parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
 p=sub.add_parser('check-tools');p.add_argument('--firmware-cache',type=Path,default=FIRMWARE_CACHE)
 p=sub.add_parser('fetch-firmware');p.add_argument('--cache',type=Path,default=FIRMWARE_CACHE)
 p=sub.add_parser('start');p.add_argument('--iso',type=Path,required=True);p.add_argument('--sha256');p.add_argument('--workdir',type=Path,required=True);p.add_argument('--firmware',choices=('bios','uefi'),default='bios');p.add_argument('--media',choices=('cdrom','usb'),default='cdrom',help='Virtual CD-ROM or read-only virtual USB storage; no host USB device is used');p.add_argument('--acceleration',choices=('auto','kvm','tcg'),default='auto');p.add_argument('--disk-gib',type=int,default=24);p.add_argument('--firmware-cache',type=Path,default=FIRMWARE_CACHE);p.add_argument('--ovmf-code',type=Path);p.add_argument('--ovmf-vars',type=Path)
 for name in ('status','screenshot','key','text','mouse','serial','eject-iso','powerdown','stop','boot-disk'):
  p=sub.add_parser(name);p.add_argument('--workdir',type=Path,required=True)
  if name=='screenshot':p.add_argument('--name',default='screen');p.add_argument('--require-content',action='store_true')
  if name=='key':p.add_argument('--keys',required=True)
  if name=='text':
   g=p.add_mutually_exclusive_group(required=True);g.add_argument('--text');g.add_argument('--stdin',action='store_true');p.add_argument('--enter',action='store_true',help='Submit a TTY command or completed field after typing; omitted for ordinary GUI text entry');p.add_argument('--interval-ms',type=int,choices=range(75,501),default=250,help='Conservative keyboard spacing for a loaded test VM')
  if name=='mouse':p.add_argument('--x',type=int,required=True);p.add_argument('--y',type=int,required=True);p.add_argument('--width',type=int);p.add_argument('--height',type=int);p.add_argument('--button',choices=('left','middle','right'))
  if name=='serial':
   g=p.add_mutually_exclusive_group();g.add_argument('--text');g.add_argument('--stdin',action='store_true');p.add_argument('--wait-seconds',type=int,choices=range(1,11),default=1,help='Bounded read from the private VM serial console; guest getty must be explicitly started during QA')
  if name=='stop':p.add_argument('--grace-seconds',type=int,choices=range(0,31),default=12)
 args=parser.parse_args()
 if args.action=='check-tools':result=tools_status(args)
 elif args.action=='fetch-firmware':result=fetch_firmware(args)
 elif args.action=='start':result=start(args)
 else:result=action(args)
 print(json.dumps(result,indent=2))
if __name__=='__main__':main()
