"""Validated Sway decoration commands; never change GTK/Qt application settings."""
import re
from project_paths import PROJECT_ROOT as ROOT

def generate_sway_theme(mode,accent,borderWidth=1,titlebar='normal',darkLevel='normal'):
    """Return one IPC command for new and existing server-decorated windows.

    ``normal`` includes a titlebar; ``pixel`` retains only the outline. App-drawn
    content and titlebars can require the application's own theme preferences.
    Values are strictly validated before interpolation into Sway's command parser.
    """
    if darkLevel not in ('normal','black'):raise ValueError('Invalid dark level')
    if mode not in ('dark','light'):raise ValueError('Invalid window theme mode')
    if not isinstance(accent,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',accent):raise ValueError('Invalid window accent')
    if type(borderWidth) is not int or not 0<=borderWidth<=4:raise ValueError('Window border width must be 0–4')
    if titlebar not in ('auto','normal','pixel'):raise ValueError('Invalid titlebar style')
    titlebar="normal" if titlebar=="auto" else titlebar
    accent=accent.lower()
    if mode=='light':
        background,text,inactive,muted,border,urgent='#f2f5f7','#15222d','#e2e8ed','#647582','#bac8d3','#a43d41'
    else:
        background,text,inactive,muted,border,urgent='#172329','#e1e8ed','#203037','#a2b0bb','#3d5058','#e99b91'
    if mode=='dark' and darkLevel=='black':background,text,inactive,muted,border='#101419','#e1e8ed','#0b0e12','#adb7c4','#38424d'
    # Retain accent identity with a subdued outline against Black surfaces.
    focused=accent
    if mode=='dark' and darkLevel=='black':
        focused='#'+''.join(f'{round(int(accent[i:i+2],16)*.4+base*.6):02x}' for i,base in zip((1,3,5),(16,20,25)))
    commands=[
        f'client.focused {focused} {background} {text} {focused} {focused}',
        f'client.focused_inactive {border} {inactive} {muted} {border} {border}',
        f'client.unfocused {border} {inactive} {muted} {border} {border}',
        f'client.urgent {urgent} {background} {text} {urgent} {urgent}',
        f'client.placeholder {border} {inactive} {muted} {border} {border}',
        f'client.background {background}',
        f'default_border {titlebar} {borderWidth}',
        f'default_floating_border {titlebar} {borderWidth}',
        f'[all] border {titlebar} {borderWidth}',
    ]
    return '; '.join(commands)

def apply_sway_theme(mode,accent,borderWidth=1,titlebar='normal',darkLevel='normal'):
    """Apply decoration commands, allowing an empty session's final criterion only."""
    from sway_events import request
    commands=generate_sway_theme(mode,accent,borderWidth,titlebar,darkLevel).split('; ')
    # Keep the criterion separate: Sway versions can return one result per
    # matched node, so response-count assumptions would reject valid sessions.
    configured=request(0,'; '.join(commands[:-1]))
    if not isinstance(configured,list) or not configured:raise ValueError('Unexpected compositor theme response')
    for item in configured:
        if not isinstance(item,dict) or not item.get('success'):raise ValueError('Compositor theme configuration failed')
    borders=request(0,commands[-1])
    if not isinstance(borders,list) or not borders:raise ValueError('Unexpected compositor border response')
    for item in borders:
        if not isinstance(item,dict):raise ValueError('Unexpected compositor border response')
        if item.get('success'):continue
        empty=(len(borders)==1 and item.get('error')=='No matching node.' and not item.get('parse_error',False))
        if not empty:raise ValueError('Compositor border failed: '+str(item.get('error','unknown error'))[:160])
    if titlebar=='auto':
        from decoration_policy import apply_auto_decorations
        apply_auto_decorations()
    return configured+borders

# Installed Mint palette families. Match hue first so a pastel accent does not
# accidentally select grey merely because its brightness is closer.
_MINT_COLORS={'':'#87a556','Aqua':'#1f9eab','Blue':'#3a74b8','Brown':'#a88663','Grey':'#808080','Orange':'#e89635','Pink':'#c96b95','Purple':'#9564b8','Red':'#c95b5b','Sand':'#c9ac72','Teal':'#35a497'}

def _installed_xfwm_themes():
    import os
    from pathlib import Path
    roots=[Path('/usr/share/themes'),Path('/usr/local/share/themes'),Path.home()/'.themes',Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share')))/'themes']
    return {p.parent.parent.name for root in roots if root.is_dir() for p in root.glob('*/xfwm4/themerc')}

def _xfwm_selection(mode,accent,current,names):
    import colorsys
    def hsv(color):return colorsys.rgb_to_hsv(*(int(color[i:i+2],16)/255 for i in (1,3,5)))
    hue,sat,value=hsv(accent);candidates=[]
    preferred='Mint-L' if current.startswith('Mint-L') else 'Mint-Y'
    for name in names:
        match=re.fullmatch(r'(Mint-[LY])(-Dark)?(?:-(Aqua|Blue|Brown|Grey|Orange|Pink|Purple|Red|Sand|Teal))?',name)
        if not match or bool(match[2])!=(mode=='dark'):continue
        suffix=match[3] or '';h,s,v=hsv(_MINT_COLORS[suffix])
        distance=(0 if suffix=='Grey' else 10) if sat<.08 else min(abs(h-hue),1-abs(h-hue))*4+abs(s-sat)*.15+abs(v-value)*.05+(2 if suffix=='Grey' else 0)
        candidates.append((match[1]!=preferred,distance,name))
    return min(candidates)[2] if candidates else None

def _xfwm_backup_path(root):
    import hashlib,os
    from pathlib import Path
    key=hashlib.sha256(os.environ.get('DISPLAY','').encode()).hexdigest()[:10]
    return (Path(os.environ['ORBIT_DATA']) if os.environ.get('ORBIT_DATA') and Path(root).resolve()==ROOT else Path(root)/'data')/('xfwm-theme-backup-'+key+'.json')

def _theme_name(value):return isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _().+-]{0,127}',value) is not None

def _read_xfwm_theme():
    import subprocess
    result=subprocess.run(['xfconf-query','-c','xfwm4','-p','/general/theme'],capture_output=True,text=True,timeout=3,check=False)
    value=result.stdout.rstrip('\n')
    return value if result.returncode==0 and _theme_name(value) else None

def _set_xfwm_theme(name):
    import subprocess
    if not _theme_name(name):return False
    return subprocess.run(['xfconf-query','-c','xfwm4','-p','/general/theme','-s',name],capture_output=True,text=True,timeout=3,check=False).returncode==0

def _load_xfwm_backup(path):
    import json
    if not path.exists():return None
    data=json.loads(path.read_text())
    if not isinstance(data,dict) or not _theme_name(data.get('original')) or not _theme_name(data.get('lastApplied')):raise ValueError('Invalid window-theme backup')
    return data

def _write_xfwm_backup(path,data):
    import json,os,tempfile
    path.parent.mkdir(parents=True,exist_ok=True)
    descriptor,temporary=tempfile.mkstemp(prefix='.xfwm-theme-',dir=path.parent)
    try:
        with os.fdopen(descriptor,'w') as handle:json.dump(data,handle);handle.flush();os.fsync(handle.fileno())
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)

