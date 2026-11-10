#!/usr/bin/env python3
"""Recovery after a forcibly killed supervisor; does not overwrite bindings the user changed."""
import json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from application_theme import restore_application_theme
restore_application_theme(ROOT)
from window_theme import restore_xfwm_theme
restore_xfwm_theme(ROOT)
for file in (ROOT/'data').glob('xfce-alt-tab-backup-*.json'):
    for key,value in json.loads(file.read_text()).items():
        current=subprocess.run(['xfconf-query','-c','xfce4-keyboard-shortcuts','-p',key],capture_output=True,text=True)
        if current.returncode!=0 or not current.stdout.strip():
            args=['xfconf-query','-c','xfce4-keyboard-shortcuts','-p',key,'-s',value]
            if current.returncode!=0:args+=['-n','-t','string']
            subprocess.run(args,check=True)
    file.unlink()
if subprocess.run(['pgrep','-u',str(os.getuid()),'-x','xfce4-panel'],stdout=subprocess.DEVNULL).returncode!=0:subprocess.Popen(['xfce4-panel','--disable-wm-check'],start_new_session=True)
print('Restored recorded XFCE shortcuts and panel')
