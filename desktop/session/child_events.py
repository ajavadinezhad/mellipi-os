"""Wake a standalone session owner on child exit, without a polling timer."""
import os,selectors,signal,threading

class ChildEvents:
    def __init__(self):self.read=None;self.write=None;self.selector=None;self.previous_fd=None;self.previous_handler=None;self.lock=threading.RLock()
    def __enter__(self):
        self.read,self.write=os.pipe2(os.O_NONBLOCK|os.O_CLOEXEC)
        self.selector=selectors.DefaultSelector();self.selector.register(self.read,selectors.EVENT_READ)
        try:
            self.previous_handler=signal.getsignal(signal.SIGCHLD)
            self.previous_fd=signal.set_wakeup_fd(self.write,warn_on_full_buffer=False)
            signal.signal(signal.SIGCHLD,lambda *_:None)
        except BaseException:
            self.__exit__(None,None,None);raise
        return self
    def wake(self):
        with self.lock:
            if self.write is not None:
                try:os.write(self.write,b'\0')
                except OSError:pass # A full pipe is already readable.
    def wait(self,timeout=None):
        ready=bool(self.selector.select(timeout))
        if ready:
            while True:
                try:
                    if not os.read(self.read,4096):break
                except BlockingIOError:break
        return ready
    def __exit__(self,*_):
        if self.previous_fd is not None:signal.set_wakeup_fd(self.previous_fd)
        if self.previous_handler is not None:signal.signal(signal.SIGCHLD,self.previous_handler)
        if self.selector is not None:self.selector.close()
        with self.lock:
            descriptors=(self.read,self.write);self.read=self.write=None
            for fd in descriptors:
                if fd is not None:os.close(fd)

def reap_children(children,lock):
    """Poll only owned children after an exit event; retain live processes."""
    with lock:owned=list(children)
    count=0
    for child in owned:
        # Popen's wait lock safely coexists with shell/portal supervisor waiters.
        if child.poll() is not None:
            with lock:
                if child in children:children.remove(child);count+=1
    return count