def apply_xfwm_theme(root,mode,accent):
    """Match only XFWM frames; retain the original across native crashes/restarts."""
    import os,shutil,subprocess
    generate_sway_theme(mode,accent) # Share strict mode/color validation.
    if os.environ.get('SWAYSOCK') or not os.environ.get('DISPLAY') or not shutil.which('xfconf-query'):return False
    try:
        current=_read_xfwm_theme()
        if not current:return False
        selected=_xfwm_selection(mode,accent,current,_installed_xfwm_themes())
        if not selected:return False
        path=_xfwm_backup_path(root);previous=_load_xfwm_backup(path)
        if selected==current:return True
        # A manual theme change since our last application becomes the new
        # restoration target, rather than being silently discarded on exit.
        original=previous['original'] if previous and current==previous['lastApplied'] else current
        _write_xfwm_backup(path,dict(original=original,lastApplied=selected))
        try:changed=_set_xfwm_theme(selected)
        except (OSError,subprocess.SubprocessError):
            # A timed-out settings call may already have changed XFWM. Keep the
            # recovery record until the next read can establish what happened.
            return False
        if not changed:
            if previous:_write_xfwm_backup(path,previous)
            else:path.unlink(missing_ok=True)
        return changed
    except (OSError,ValueError,subprocess.SubprocessError):return False

def restore_xfwm_theme(root):
    """Restore only if the user has not independently changed the frame theme."""
    import os,shutil,subprocess
    if os.environ.get('SWAYSOCK') or not os.environ.get('DISPLAY') or not shutil.which('xfconf-query'):return False
    try:
        path=_xfwm_backup_path(root);backup=_load_xfwm_backup(path)
        if not backup:return False
        current=_read_xfwm_theme()
        if not current:return False # Keep backup if the settings service is temporarily absent.
        if current!=backup['lastApplied']:
            path.unlink();return False
        if not _set_xfwm_theme(backup['original']):return False
        path.unlink();return True
    except (OSError,ValueError,subprocess.SubprocessError):return False
