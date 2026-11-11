"""Native desktop adapters. No shell evaluation; only explicit desktop operations."""
import configparser
import os
import shutil
import re
from pathlib import Path
from project_paths import PROJECT_ROOT, SOURCE_ROOT
import subprocess
from urllib.parse import urlparse, unquote


def application_roots():
    roots=[os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share'))]
    roots+=os.environ.get('XDG_DATA_DIRS','/usr/local/share:/usr/share').split(':')
    return list(dict.fromkeys(Path(value)/'applications' for value in roots[:32] if value and Path(value).is_absolute()))


def locale_candidates():
    locale=os.environ.get('LC_ALL') or os.environ.get('LC_MESSAGES') or os.environ.get('LANG','C')
    locale=re.sub(r'\.[^@]*','',locale)
    if locale in ('C','POSIX'):return []
    candidates=[]
    for value in [*filter(None,os.environ.get('LANGUAGE','').split(':')),locale]:
        value=re.sub(r'\.[^@]*','',value)
        language,_,modifier=value.partition('@');lang,_,country=language.partition('_')
        candidates.extend([value,language,lang+'@'+modifier if modifier else lang,lang])
    return list(dict.fromkeys(value for value in candidates if value and len(value)<80))


def desktop_string(value):
    return re.sub(r'\\([sntr\\;])',lambda match:{'s':' ','n':'\n','t':'\t','r':'\r','\\':'\\',';':';'}.get(match[1],match[0]),value)[:2048]


def localized_entry(entry,key,candidates):
    return desktop_string(next((entry[key+'['+locale+']'] for locale in candidates if key+'['+locale+']' in entry),entry.get(key,'')))


def desktop_keywords(value):
    # Semicolons escaped inside a word are literal, not list delimiters.
    return [desktop_string(part)[:120] for part in re.split(r'(?<!\\);',value)[:64] if part]


def application_entries(base):
    for index,(folder,dirs,files) in enumerate(os.walk(base,followlinks=False)):
        if index>=2048:return
        dirs[:]=sorted(name for name in dirs if not name.startswith('.'))
        for name in sorted(files):
            if name.endswith('.desktop'):yield Path(folder)/name


def applications():
    seen,result=set(),[];candidates=locale_candidates();scanned=0
    for base in application_roots():
        if not base.is_dir():continue
        for path in application_entries(base):
            scanned+=1
            if scanned>16384:return sorted(result,key=lambda app:app['name'].casefold())
            ident=str(path.relative_to(base)).replace('/','-')
            if ident in seen:continue
            seen.add(ident)
            try:
                if path.stat().st_size>262144:continue
                parser=configparser.ConfigParser(interpolation=None,strict=False);parser.optionxform=str
                parser.read(path,encoding='utf-8');entry=parser['Desktop Entry']
                if entry.get('Hidden','false').lower()=='true' or entry.get('NoDisplay','false').lower()=='true':continue
                if entry.get('Type')!='Application':continue
                desktops=set(os.environ.get('XDG_CURRENT_DESKTOP','XFCE').split(':'))
                only=set(filter(None,entry.get('OnlyShowIn','').split(';')));excluded=set(filter(None,entry.get('NotShowIn','').split(';')))
                if only and not desktops.intersection(only):continue
                if desktops.intersection(excluded):continue
                if not entry.get('Exec') and entry.get('DBusActivatable','false').lower()!='true':continue
                executable=desktop_string(entry.get('TryExec',''))
                if executable and (not shutil.which(executable) or ('/' in executable and not Path(executable).is_absolute())):continue
                name=localized_entry(entry,'Name',candidates) or ident
                description=localized_entry(entry,'Comment',candidates);generic=localized_entry(entry,'GenericName',candidates)
                keyword_value=next((entry['Keywords['+locale+']'] for locale in candidates if 'Keywords['+locale+']' in entry),entry.get('Keywords',''))
                keywords=desktop_keywords(keyword_value)
                search=' '.join([name,entry.get('Name',''),description,generic,*keywords,ident]).casefold()
                result.append(dict(id=ident,path=str(path),name=name,icon=entry.get('Icon','application-x-executable'),description=description,genericName=generic,keywords=keywords,searchText=search,startup=entry.get('StartupWMClass','').lower()))
            except (configparser.Error,OSError,UnicodeError,KeyError):continue
    return sorted(result,key=lambda app:app['name'].casefold())


def command(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=3, check=True).stdout


def parse_windows(raw):
    windows=[]
    for line in raw.splitlines():
        parts=line.split(None,9)
        if len(parts)<10: continue
        ident, desktop, pid, x,y,w,h, klass,host,title=parts
        try:
            if klass.lower().endswith('.orbit-shell') or int(pid)==os.getpid(): continue
            windows.append(dict(id=ident, desktop=int(desktop), pid=int(pid), x=int(x),y=int(y),width=int(w),height=int(h), klass=klass.lower(),title=title))
        except ValueError: continue
    return windows


def window_state():
    windows=parse_windows(command(['wmctrl','-lpGx']))
    desktops=[]
    for line in command(['wmctrl','-d']).splitlines():
        fields=line.split()
        if len(fields)<2: continue
        desktops.append(dict(id=int(fields[0]),active=fields[1]=='*',name=f'Space {int(fields[0])+1}'))
    return dict(windows=windows, desktops=desktops)


def local_file(uri):
    parsed=urlparse(uri)
    if parsed.scheme!='file' or parsed.netloc not in ('','localhost'): raise ValueError('Only local file drops are supported')
    path=Path(unquote(parsed.path)).resolve(strict=True)
    if not path.is_file(): raise ValueError('Drop a file, not a folder')
    return path


def x11_state(connection):
    """Read EWMH state on an existing connection. No command spawning or pixel capture."""
    from Xlib import X, error
    root=connection.screen().root
    atom=connection.intern_atom
    def prop(window,name):
        p=window.get_full_property(atom(name),X.AnyPropertyType)
        return p.value if p is not None else None
    def first(window,name,default=0):
        value=prop(window,name)
        return int(value[0]) if value is not None and len(value) else default
    active=first(root,'_NET_ACTIVE_WINDOW',0)
    ids=prop(root,'_NET_CLIENT_LIST');ids=list(ids) if ids is not None else []
    stacking=prop(root,'_NET_CLIENT_LIST_STACKING')
    if stacking is not None:ids=list(dict.fromkeys(ids+list(stacking)))
    windows=[]
    for ident in ids:
        try:
            w=connection.create_resource_object('window',int(ident))
            raw=prop(w,'_NET_WM_NAME')
            title=bytes(raw).decode('utf-8','replace') if raw is not None else str(w.get_wm_name() or '')
            classes=w.get_wm_class()
            klass=(classes if isinstance(classes,str) else '.'.join(str(part) for part in classes or () if part)).lower()
            if not klass:
                raw_class=prop(w,'WM_CLASS')
                if raw_class is not None:klass=bytes(raw_class).decode('utf-8','replace').replace('\0','.').strip('.').lower()
            if not title.strip():title=str(w.get_wm_name() or klass or 'Untitled')
            if first(w,'_NET_WM_PID',0)==os.getpid() or 'orbit-shell' in klass:continue
            types=prop(w,'_NET_WM_WINDOW_TYPE')
            excluded=[atom('_NET_WM_WINDOW_TYPE_'+t) for t in ('DOCK','DESKTOP','NOTIFICATION','TOOLTIP','MENU','POPUP_MENU','DROPDOWN_MENU','SPLASH')]
            if types is not None and any(t in excluded for t in types): continue
            if not title: continue
            desk=first(w,'_NET_WM_DESKTOP',0)
            windows.append(dict(id=f'0x{int(ident):08x}',desktop=-1 if desk==0xffffffff else desk,pid=first(w,'_NET_WM_PID',0),klass=klass,title=title,active=int(ident)==active))
        except (error.XError,ValueError,TypeError): continue
    current=first(root,'_NET_CURRENT_DESKTOP',0); count=min(first(root,'_NET_NUMBER_OF_DESKTOPS',1),64)
    return dict(windows=windows,desktops=[dict(id=i,active=i==current,name=f'Space {i+1}') for i in range(count)])


def match_application(window,apps):
    klass=window.get('klass','').casefold();tokens=set(klass.split('.'))
    for app in apps:
        startup=app.get('startup','').casefold()
        ident=app['id'].removesuffix('.desktop').casefold()
        if (startup and (startup==klass or startup in tokens)) or ident==klass:return app
    for app in apps:
        ident=app['id'].removesuffix('.desktop').casefold();basename=ident.rsplit('.',1)[-1]
        if basename in tokens or (len(ident)>5 and ident in klass):return app
    return None


def notification_target(note,apps,windows):
    """Resolve notification metadata against known apps/windows, never as a command."""
    entry=note.get('desktopEntry','').removesuffix('.desktop').casefold()
    app=next((a for a in apps if entry and a['id'].removesuffix('.desktop').casefold()==entry),None)
    name=note.get('app','').strip().casefold()
    if not app and name:
        candidates=[a for a in apps if name in (a['name'].casefold(),a['id'].removesuffix('.desktop').casefold(),a.get('startup','').casefold())]
        if len(candidates)==1:app=candidates[0]
    if app:
        matches=[w for w in windows if match_application(w,[app])]
        if matches:return 'window',next((w for w in matches if w.get('active')),matches[0])['id']
        return 'app',app['id']
    if name:
        matches=[w for w in windows if name==w.get('klass','').casefold() or name in w.get('klass','').casefold().split('.')]
        if matches:return 'window',next((w for w in matches if w.get('active')),matches[0])['id']
    return None


def dock_groups(apps,windows,pins=None):
    pinned=[]
    for alternatives in [('firefox.desktop','com.google.Chrome.desktop'),('mellipi-files.desktop','thunar.desktop','org.gnome.Nautilus.desktop'),('mellipi-terminal.desktop','xfce4-terminal.desktop','org.gnome.Terminal.desktop'),('org.xfce.mousepad.desktop','xed.desktop')]:
        app=next((a for a in apps if a['id'] in alternatives),None)
        if app:pinned.append(app)
    if pins is not None:pinned=[a for ident in pins for a in apps if a['id']==ident]
    groups={a['id']:dict(id=a['id'],name=a['name'],icon=a['icon'],windows=[],pinned=True) for a in pinned}
    for window in windows:
        app=match_application(window,apps);key=app['id'] if app else window['klass']
        if key not in groups:groups[key]=dict(id=key,name=app['name'] if app else window['klass'].rsplit('.',1)[-1] or window['title'],icon=app['icon'] if app else window.get('icon','application-x-executable'),windows=[],pinned=False)
        groups[key]['windows'].append(window)
    return list(groups.values())


def application_launch_path(app,environment):
    """Route only the distro Synaptic entry through the native auth bridge."""
    bridge=Path('/usr/lib/abstract/synaptic-native.desktop')
    if (app.get('id')=='synaptic.desktop' and app.get('path')=='/usr/share/applications/synaptic.desktop'
            and environment.get('ORBIT_NATIVE_CONTROL') and environment.get('WAYLAND_DISPLAY')
            and bridge.is_file() and shutil.which('abstract-package-manager') and shutil.which('synaptic')):
        return str(bridge)
    return app['path']


def application_environment():
    """Never turn a launched Qt app into a shell panel or force Orbit's private renderer."""
    env={k:v for k,v in os.environ.items() if not k.startswith('ORBIT_') or k=='ORBIT_NATIVE_CONTROL'};root=PROJECT_ROOT
    for key in ('QT_WAYLAND_SHELL_INTEGRATION','ORBIT_QT','QT_QUICK_BACKEND','QT_QPA_PLATFORM'):
        env.pop(key,None)
    if env.get('QT_QUICK_CONTROLS_STYLE','').startswith(str(root/'.wayland-runtime')):env.pop('QT_QUICK_CONTROLS_STYLE',None)
    for key in ('QT_PLUGIN_PATH','QML2_IMPORT_PATH','PYTHONPATH','LD_LIBRARY_PATH'):
        parts=[p for p in env.get(key,'').split(':') if p and p!=str(SOURCE_ROOT) and not p.startswith(str(root/'.wayland-runtime')) and not p.startswith(str(root/'.runtime')) and p!=str(root/'.qt5-a11y-runtime') and not p.startswith(str(root/'.qt5-a11y-runtime')+os.sep)]
        if parts:env[key]=':'.join(parts)
        else:env.pop(key,None)
    return env

def terminal_gio():
    import sys
    if '/usr/lib/python3/dist-packages' not in sys.path:sys.path.append('/usr/lib/python3/dist-packages')
    from gi.repository import Gio,GLib
    return Gio,GLib

def launch_terminal():
    """Use the system terminal; GIO owns activation and child reaping."""
    executable=next((value for name in ('mellipi-terminal','x-terminal-emulator','foot','xfce4-terminal','gnome-terminal','konsole','xterm') if (value:=shutil.which(name))),None)
    if not executable:raise RuntimeError('Install a terminal emulator to use the terminal shortcut')
    try:
        Gio,GLib=terminal_gio();environment=application_environment();context=Gio.AppLaunchContext()
        if os.path.basename(executable)=='mellipi-terminal' and os.environ.get('ORBIT_SETTINGS_FILE'):
            environment['ORBIT_SETTINGS_FILE']=os.environ['ORBIT_SETTINGS_FILE']
        for key in os.environ:
            if key not in environment:context.unsetenv(key)
        for key,value in environment.items():context.setenv(key,value)
        app=Gio.AppInfo.create_from_commandline('/usr/bin/setsid -- '+GLib.shell_quote(executable.replace('%','%%')),'Terminal',Gio.AppInfoCreateFlags.NONE)
        if not app.launch([],context):raise RuntimeError('Terminal activation was not accepted')
        return True
    except Exception as error:raise RuntimeError('Could not open terminal: '+str(error)[:180]) from error

