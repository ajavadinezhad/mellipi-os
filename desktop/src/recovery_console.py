"""Plain recovery shell independent of user shell startup files and Wayland."""
import ctypes,os,pwd

def focus_terminal():
    """No window manager runs here; focus Xterm's own supplied window once."""
    try:
        ident=int(os.environ.get('WINDOWID','0'),0)
        if not 0<ident<2**32 or not os.environ.get('DISPLAY'):return
        x=ctypes.CDLL('libX11.so.6');x.XOpenDisplay.argtypes=[ctypes.c_char_p];x.XOpenDisplay.restype=ctypes.c_void_p
        display=x.XOpenDisplay(None)
        if not display:return
        x.XSetInputFocus.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong]
        x.XSync.argtypes=[ctypes.c_void_p,ctypes.c_int];x.XCloseDisplay.argtypes=[ctypes.c_void_p]
        handler_type=ctypes.CFUNCTYPE(ctypes.c_int,ctypes.c_void_p,ctypes.c_void_p)
        handler=handler_type(lambda *_:0)
        x.XSetErrorHandler.argtypes=[ctypes.c_void_p];x.XSetErrorHandler.restype=ctypes.c_void_p
        previous=x.XSetErrorHandler(ctypes.cast(handler,ctypes.c_void_p))
        try:x.XSetInputFocus(display,ident,1,0);x.XSync(display,False)
        finally:x.XSetErrorHandler(previous);x.XCloseDisplay(display)
    except (OSError,ValueError,AttributeError):pass # Clicking the terminal remains a fallback.

def main():
    if os.geteuid()==0:raise SystemExit('Use the normal sign-in screen for Recovery.')
    focus_terminal()
    print('\nMellipi Recovery\n\nThis terminal works without the Mellipi compositor or panels.\n\n  mellipi-recover    Show your saved working-version recovery command\n  exit              Return to the sign-in screen\n\nUse sudo only for the repair you choose. This recovery terminal does not lock;\nsign out before leaving it unattended.\n',flush=True)
    home=pwd.getpwuid(os.getuid()).pw_dir
    try:os.chdir(home if os.path.isdir(home) else '/')
    except OSError:
        # Broken ownership/mount permissions are a reason to use Recovery.
        # Keep the authenticated HOME for repair tools, but start at usable /.
        os.chdir('/')
    env=dict(os.environ,HOME=home,PS1='recovery \\u@\\h:\\w\\$ ',INPUTRC='/dev/null',HISTFILE='/dev/null')
    for key in list(env):
        if key.startswith('BASH_FUNC_') or key in ('BASH_ENV','ENV','SHELLOPTS','BASHOPTS','PROMPT_COMMAND'):env.pop(key,None)
    os.execve('/bin/bash',['/bin/bash','--noprofile','--norc','-i'],env)

if __name__=='__main__':main()
