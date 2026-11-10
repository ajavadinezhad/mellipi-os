"""Exec the idle timer with a parent-death signal; no persistent helper process."""
import ctypes,os,signal,sys

def bind_parent(expected_parent,get_parent=os.getppid,prctl=None):
    if type(expected_parent) is not int or expected_parent<=1:raise ValueError('Invalid idle policy parent')
    if get_parent()!=expected_parent:return False
    if prctl is None:
        if not sys.platform.startswith('linux'):raise RuntimeError('Safe idle timer lifetime requires Linux')
        libc=ctypes.CDLL(None,use_errno=True)
        prctl=libc.prctl;prctl.argtypes=[ctypes.c_int,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_ulong];prctl.restype=ctypes.c_int
    if prctl(1,signal.SIGTERM,0,0,0)!=0:
        code=ctypes.get_errno();raise OSError(code,os.strerror(code))
    # The parent can die between the first check and configuring PDEATHSIG.
    return get_parent()==expected_parent

def main():
    ready=None
    try:
        if len(sys.argv)<3:raise ValueError('Expected parent PID and idle command')
        args=sys.argv[2:]
        if len(args)>=3 and args[0]=='--ready-fd':
            ready=int(args[1]);os.set_inheritable(ready,False);args=args[2:]
        if not bind_parent(int(sys.argv[1])):return 0
        os.execvp(args[0],args)
    except (OSError,ValueError,RuntimeError) as error:
        message='Idle policy: '+str(error)
        if ready is not None:
            try:os.write(ready,message.encode('utf-8','replace')[:1024])
            except OSError:pass
        print(message,file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
