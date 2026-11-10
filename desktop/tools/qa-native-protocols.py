#!/usr/bin/env python3
"""Destructive lock protocol checks for a DISPOSABLE private Orbit compositor.

Does not launch a compositor, alter login services, or connect to physical Sway.
Caller must create a private native instance and terminate it after this test:
the last check deliberately disconnects the locker, leaving that instance locked.
"""
import argparse, os, socket, struct
from pathlib import Path

class Client:
    def __init__(self, env):
        self.sock=socket.socket(socket.AF_UNIX); self.sock.settimeout(15)
        self.sock.connect(os.path.join(env['XDG_RUNTIME_DIR'],env['WAYLAND_DISPLAY']))
        self.next=4; self.globals={}; self.events=[]
        self.send(1,1,struct.pack('=I',2)); self.send(1,0,struct.pack('=I',3))
        while True:
            ident,op,data=self.recv()
            if ident==2 and op==0:
                name,length=struct.unpack('=II',data[:8]); interface=data[8:8+length-1].decode()
                version=struct.unpack_from('=I',data,8+(length+3)//4*4)[0]
                self.globals[interface]=(name,version)
            if ident==3: break
    def alloc(self):
        ident=self.next; self.next+=1; return ident
    def send(self,ident,op,data=b''):
        self.sock.sendall(struct.pack('=II',ident,((len(data)+8)<<16)|op)+data)
    def recv(self):
        def read(n):
            result=b''
            while len(result)<n:
                part=self.sock.recv(n-len(result))
                if not part: raise EOFError('Wayland client disconnected')
                result+=part
            return result
        ident,word=struct.unpack('=II',read(8)); size=word>>16
        if not 8<=size<=65536: raise AssertionError('Malformed protocol event')
        return ident,word&65535,read(size-8)
    def bind(self,interface,version=1):
        name,advertised=self.globals[interface]; ident=self.alloc(); text=interface.encode()+b'\0'
        self.send(2,0,struct.pack('=II',name,len(text))+text+b'\0'*(-len(text)%4)+struct.pack('=II',min(version,advertised),ident))
        return ident
    def event(self,target,opcode):
        while True:
            event=self.recv(); self.events.append(event)
            if event[0]==1 and event[1]==0: raise AssertionError('Unexpected protocol error '+repr(event))
            if event[:2]==(target,opcode): return event[2]
    def lock(self):
        manager=self.bind('ext_session_lock_manager_v1'); lock=self.alloc(); self.send(manager,1,struct.pack('=I',lock)); return lock
    def capture_failed(self):
        manager=self.bind('zwlr_screencopy_manager_v1',3); output=self.bind('wl_output'); frame=self.alloc()
        self.send(manager,0,struct.pack('=III',frame,0,output)); self.event(frame,3)
    def close(self): self.sock.close()

def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--disposable-private-lock',action='store_true',required=True); parser.add_argument('--native-pid',type=int,required=True); args=parser.parse_args()
    env=os.environ.copy()
    if env.get('ORBIT_NESTED')!='1': raise SystemExit('Refusing: ORBIT_NESTED=1 private native instance required')
    if env.get('SWAYSOCK'): raise SystemExit('Refusing: clear SWAYSOCK; target the disposable native socket only')
    process=Path('/proc')/str(args.native_pid)
    if Path(os.readlink(process/'exe')).name!='orbit-compositor': raise SystemExit('Refusing: target PID is not Orbit native')
    target=os.path.join(env['XDG_RUNTIME_DIR'],env['WAYLAND_DISPLAY'])
    inodes={line.split()[6] for line in Path('/proc/net/unix').read_text().splitlines()[1:] if len(line.split())>=8 and line.split()[7]==target}
    owned={os.readlink(fd) for fd in (process/'fd').iterdir()}
    if not any('socket:['+inode+']' in owned for inode in inodes): raise SystemExit('Refusing: native PID does not own target Wayland socket')
    if env.get('ORBIT_NATIVE_QA_LOCK')!='1': raise SystemExit('Refusing: private synthetic-presentation QA mode required')
    owner=Client(env); lock=owner.lock(); owner.event(lock,0); print('PASS locked ownership after PRIVATE synthetic presentation (not hardware certification)',flush=True)
    other=Client(env); rejected=other.lock(); other.event(rejected,1)
    other.send(rejected,2) # unlock_and_destroy on an unaccepted object must be a protocol error.
    while True:
        event=other.recv()
        if event[:2]==(1,0): break
    other.close(); probe=Client(env); probe.capture_failed(); probe.close(); print('PASS rejected owner cannot unlock or capture',flush=True)
    owner.send(lock,2); callback=owner.alloc(); owner.send(1,0,struct.pack('=I',callback)); owner.event(callback,0)
    lock=owner.lock(); owner.event(lock,0); owner.close()
    probe=Client(env); probe.capture_failed(); probe.close(); print('PASS locker disconnect remains fail-closed; dispose private compositor now',flush=True)

if __name__=='__main__': main()
