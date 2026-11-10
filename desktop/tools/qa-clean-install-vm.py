#!/usr/bin/env python3
"""Disposable Ubuntu24.04 VM acceptance. Never installs host packages or uses its seat."""
import argparse,hashlib,json,os,re,secrets,shlex,shutil,socket,stat,subprocess,sys,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OFFICIAL='https://cloud-images.ubuntu.com/minimal/releases/noble/release/'
IMAGE='ubuntu-24.04-minimal-cloudimg-amd64.img'
TOOLS=('qemu-system-x86_64','qemu-img','genisoimage','ssh','ssh-keygen','openssl','gpgv','dpkg-deb')

def digest(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as source:
  for block in iter(lambda:source.read(1024*1024),b''):h.update(block)
 return h.hexdigest()

def checksum_for(text,name=IMAGE):
 matches=[]
 for line in text.splitlines():
  row=line.split()
  if len(row)==2 and row[1].lstrip('*')==name and re.fullmatch('[a-fA-F0-9]{64}',row[0]):matches.append(row[0].lower())
 if len(matches)!=1:raise ValueError('Official checksum entry missing or ambiguous')
 return matches[0]

def verify_signature(sums,signature,keyring='/usr/share/keyrings/ubuntu-cloudimage-keyring.gpg'):
 if not shutil.which('gpgv') or not Path(keyring).is_file():raise RuntimeError('Official image verification needs gpgv and the Ubuntu cloud-image keyring')
 subprocess.run(['gpgv','--keyring',str(keyring),str(signature),str(sums)],check=True,stdout=subprocess.DEVNULL)

def fetch(cache):
 cache=Path(cache).resolve();cache.mkdir(parents=True,exist_ok=True)
 request=urllib.request.Request(OFFICIAL+'SHA256SUMS',headers={'User-Agent':'Mellipi-clean-install-QA/1'})
 with urllib.request.urlopen(request,timeout=45) as incoming:sums=incoming.read(1024*1024).decode()
 (cache/'SHA256SUMS').write_text(sums)
 with urllib.request.urlopen(OFFICIAL+'SHA256SUMS.gpg',timeout=45) as incoming:signature=incoming.read(1024*1024)
 (cache/'SHA256SUMS.gpg').write_bytes(signature)
 verify_signature(cache/'SHA256SUMS',cache/'SHA256SUMS.gpg')
 expected=checksum_for(sums);destination=cache/IMAGE
 if not destination.is_file() or digest(destination)!=expected:
  temporary=cache/(IMAGE+'.partial')
  try:
   with urllib.request.urlopen(OFFICIAL+IMAGE,timeout=60) as incoming,temporary.open('wb') as out:
    count=0
    while block:=incoming.read(1024*1024):
     count+=len(block)
     if count>2*1024**3:raise ValueError('Official cloud image exceeded2GiB bound')
     out.write(block)
   if digest(temporary)!=expected:raise ValueError('Official image SHA256 mismatch; image not accepted')
   os.replace(temporary,destination)
  finally:temporary.unlink(missing_ok=True)
 (cache/'SHA256SUMS').write_text(sums)
 return dict(image=str(destination),sha256=expected,source=OFFICIAL+IMAGE)

def run(args,**kwargs):return subprocess.run([str(x) for x in args],check=True,**kwargs)
def private_write(path,text):
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as target:target.write(text)

def tools_status():
 return dict(tools={name:shutil.which(name) for name in TOOLS},kvm=bool(os.access('/dev/kvm',os.R_OK|os.W_OK)),host_changed=False)

def vm_command(work,image,port,accel):
 work=Path(work)
 return ['qemu-system-x86_64','-name','Mellipi-clean-install-QA','-machine','q35,accel='+accel,'-cpu','host' if accel=='kvm' else 'max','-smp','2','-m','4096','-device','virtio-vga','-display','none','-vnc','unix:'+str(work/'vnc.sock'),'-qmp','unix:'+str(work/'qmp.sock')+',server=on,wait=off','-serial','file:'+str(work/'serial.log'),'-drive','file='+str(image)+',if=virtio,format=qcow2','-drive','file='+str(work/'seed.iso')+',if=virtio,format=raw,readonly=on','-smbios','type=1,serial=ds=nocloud','-netdev','user,id=net0,hostfwd=tcp:127.0.0.1:'+str(port)+'-:22','-device','virtio-net-pci,netdev=net0']

def check_display_pixels(path):
 """Reject cursor-only/black startup frames; this is not full visual acceptance."""
 data=Path(path).read_bytes()
 if len(data)>64*1024*1024:raise ValueError('VM screenshot exceeded bound')
 tokens=[];at=0
 while len(tokens)<4:
  while at<len(data) and data[at:at+1] in b' \t\r\n':at+=1
  if data[at:at+1]==b'#':
   at=data.index(b'\n',at)+1;continue
  end=at
  while end<len(data) and data[end:end+1] not in b' \t\r\n':end+=1
  if end==at:raise ValueError('Invalid VM screenshot header')
  tokens.append(data[at:end]);at=end
 if tokens[0]!=b'P6' or tokens[3]!=b'255':raise ValueError('Expected8-bit binary PPM screenshot')
 width,height=int(tokens[1]),int(tokens[2]);pixels=width*height
 if not 1<=width<=8192 or not 1<=height<=8192 or pixels>9000000:raise ValueError('VM screenshot geometry exceeded bound')
 at+=2 if data[at:at+2]==b'\r\n' else 1
 image=data[at:]
 if len(image)!=pixels*3:raise ValueError('VM screenshot length mismatch')
 stride=max(1,pixels//20000);samples=0;nonblack=0;colors=set()
 for pixel in range(0,pixels,stride):
  value=image[pixel*3:pixel*3+3];samples+=1
  if max(value)>8:nonblack+=1
  if len(colors)<4096:colors.add(value)
 result=dict(width=width,height=height,samples=samples,nonblack_fraction=nonblack/samples,distinct_colors=len(colors))
 if result['nonblack_fraction']<.005 or len(colors)<8:raise RuntimeError('VM startup display is blank/cursor-only: '+json.dumps(result))
 return result

def ssh_args(work,port):
 return ['ssh','-F','/dev/null','-i',str(Path(work)/'id_ed25519'),'-p',str(port),'-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','ConnectTimeout=5','-o','StrictHostKeyChecking=accept-new','-o','UserKnownHostsFile='+str(Path(work)/'known_hosts'),'abstract@127.0.0.1']

def ssh(work,port,command,**kwargs):return run([*ssh_args(work,port),command],**kwargs)

def validate_work(work):
 work=Path(work).resolve();info=work.stat()
 if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise ValueError('VM work directory must be private and owned by this user')
 state=json.loads((work/'vm.json').read_text())
 if state.get('kind')!='abstract-clean-install-vm':raise ValueError('Not an Mellipi QA VM directory')
 return work,state

class Qmp:
 def __init__(self,path):self.path=path;self.connection=None;self.stream=None
 def __enter__(self):
  self.connection=socket.socket(socket.AF_UNIX);self.connection.settimeout(8);self.connection.connect(str(self.path));self.stream=self.connection.makefile('rwb');self.row();self.execute('qmp_capabilities');return self
 def __exit__(self,*args):
  if self.stream:self.stream.close()
  if self.connection:self.connection.close()
 def row(self):
  line=self.stream.readline(1024*1024)
  if not line:raise OSError('QA VM QMP disconnected')
  return json.loads(line)
 def execute(self,command,arguments=None):
  ident=secrets.token_hex(4);self.stream.write((json.dumps(dict(execute=command,arguments=arguments or {},id=ident))+'\n').encode());self.stream.flush()
  while True:
   row=self.row()
   if row.get('id')==ident:
    if 'error' in row:raise RuntimeError(str(row['error']))
    return row.get('return')

def qmp_action(args):
 work,state=validate_work(args.workdir)
 with Qmp(work/'qmp.sock') as qmp:
  if args.action=='status':result=qmp.execute('query-status')
  elif args.action=='screenshot':
   path=work/'screen.ppm';qmp.execute('screendump',dict(filename=str(path)));result=dict(screenshot=str(path))
  elif args.action=='key':
   keys=args.keys.split('-')
   if not keys or not all(re.fullmatch('[a-z0-9_]+',key) for key in keys):raise ValueError('Use QEMU qcode names separated by hyphens')
   qmp.execute('send-key',{'keys':[dict(type='qcode',data=key) for key in keys],'hold-time':80});result=dict(sent=True)
  elif args.action=='password':
   secret=json.loads((work/'credentials.json').read_text())['password']
   if not re.fullmatch('[a-f0-9]{20}',secret):raise ValueError('Unexpected generated QA credential')
   for key in secret:qmp.execute('send-key',{'keys':[dict(type='qcode',data=key)],'hold-time':30});time.sleep(.06)
   qmp.execute('send-key',{'keys':[dict(type='qcode',data='ret')],'hold-time':80});result=dict(typed_generated_vm_password=True)
  else:result=qmp.execute('system_powerdown')
 print(json.dumps(result))

def boot(args):
 status=tools_status();missing=[k for k,v in status['tools'].items() if not v]
 if missing:raise RuntimeError('Missing host tools (not installed by harness): '+', '.join(missing))
 image=Path(args.image).resolve()
 if not re.fullmatch('[a-fA-F0-9]{64}',args.sha256) or digest(image)!=args.sha256.lower():raise ValueError('Cloud image checksum mismatch')
 sums=Path(args.sha256sums) if args.sha256sums else image.parent/'SHA256SUMS'
 signature=Path(args.signature) if args.signature else image.parent/'SHA256SUMS.gpg'
 verify_signature(sums,signature,args.keyring)
 if checksum_for(sums.read_text(),image.name)!=args.sha256.lower():raise ValueError('Image checksum does not match signed official manifest')
 packages=[Path(p).resolve() for p in args.package]
 if not packages or not all(p.is_file() and p.suffix=='.deb' for p in packages):raise ValueError('Pass existing .deb packages')
 names=[subprocess.check_output(['dpkg-deb','-f',str(p),'Package'],text=True).strip() for p in packages]
 if 'abstract-shell' not in names:raise ValueError('abstract-shell package is required')
 if args.profile=='full' and 'abstract-desktop' not in names:raise ValueError('Full profile requires abstract-desktop metapackage')
 work=Path(args.workdir).resolve()
 if ',' in str(work) or any(ord(c)<32 for c in str(work)):raise ValueError('VM work path cannot contain QEMU option separators or controls')
 if work.exists() and any(work.iterdir()):raise ValueError('Use a new empty work directory for every clean case')
 work.mkdir(mode=0o700,parents=True,exist_ok=True);work.chmod(0o700)
 if len(str(work/'qmp.sock').encode())>=104:raise ValueError('Use a shorter VM work directory (Unix socket limit)')
 run(['ssh-keygen','-q','-t','ed25519','-N','','-f',work/'id_ed25519'])
 password=secrets.token_hex(10);password_hash=subprocess.check_output(['openssl','passwd','-6','-stdin'],input=password+'\n',text=True).strip()
 key=(work/'id_ed25519.pub').read_text().strip()
 userdata='#cloud-config\n'+json.dumps(dict(hostname='abstract-qa',manage_etc_hosts=True,users=[dict(name='abstract',groups=['sudo'],shell='/bin/bash',sudo='ALL=(ALL) NOPASSWD:ALL',lock_passwd=False,passwd=password_hash,ssh_authorized_keys=[key])],ssh_pwauth=False,disable_root=True,package_update=False,write_files=[dict(path='/etc/motd',content='Disposable Mellipi QA VM; no host desktop changes.\n')]))+'\n'
 private_write(work/'user-data',userdata);private_write(work/'meta-data','instance-id: abstract-qa-'+secrets.token_hex(8)+'\nlocal-hostname: abstract-qa\n');private_write(work/'credentials.json',json.dumps(dict(user='abstract',password=password))+'\n')
 run(['genisoimage','-quiet','-output',work/'seed.iso','-volid','cidata','-joliet','-rock',work/'user-data',work/'meta-data'])
 fmt=json.loads(subprocess.check_output(['qemu-img','info','--output=json',str(image)],text=True))['format']
 if fmt not in ('qcow2','raw'):raise ValueError('Unsupported base image format')
 overlay=work/'disk.qcow2';run(['qemu-img','create','-q','-f','qcow2','-F',fmt,'-b',image,overlay,'24G'])
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 accel='kvm' if status['kvm'] else 'tcg'
 state=dict(kind='abstract-clean-install-vm',ssh_port=port,profile=args.profile,no_install_recommends=args.no_install_recommends,image_sha256=args.sha256.lower(),packages=[dict(name=n,path=str(p),sha256=digest(p)) for n,p in zip(names,packages)],accel=accel)
 private_write(work/'vm.json',json.dumps(state,indent=2)+'\n')
 with (work/'qemu.log').open('wb') as log:process=subprocess.Popen(vm_command(work,overlay,port,accel),stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
 state['pid']=process.pid;(work/'vm.json').write_text(json.dumps(state,indent=2)+'\n')
 report=dict(profile=args.profile,no_install_recommends=args.no_install_recommends,base_image_verified=True,official_manifest_signature_verified=True,host_desktop_changed=False,graphical_login='not tested',lock_unlock='not tested',accessibility='not tested',lifecycle='not tested')
 try:
  deadline=time.monotonic()+args.boot_timeout
  while True:
   if process.poll() is not None:raise RuntimeError('QA VM exited: '+(work/'qemu.log').read_text()[-2000:])
   try:ready=subprocess.run([*ssh_args(work,port),'cloud-init status --wait >/dev/null'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)
   except subprocess.TimeoutExpired:
    if time.monotonic()>deadline:raise RuntimeError('Cloud-init timeout; inspect owned serial.log')
    continue
   if ready.returncode==0:break
   if time.monotonic()>deadline:raise RuntimeError('QA VM SSH/cloud-init timeout; inspect serial.log')
   time.sleep(2)
  report['fresh_cloud_boot']=True
  ssh(work,port,'mkdir -p /home/abstract/packages')
  for index,package in enumerate(packages):
   ssh(work,port,'cat > /home/abstract/packages/'+str(index)+'.deb',input=package.read_bytes(),stdout=subprocess.DEVNULL)
  probe=ROOT/'tools/qa-clean-install-guest.py';ssh(work,port,'cat > /home/abstract/qa-guest.py',input=probe.read_bytes(),stdout=subprocess.DEVNULL)
  flags=' --no-install-recommends' if args.no_install_recommends else ''
  with (work/'install.log').open('wb') as log:
   ssh(work,port,'sudo apt-get update && sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y'+flags+' /home/abstract/packages/*.deb',stdout=log,stderr=subprocess.STDOUT,timeout=args.install_timeout)
  report['package_install']=True
  try:baseline=ssh(work,port,'python3 /home/abstract/qa-guest.py baseline',capture_output=True,text=True,timeout=40)
  except subprocess.CalledProcessError as error:
   (work/'baseline.log').write_text((error.stdout or '')+(error.stderr or ''))
   raise RuntimeError('Guest baseline failed; inspect '+str(work/'baseline.log')) from error
  (work/'baseline.log').write_text(baseline.stdout+baseline.stderr)
  report['baseline']=json.loads(baseline.stdout)
  if args.start_desktop:
   ssh(work,port,"sudo python3 /home/abstract/qa-guest.py start-tty",capture_output=True,text=True,timeout=20)
   deadline=time.monotonic()+90
   while True:
    result=subprocess.run([*ssh_args(work,port),'python3 /home/abstract/qa-guest.py session'],capture_output=True,text=True,timeout=15)
    if result.returncode==0:report['session']=json.loads(result.stdout);report['graphical_login']='passed: VM tty1 PAM login and native compositor';break
    if time.monotonic()>deadline:raise RuntimeError('VM graphical session did not become ready: '+result.stderr[-2000:])
    time.sleep(2)
   time.sleep(2)
   screenshot=work/'startup.ppm'
   with Qmp(work/'qmp.sock') as qmp:qmp.execute('screendump',dict(filename=str(screenshot)))
   report['display_pixels']=check_display_pixels(screenshot)
  print(json.dumps(report,indent=2))
 except Exception as error:
  report['failure']=str(error)[:2000]
  raise
 finally:
  (work/'report.json').write_text(json.dumps(report,indent=2)+'\n')
  if not args.keep_running:
   if process.poll() is None:
    try:
     with Qmp(work/'qmp.sock') as qmp:qmp.execute('quit')
    except (OSError,RuntimeError):process.terminate()
    try:process.wait(timeout=8)
    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
  else:print('Owned QA VM retained; use qmp subcommand and credentials.json privately.',file=sys.stderr)

def main():
 parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
 sub.add_parser('check-tools')
 download=sub.add_parser('fetch-image');download.add_argument('--cache-dir',type=Path,required=True)
 vm=sub.add_parser('run');vm.add_argument('--image',type=Path,required=True);vm.add_argument('--sha256',required=True);vm.add_argument('--sha256sums',type=Path);vm.add_argument('--signature',type=Path);vm.add_argument('--keyring',type=Path,default=Path('/usr/share/keyrings/ubuntu-cloudimage-keyring.gpg'));vm.add_argument('--workdir',type=Path,required=True);vm.add_argument('--package',type=Path,action='append',required=True);vm.add_argument('--profile',choices=('core','full'),default='core');vm.add_argument('--no-install-recommends',action='store_true');vm.add_argument('--start-desktop',action='store_true');vm.add_argument('--keep-running',action='store_true');vm.add_argument('--boot-timeout',type=int,default=600);vm.add_argument('--install-timeout',type=int,default=1200)
 qmp=sub.add_parser('qmp');qmp.add_argument('--workdir',type=Path,required=True);qmp.add_argument('action',choices=('status','screenshot','key','password','powerdown'));qmp.add_argument('--keys',default='ret')
 args=parser.parse_args()
 if args.command=='check-tools':print(json.dumps(tools_status(),indent=2))
 elif args.command=='fetch-image':print(json.dumps(fetch(args.cache_dir),indent=2))
 elif args.command=='qmp':qmp_action(args)
 else:boot(args)
if __name__=='__main__':main()
