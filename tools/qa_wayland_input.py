"""Virtual input for isolated Orbit QA only; refuses physical-session environments.

Protocol definitions: swaywm/wlr-protocols wlr-virtual-pointer-unstable-v1
and swaywm/wlroots virtual-keyboard-unstable-v1. No production dependency.
"""
import os,socket,struct,time,ctypes
class VirtualPointer:
 def __init__(self,env):
  assert env.get('ORBIT_NESTED')=='1','QA pointer requires a private nested desktop'
  self.socket=socket.socket(socket.AF_UNIX);self.socket.settimeout(3);self.socket.connect(os.path.join(env['XDG_RUNTIME_DIR'],env['WAYLAND_DISPLAY']));self.nextid=6
  self.send(1,1,struct.pack('=I',2));self.send(1,0,struct.pack('=I',3));manager=None;globals={}
  while True:
   ident,opcode,data=self.receive()
   if ident==2 and opcode==0:
    name,length=struct.unpack('=II',data[:8]);interface=data[8:8+length-1].decode();version=struct.unpack('=I',data[8+((length+3)//4)*4:12+((length+3)//4)*4])[0]
    globals[interface]=(name,version)
    if interface=='zwlr_virtual_pointer_manager_v1':manager=name
   if ident==3:break
  if manager is None:raise RuntimeError('No private virtual-pointer manager')
  text=b'zwlr_virtual_pointer_manager_v1\0';arg=struct.pack('=II',manager,len(text))+text+b'\0'*((-len(text))%4)+struct.pack('=II',1,4)
  self.send(2,0,arg);self.send(4,0,struct.pack('=II',0,5));self.roundtrip()
  self.keyboard(globals)
 def bind(self,global_id,interface,ident):
  text=interface.encode()+b'\0';self.send(2,0,struct.pack('=II',global_id,len(text))+text+b'\0'*((-len(text))%4)+struct.pack('=II',1,ident))
 def keyboard(self,globals):
  if 'zwp_virtual_keyboard_manager_v1' not in globals:raise RuntimeError('No private keyboard manager')
  seat=self.nextid;manager=seat+1;keyboard=seat+2;self.nextid+=3;self.keyboard_id=keyboard
  self.bind(globals['wl_seat'][0],'wl_seat',seat);self.bind(globals['zwp_virtual_keyboard_manager_v1'][0],'zwp_virtual_keyboard_manager_v1',manager)
  self.send(manager,0,struct.pack('=II',seat,keyboard))
  lib=ctypes.CDLL('libxkbcommon.so.0')
  lib.xkb_context_new.argtypes=[ctypes.c_int];lib.xkb_context_new.restype=ctypes.c_void_p
  lib.xkb_keymap_new_from_names.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int];lib.xkb_keymap_new_from_names.restype=ctypes.c_void_p
  lib.xkb_keymap_get_as_string.argtypes=[ctypes.c_void_p,ctypes.c_int];lib.xkb_keymap_get_as_string.restype=ctypes.c_void_p
  lib.xkb_keymap_unref.argtypes=[ctypes.c_void_p];lib.xkb_context_unref.argtypes=[ctypes.c_void_p]
  context=lib.xkb_context_new(0);keymap=lib.xkb_keymap_new_from_names(context,None,0);string=lib.xkb_keymap_get_as_string(keymap,1);data=ctypes.string_at(string)+b'\0'
  libc=ctypes.CDLL(None);libc.free.argtypes=[ctypes.c_void_p];libc.free(string);lib.xkb_keymap_unref(keymap);lib.xkb_context_unref(context)
  fd=os.memfd_create('orbit-private-qa-keymap',os.MFD_CLOEXEC)
  try:
   os.write(fd,data);payload=struct.pack('=II',1,len(data));header=struct.pack('=II',keyboard,(16<<16))
   self.socket.sendmsg([header+payload],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,struct.pack('=i',fd))])
  finally:os.close(fd)
  self.roundtrip()
 def send(self,ident,opcode,data=b''):
  self.socket.sendall(struct.pack('=II',ident,((len(data)+8)<<16)|opcode)+data)
 def receive(self):
  def read(n):
   data=b''
   while len(data)<n:
    part=self.socket.recv(n-len(data))
    if not part:raise RuntimeError('Private Wayland connection closed')
    data+=part
   return data
  ident,word=struct.unpack('=II',read(8));size=word>>16
  if not 8<=size<=65536:raise RuntimeError('Invalid Wayland message')
  data=read(size-8)
  if ident==1 and word&65535==0:raise RuntimeError('Wayland QA protocol error: '+repr(data))
  return ident,word&65535,data
 def roundtrip(self):
  ident=self.nextid;self.nextid+=1;self.send(1,0,struct.pack('=I',ident))
  while self.receive()[0]!=ident:pass
 def move(self,x,y,width=1280,height=720):
  stamp=int(time.monotonic()*1000)&0xffffffff
  self.send(5,1,struct.pack('=IIIII',stamp,int(x),int(y),width,height));self.send(5,4);self.roundtrip()
 def click(self,x,y,width=1280,height=720,button=272):
  stamp=int(time.monotonic()*1000)&0xffffffff
  self.send(5,1,struct.pack('=IIIII',stamp,int(x),int(y),width,height));self.send(5,4);self.roundtrip();time.sleep(.08)
  self.send(5,2,struct.pack('=III',stamp,button,1));self.send(5,4);self.send(5,2,struct.pack('=III',stamp+1,button,0));self.send(5,4);self.roundtrip();time.sleep(.15)
 def close(self):
  try:self.send(self.keyboard_id,3);self.send(5,8);self.send(4,1);self.roundtrip()
  except OSError:pass
  self.socket.close()
