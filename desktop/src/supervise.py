"""Keep the original XFCE panel available after clean exits or shell crashes."""
import os, signal, subprocess, sys
from pathlib import Path
import fcntl,hashlib,json
# Never run XFCE replacement/recovery against an inherited Wayland session.
if os.environ.get('ORBIT_NATIVE_CONTROL') or os.environ.get('WAYLAND_DISPLAY') or os.environ.get('SWAYSOCK'):
    sys.exit('The X11 preview supervisor cannot run inside a Wayland session')
from project_paths import PROJECT_ROOT as ROOT, SOURCE_ROOT
(ROOT/'data').mkdir(exist_ok=True)
session_key=hashlib.sha256((os.environ.get('WAYLAND_DISPLAY') or os.environ.get('DISPLAY','offscreen')).encode()).hexdigest()[:10]
handle=open(ROOT/f'data/supervisor-{session_key}.lock','w')
try: fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError: sys.exit('Orbit is already running; use Ctrl Alt Space.')
replace='--keep-panels' not in sys.argv and '--smoke-test' not in sys.argv
args=[a for a in sys.argv[1:] if a!='--keep-panels']
panel_was_running=False
shortcut_backup={}
backup_path=ROOT/f'data/xfce-alt-tab-backup-{session_key}.json'
child=None

def stop(*_):
    if child and child.poll() is None: child.terminate()
signal.signal(signal.SIGTERM,stop); signal.signal(signal.SIGINT,stop)
try:
    if replace and not os.environ.get('SWAYSOCK') and os.environ.get('DISPLAY'):
        panel_was_running=subprocess.run(['pgrep','-u',str(os.getuid()),'-x','xfce4-panel'],stdout=subprocess.DEVNULL).returncode==0
        if panel_was_running: subprocess.run(['xfce4-panel','--quit'],timeout=8,check=False)
    if replace and not os.environ.get('SWAYSOCK'):
        previous_backup=json.loads(backup_path.read_text()) if backup_path.exists() else {}
        for key in ('/xfwm4/custom/<Alt>Tab','/xfwm4/custom/<Alt><Shift>Tab','/commands/custom/Print'):
            old=subprocess.run(['xfconf-query','-c','xfce4-keyboard-shortcuts','-p',key],capture_output=True,text=True)
            if old.returncode==0:
                shortcut_backup[key]=old.stdout.rstrip('\n')
                if not shortcut_backup[key]:shortcut_backup[key]=previous_backup.get(key,'')
                backup_path.write_text(json.dumps({**previous_backup,**shortcut_backup}))
                subprocess.run(['xfconf-query','-c','xfce4-keyboard-shortcuts','-p',key,'-r'],check=False)
    child=subprocess.Popen([sys.executable,str(SOURCE_ROOT/'native_app.py'),*args])
    result=child.wait()
finally:
    from application_theme import restore_application_theme
    restore_application_theme(ROOT)
    if not os.environ.get('SWAYSOCK'):
        from window_theme import restore_xfwm_theme
        restore_xfwm_theme(ROOT)
    restored=True
    for key,value in shortcut_backup.items():
        current=subprocess.run(['xfconf-query','-c','xfce4-keyboard-shortcuts','-p',key],capture_output=True,text=True)
        if current.returncode!=0 or not current.stdout.strip():
            args=['xfconf-query','-c','xfce4-keyboard-shortcuts','-p',key,'-s',value]
            if current.returncode!=0:args+=['-n','-t','string']
            outcome=subprocess.run(args,check=False);restored=restored and outcome.returncode==0
    if restored and backup_path.exists():backup_path.unlink()
    if panel_was_running:
        if subprocess.run(['pgrep','-u',str(os.getuid()),'-x','xfce4-panel'],stdout=subprocess.DEVNULL).returncode!=0:
            subprocess.Popen(['xfce4-panel','--disable-wm-check'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
sys.exit(result)
