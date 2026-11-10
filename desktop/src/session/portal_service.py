"""A small session-owned portal compatibility backend with bounded recovery."""
import os,time
from pathlib import Path

def backend_command(root):
    binary=Path(root)/'.portal-runtime/xdg-desktop-portal-wlr'
    return [str(binary)] if binary.is_file() and os.access(binary,os.X_OK) else None

def supervise(command,environment,launch,release,stopping,delays=(0,.5,2,8)):
    """No idle poll: wait on the owned backend; never end the desktop on failure."""
    for delay in delays:
        if stopping.wait(delay):return
        child=None
        try:
            child=launch(command,environment=environment)
            if child is None:return
            code=child.wait()
        except OSError as error:
            print('Abstract portal backend unavailable: '+str(error),flush=True);code=1
        finally:
            if child is not None:release(child)
        if stopping.is_set() or code==0:return
    print('Abstract portal backend stopped after repeated failures; desktop apps remain running',flush=True)
