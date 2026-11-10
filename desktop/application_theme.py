"""Reversible toolkit appearance sync; no icons, fonts or app-specific config edits."""
import ast,hashlib,json,os,shutil,subprocess
from pathlib import Path
from window_theme import _xfwm_selection,_theme_name,_write_xfwm_backup
SCHEMA='org.gnome.desktop.interface'
KEYS=('xsettings','gtk-theme','color-scheme','cursor-theme')

def _validate(mode,accent):
    import re
    if mode not in ('dark','light') or not isinstance(accent,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',accent):raise ValueError('Invalid application appearance')

def _available():
    # Settings backends are user-wide even with a private nested D-Bus session.
    return not os.environ.get('ORBIT_NESTED') and bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))

def _backup_path(root):
    identity='\0'.join(os.environ.get(k,'') for k in ('DISPLAY','WAYLAND_DISPLAY','XDG_SESSION_ID','DBUS_SESSION_BUS_ADDRESS'))
    return (Path(os.environ['ORBIT_DATA']) if os.environ.get('ORBIT_DATA') and Path(root).resolve()==Path(__file__).resolve().parent else Path(root)/'data')/('application-theme-backup-'+hashlib.sha256(identity.encode()).hexdigest()[:12]+'.json')

def _run(args):return subprocess.run(args,capture_output=True,text=True,timeout=3,check=False)

def _read(key):
    if key=='xsettings':
        if not shutil.which('xfconf-query'):return None
        result=_run(['xfconf-query','-c','xsettings','-p','/Net/ThemeName'])
        value=result.stdout.rstrip('\n')
    else:
        if not shutil.which('gsettings'):return None
        result=_run(['gsettings','get',SCHEMA,key])
        if result.returncode:return None
        try:value=ast.literal_eval(result.stdout.strip())
        except (ValueError,SyntaxError):return None
    return value if result.returncode==0 and _valid_value(key,value) else None

def _valid_value(key,value):
    return value in ('default','prefer-dark','prefer-light') if key=='color-scheme' else _theme_name(value)

def _write(key,value):
    if key not in KEYS or not _valid_value(key,value):raise ValueError('Invalid toolkit setting')
    if key=='xsettings':args=['xfconf-query','-c','xsettings','-p','/Net/ThemeName','-s',value]
    else:args=['gsettings','set',SCHEMA,key,json.dumps(value)]
    return _run(args).returncode==0

def _installed_gtk_themes():
    roots=[Path('/usr/share/themes'),Path('/usr/local/share/themes'),Path.home()/'.themes',Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share')))/'themes']
    return {p.parent.parent.name for root in roots if root.is_dir() for pattern in ('*/gtk-3.0/gtk.css','*/gtk-4.0/gtk.css') for p in root.glob(pattern)}

def _load(path):
    if not path.exists():return {}
    data=json.loads(path.read_text())
    if not isinstance(data,dict) or set(data)-set(KEYS):raise ValueError('Invalid application theme recovery data')
    for key,entry in data.items():
        if not isinstance(entry,dict) or set(entry)!={'original','lastApplied'} or not all(_valid_value(key,v) for v in entry.values()):raise ValueError('Invalid application theme recovery value')
    return data

def _save(path,records):
    if records:_write_xfwm_backup(path,records)
    else:path.unlink(missing_ok=True)

def apply_application_theme(root,mode,accent):
    """Update supported live GTK/XSettings and GNOME color preference channels.

    Journal each original value before its mutation. Missing schemas/services are
    skipped; nested desktops cannot change the physical session's preferences.
    """
    _validate(mode,accent)
    if not _available():return False
    path=_backup_path(root)
    try:
        records=_load(path);values={}
        for key in KEYS:
            try:values[key]=_read(key)
            except (OSError,subprocess.SubprocessError):values[key]=None
        current=values.get('xsettings') or values.get('gtk-theme') or ''
        theme=_xfwm_selection(mode,accent,current,_installed_gtk_themes())
        cursor=cursor_name(mode)
        targets={'cursor-theme':cursor,'xsettings':theme,'gtk-theme':theme,'color-scheme':'prefer-dark' if mode=='dark' else 'prefer-light'}
        applied=False;failed=False
        for key,target in targets.items():
            value=values[key]
            if value is None or target is None:continue
            if value==target:applied=True;continue
            previous=records.get(key)
            original=previous['original'] if previous and value==previous['lastApplied'] else value
            records[key]=dict(original=original,lastApplied=target);_save(path,records)
            try:success=_write(key,target)
            except (OSError,subprocess.SubprocessError):success=False
            applied=applied or success;failed=failed or not success
            # Even an uncertain timeout leaves a recovery record: the service
            # may have applied the value before its reply was interrupted.
        return applied and not failed
    except (OSError,ValueError,subprocess.SubprocessError):return False

def restore_application_theme(root):
    """Restore each channel only while its value still matches Orbit's last write."""
    if not _available():return False
    path=_backup_path(root)
    try:
        records=_load(path);restored=False
        for key,entry in list(records.items()):
            try:current=_read(key)
            except (OSError,subprocess.SubprocessError):continue
            if current is None:continue # Preserve journal for a later service recovery.
            if current!=entry['lastApplied']:
                records.pop(key);_save(path,records);continue
            try:success=_write(key,entry['original'])
            except (OSError,subprocess.SubprocessError):success=False
            if success:records.pop(key);_save(path,records);restored=True
        return restored
    except (OSError,ValueError,subprocess.SubprocessError):return False

def launch_environment(mode,environment=None):
    """Let new GTK apps follow live settings instead of an inherited forced theme."""
    if mode not in ('dark','light'):raise ValueError('Invalid application appearance')
    env=dict(os.environ if environment is None else environment);env.pop('GTK_THEME',None)
    return env


def cursor_name(mode):
    name='Bibata-Modern-Classic' if mode=='light' else 'Bibata-Modern-Ice'
    return name if (Path('/usr/share/icons')/name/'cursors').is_dir() else 'DMZ-Black' if mode=='light' else 'DMZ-White'


def apply_cursor_theme(root,mode):
    if not _available():return False
    try:
        path=_backup_path(root);records=_load(path);value=_read('cursor-theme');target=cursor_name(mode)
        if value is None:return False
        if value==target:return True
        previous=records.get('cursor-theme');original=previous['original'] if previous and value==previous['lastApplied'] else value
        records['cursor-theme']=dict(original=original,lastApplied=target);_save(path,records)
        return _write('cursor-theme',target)
    except (OSError,ValueError,subprocess.SubprocessError):return False
