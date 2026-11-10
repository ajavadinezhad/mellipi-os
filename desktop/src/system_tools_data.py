"""Bounded, desktop-neutral settings data. No applications or services start here."""
import configparser,os,tempfile,unicodedata
from pathlib import Path
from session import xdg_autostart as autostart

def plain_label(value):
    return ''.join(c for c in str(value)[:160] if unicodedata.category(c)!='Cc').replace('<','‹').replace('>','›')

MAX_ROWS=512
DEFAULT_TYPES=(('browser','Web browser','text/html'),('files','File manager','inode/directory'),('text','Plain text files','text/plain'),('pdf','PDF documents','application/pdf'),('images','PNG images','image/png'),('audio','MP3 audio','audio/mpeg'),('video','MP4 video','video/mp4'))

def startup_rows(environment):
    rows=[]
    for name,path in sorted(autostart.selected_files(environment).items()):
        try:
            entry=autostart.read_entry(path);reason=autostart.eligible(entry,environment)
            owned=autostart.command_identity(entry) in autostart.OWNED_EXECUTABLES
            if owned:continue
            # Other desktop-specific entries are not actionable here. A user
            # disabled override can still be enabled without discarding its keys.
            hidden=entry.get('Hidden')=='true' or entry.get('X-GNOME-Autostart-enabled')=='false'
            visible=dict(entry,Hidden='false',**{'X-GNOME-Autostart-enabled':'true'})
            applicability=autostart.eligible(visible,environment)
            if applicability in ('another desktop','excluded desktop','conflicting desktop conditions','not an application'):continue
            rows.append(dict(id=name,name=plain_label(entry.get('Name',name)),enabled=not hidden,available=applicability is None,reason=applicability or ''))
        except (OSError,ValueError,UnicodeError,configparser.Error):continue
        if len(rows)>=MAX_ROWS:break
    return rows

def set_startup_enabled(name,enabled,environment):
    if not isinstance(enabled,bool) or not isinstance(name,str) or len(name)>240 or not name.endswith('.desktop') or Path(name).name!=name or '\0' in name:raise ValueError('Invalid startup entry')
    selected=autostart.selected_files(environment)
    if name not in selected:raise ValueError('Startup entry is no longer available')
    entry=autostart.read_entry(selected[name])
    if autostart.command_identity(entry) in autostart.OWNED_EXECUTABLES:raise ValueError('This startup entry belongs to the desktop session')
    user=autostart.directories(environment)[0];user.mkdir(mode=0o700,parents=True,exist_ok=True)
    destination=user/name
    if destination.is_symlink():raise ValueError('Cannot replace a symlinked startup entry')
    parser=configparser.ConfigParser(interpolation=None);parser.optionxform=str
    parser['Desktop Entry']=entry
    parser['Desktop Entry']['Hidden']='false' if enabled else 'true'
    if 'X-GNOME-Autostart-enabled' in entry:parser['Desktop Entry']['X-GNOME-Autostart-enabled']='true' if enabled else 'false'
    fd,temp=tempfile.mkstemp(prefix='.abstract-startup-',dir=user)
    try:
        with os.fdopen(fd,'w') as stream:parser.write(stream,space_around_delimiters=False);stream.flush();os.fsync(stream.fileno())
        os.chmod(temp,0o600);os.replace(temp,destination)
    finally:
        try:os.unlink(temp)
        except FileNotFoundError:pass

def default_choices(gio,key):
    row=next((r for r in DEFAULT_TYPES if r[0]==key),None)
    if not row:raise ValueError('Unknown application category')
    mime=row[2];current=gio.AppInfo.get_default_for_type(mime,False)
    apps=gio.AppInfo.get_all_for_type(mime) or []
    if current and not any(app.get_id()==current.get_id() for app in apps):apps.insert(0,current)
    mapping={};rows=[]
    for app in apps[:MAX_ROWS]:
        ident=app.get_id()
        if not ident or ident in mapping:continue
        mapping[ident]=app;rows.append(dict(id=ident,name=app.get_display_name() or ident,selected=bool(current and ident==current.get_id())))
    return rows,mapping

def set_default(gio,key,ident):
    rows,mapping=default_choices(gio,key)
    if ident not in mapping:raise ValueError('This application is no longer available')
    mime=next(r[2] for r in DEFAULT_TYPES if r[0]==key)
    targets=('text/html','x-scheme-handler/http','x-scheme-handler/https') if key=='browser' else (mime,)
    # GIO owns standard mimeapps.list updates; no desktop-specific settings tool.
    for target in targets:
        if not mapping[ident].set_as_default_for_type(target):raise RuntimeError('Could not save the default application')

def add_startup_application(gio,ident,environment):
    """Opt one installed application into Abstract login; never run it now."""
    import hashlib
    if not isinstance(ident,str) or not ident.endswith('.desktop') or len(ident)>240 or '/' in ident or '\0' in ident:raise ValueError('Choose an installed application')
    info=gio.DesktopAppInfo.new(ident)
    if info is None:raise ValueError('This application is no longer installed')
    filename=info.get_filename()
    if not filename or not Path(filename).is_absolute():raise ValueError('This application has no desktop entry')
    source=autostart.read_entry(filename)
    if source.get('Type')!='Application' or not source.get('Exec'):raise ValueError('This application cannot start automatically')
    if autostart.command_identity(source) in autostart.OWNED_EXECUTABLES:raise ValueError('This application belongs to the desktop session')
    keys={'Type','Name','Comment','Exec','TryExec','Path','Icon','Terminal','StartupNotify'}
    entry={key:value for key,value in source.items() if key in keys or key.startswith(('Name[','Comment['))}
    entry.update(Hidden='false',OnlyShowIn='Orbit;',DBusActivatable='false',**{'X-Abstract-Source':ident})
    reason=autostart.eligible(entry,environment)
    if reason:raise ValueError('This application cannot start automatically: '+reason)
    name='abstract-user-'+hashlib.sha256(ident.encode()).hexdigest()[:20]+'.desktop'
    user=autostart.directories(environment)[0];user.mkdir(mode=0o700,parents=True,exist_ok=True)
    destination=user/name
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or autostart.read_entry(destination).get('X-Abstract-Source')!=ident:raise ValueError('The startup entry already exists and was preserved')
        set_startup_enabled(name,True,environment);return name
    parser=configparser.ConfigParser(interpolation=None);parser.optionxform=str;parser['Desktop Entry']=entry
    fd,temp=tempfile.mkstemp(prefix='.abstract-startup-',dir=user)
    try:
        with os.fdopen(fd,'w') as stream:parser.write(stream,space_around_delimiters=False);stream.flush();os.fsync(stream.fileno())
        os.chmod(temp,0o600);os.link(temp,destination)
    finally:os.unlink(temp)
    return name
