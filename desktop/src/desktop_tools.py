"""Desktop-neutral on-demand tools and system settings; no idle polling."""
import os,shutil,subprocess,threading
from pathlib import Path
from qt_compat import QObject,Property,Signal,Slot
from system_tools_data import add_startup_application,DEFAULT_TYPES,startup_rows,set_startup_enabled,default_choices,set_default

# Existing installed services/frontends own privileged operations and package work.
CANDIDATES={
 'files':('Files',(('gio','open',Path.home().as_uri()),('xdg-open',str(Path.home())),('thunar',),('nautilus',),('dolphin',),('nemo',),('pcmanfm-qt',),('pcmanfm',))),
 'software':('Install applications',(('gnome-software',),('plasma-discover',),('mintinstall',),('pamac-manager',),('abstract-package-manager',),('synaptic-pkexec',),('synaptic',))),
 'updates':('Software updates',(('mintupdate',),('gnome-software','--mode=updates'),('plasma-discover','--mode','Update'),('pamac-manager','--updates'),('abstract-package-manager',),('synaptic-pkexec',),('synaptic',))),
 'users':('Users and passwords',(('cinnamon-settings','users'),('gnome-control-center','user-accounts'),('systemsettings','kcm_users'),('mate-user-admin',),('users-admin',))),
 'datetime':('Date and time',(('cinnamon-settings','calendar'),('gnome-control-center','datetime'),('systemsettings','kcm_clock'),('time-admin',))),
 'printers':('Printers',(('system-config-printer',),('gnome-control-center','printers'),('systemsettings','kcm_printer_manager'))),
 'input-method':('Input methods',(('fcitx5-configtool',),('fcitx5-config-qt',),('ibus-setup',),('im-config',))),
 'screen-reader':('Screen reader',(('orca',),)),
 'keyboard':('On-screen keyboard',(('onboard',),)),
}
# Retained for import compatibility; discovery below considers all candidates.
TOOLS={key:(label,commands[0]) for key,(label,commands) in CANDIDATES.items()}

def open_device_uri(uri):
    """Reap the short-lived GIO dispatcher; never wait for the file manager."""
    from desktop import application_environment
    result=subprocess.run(['gio','open',uri],env=application_environment(),start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,timeout=5)
    if result.returncode:raise RuntimeError('Could not open this device: '+(result.stderr.strip()[:160] or 'the file manager did not accept the request'))

def launch_tool(Gio,command,label):
    """GIO owns app activation/reaping; tool windows outlive this worker call."""
    from desktop import application_environment,terminal_gio
    _,GLib=terminal_gio()
    if not command or not shutil.which(command[0]):raise RuntimeError(label+' is no longer installed')
    environment=application_environment();context=Gio.AppLaunchContext()
    for key in os.environ:
        if key not in environment:context.unsetenv(key)
    for key,value in environment.items():context.setenv(key,value)
    text='/usr/bin/setsid -- '+' '.join(GLib.shell_quote(str(value).replace('%','%%')) for value in command)
    info=Gio.AppInfo.create_from_commandline(text,label,Gio.AppInfoCreateFlags.NONE)
    if not info.launch([],context):raise RuntimeError('Could not open '+label+': activation was not accepted')

def discover_tools(environment,which=shutil.which):
    rows={}
    for key,(label,commands) in CANDIDATES.items():
        if key=='keyboard' and environment.get('WAYLAND_DISPLAY'):
            commands=(('wvkbd-mobintl',),('wvkbd-desktop',),('squeekboard',))
        command=next((list(row) for row in commands if which(row[0]) and (row[0]!='abstract-package-manager' or (environment.get('ORBIT_NATIVE_CONTROL') and environment.get('WAYLAND_DISPLAY') and which('synaptic')))),[])
        reason='' if command else ('Install a compatible Wayland keyboard such as wvkbd or Squeekboard.' if key=='keyboard' and environment.get('WAYLAND_DISPLAY') else 'No compatible '+label.lower()+' tool is installed. Use your distribution’s package manager to install one.')
        rows[key]=dict(label=label,command=command,available=bool(command),reason=reason,builtin=False)
    return rows

class DesktopTools(QObject):
    notice=Signal(str);changed=Signal();viewRequested=Signal(str);update=Signal(object)
    def __init__(self,parent=None,environment=None,which=None):
        super().__init__(parent);self.environment=dict(os.environ if environment is None else environment);self._which=which or shutil.which
        self._tools=discover_tools(self.environment,which or shutil.which)
        if self.environment.get('WAYLAND_DISPLAY') and self._tools['keyboard']['available']:
            supported=False
            try:
                from native_compositor import NativeCompositor
                status=NativeCompositor(self.environment['ORBIT_NATIVE_CONTROL']).status()
                supported=status.get('capabilities',{}).get('trusted_virtual_keyboard') is True
            except (KeyError,OSError,ValueError,RuntimeError):pass
            if not supported:self._tools['keyboard'].update(available=False,reason='This session does not provide a trusted Wayland keyboard endpoint. Start an updated Mellipi native session to enable it.')
        try:
            import gi;gi.require_version('Gio','2.0');from gi.repository import Gio
            self.gioAvailable=True
        except (ImportError,ValueError):self.gioAvailable=False
        if self.gioAvailable:
            try:
                if Gio.AppInfo.get_default_for_type('inode/directory',False) is None:
                    fallback=next(([command] for command in ('thunar','nautilus','dolphin','nemo','pcmanfm-qt','pcmanfm') if self._which(command)),[])
                    self._tools['files'].update(command=fallback,available=bool(fallback),reason='' if fallback else 'Install a file manager, then select it under Default applications.')
            except Exception:pass
        for key,label in [('defaults','Default applications'),('devices','Removable devices')]:self._tools[key]=dict(label=label,command=[],available=self.gioAvailable,reason='' if self.gioAvailable else 'GIO integration is not installed in this Python runtime.',builtin=True)
        for key,label in [('users','Users and passwords'),('datetime','Date and time')]:self._tools[key]=dict(label=label,command=[],available=self.gioAvailable,reason='' if self.gioAvailable else 'Install python3-gi to access system services.',builtin=True)
        self._tools['recovery']=dict(label='Backups & recovery',command=[],available=True,reason='',builtin=True)
        self._tools['defaults-mint']=dict(label='Default applications',command=[],available=False,reason='Use the built-in Default applications page.',builtin=True)
        self._defaultKey='browser';self._defaults=[];self._startup=[];self._devices=[];self._state=dict(busy=False,error='',monitorAvailable=False,gioAvailable=self.gioAvailable);self._active=False;self._generation=0;self._startupReading=False;self._startupLock=threading.Lock();self._startupRevision=0;self._viewRequest={};self._viewSerial=0
        self._systemUsers=[];self._systemState=dict(busy=False,error='',usersAvailable=False,clockAvailable=False,timezone='',ntp=False,canNtp=False,synchronized=False,zones=[]);self._systemClosed=False
        from device_monitor import DeviceMonitor
        self.monitor=DeviceMonitor(self);self.monitor.result.connect(self.applyUpdate);self.update.connect(self.applyUpdate)
    tools=Property('QVariantMap',lambda s:{key:{k:v for k,v in row.items() if k!='command'} for key,row in s._tools.items()},notify=changed)
    toolRows=Property('QVariantList',lambda s:[dict(id=key,**{k:v for k,v in row.items() if k!='command'}) for key,row in s._tools.items() if key not in ('defaults','defaults-mint','devices','keyboard','input-method','screen-reader')],notify=changed)
    defaultTypes=Property('QVariantList',lambda s:[dict(id=key,name=name,mime=mime) for key,name,mime in DEFAULT_TYPES],constant=True)
    defaultApplications=Property('QVariantList',lambda s:s._defaults,notify=changed)
    defaultType=Property(str,lambda s:s._defaultKey,notify=changed)
    startupApps=Property('QVariantList',lambda s:s._startup,notify=changed)
    devices=Property('QVariantList',lambda s:s._devices,notify=changed)
    systemUsers=Property('QVariantList',lambda s:[{k:v for k,v in r.items() if k!='path'} for r in s._systemUsers],notify=changed)
    systemState=Property('QVariantMap',lambda s:dict(s._systemState),notify=changed)
    state=Property('QVariantMap',lambda s:dict(s._state),notify=changed)
    viewRequest=Property('QVariantMap',lambda s:dict(s._viewRequest),notify=changed)
    @Slot(object)
    def applyUpdate(self,data):
        if not isinstance(data,dict):return
        if 'devices' in data:self._devices=data['devices']
        if 'defaults' in data and data.get('defaultType',self._defaultKey)==self._defaultKey:self._defaults=data['defaults']
        if 'startup' in data and data.get('startupRevision',self._startupRevision)==self._startupRevision:self._startup=data['startup']
        if 'error' in data:self._state['error']=data['error'];self._state['busy']=False
        if data.get('operationDone'):self._state['busy']=False
        if 'monitorAvailable' in data:self._state['monitorAvailable']=data['monitorAvailable']
        if 'system' in data:
            result=data['system'];self._systemState.update(busy=False,error=result.get('error',''))
            if 'users' in result:self._systemUsers=result['users'];self._systemState['usersAvailable']=True
            if 'clock' in result:self._systemState.update(result['clock'],clockAvailable=True)
        self.changed.emit()
    def fail(self,error):self.applyUpdate(dict(error=str(error)[:240]));self.notice.emit(str(error)[:240])
    @Slot(bool)
    def setActive(self,active):
        self._active=active
        if active:
            if self.gioAvailable:self.monitor.start();self.refreshDefaults()
            self.refreshStartup()
        else:self.monitor.stop()
    @Slot()
    def refreshStartup(self):
        with self._startupLock:
            if self._startupReading:return
            self._startupReading=True
        environment=dict(self.environment);revision=self._startupRevision
        def work():
            try:self.update.emit(dict(startup=startup_rows(environment),startupRevision=revision))
            except Exception as error:self.update.emit(dict(error=str(error)[:240]))
            finally:
                with self._startupLock:self._startupReading=False
        threading.Thread(target=work,name='abstract-startup-read',daemon=True).start()
    @Slot(str,bool)
    def setStartupEnabled(self,ident,enabled):
        if self._state['busy']:return
        self._state.update(busy=True,error='');self.changed.emit();environment=dict(self.environment);self._startupRevision+=1;revision=self._startupRevision
        def work():
            try:set_startup_enabled(ident,enabled,environment);self.update.emit(dict(startup=startup_rows(environment),startupRevision=revision,operationDone=True))
            except Exception as error:self.update.emit(dict(error=str(error)[:240],operationDone=True))
        threading.Thread(target=work,name='abstract-startup-save',daemon=True).start()
    @Slot(str)
    def addStartupApplication(self,ident):
        if not self.gioAvailable or self._state['busy']:return
        self._state.update(busy=True,error='');self.changed.emit();environment=dict(self.environment)
        self._startupRevision+=1;revision=self._startupRevision
        def work(Gio):
            add_startup_application(Gio,ident,environment)
            self.update.emit(dict(startup=startup_rows(environment),startupRevision=revision,operationDone=True))
        self.monitor.submit(work)
    @Slot(str)
    def selectDefaultType(self,key):
        if key not in [row[0] for row in DEFAULT_TYPES]:return
        self._defaultKey=key;self._defaults=[];self.changed.emit();self.refreshDefaults()
    @Slot()
    def refreshDefaults(self):
        if not self.gioAvailable:return
        key=self._defaultKey
        def work(Gio):
            rows,_=default_choices(Gio,key);self.update.emit(dict(defaults=rows,defaultType=key))
        self.monitor.submit(work)
    @Slot(str)
    def setDefaultApplication(self,ident):
        if not self.gioAvailable or self._state['busy']:return
        self._state.update(busy=True,error='');self.changed.emit();key=self._defaultKey
        def work(Gio):
            set_default(Gio,key,ident);rows,_=default_choices(Gio,key);self.update.emit(dict(defaults=rows,defaultType=key,operationDone=True))
        self.monitor.submit(work)
    @Slot(str,str)
    def deviceAction(self,ident,action):
        if action=='open':
            row=next((row for row in self._devices if row['id']==ident),None)
            if row and row.get('uri'):
                uri=row['uri']
                self.monitor.submit(lambda Gio:open_device_uri(uri))
            return
        if action not in ('mount','unmount','eject') or self._state['busy']:return
        self._state.update(busy=True,error='');self.changed.emit();self.monitor.action(ident,action)
    def _system_submit(self,method,*args):
        if self._systemClosed or self._systemState['busy']:return
        self._systemState.update(busy=True,error='');self.changed.emit()
        def work():
            from system_settings import SystemSettingsBackend,ServiceError
            try:
                value=getattr(SystemSettingsBackend(),method)(*args)
                result={'clock' if method in ('clock','set_timezone','set_ntp','set_time') else 'users':value}
            except (ValueError,ServiceError) as error:result=dict(error=str(error)[:240])
            except Exception:result=dict(error='The system request failed. Refresh to check its current state.')
            if not self._systemClosed:self.update.emit(dict(system=result))
        threading.Thread(target=work,name='mellipi-system-settings',daemon=True).start()
    @Slot(str)
    def refreshSystem(self,section):
        if section in ('users','datetime'):self._system_submit('users' if section=='users' else 'clock')
    @Slot(int,str,bool)
    def saveSystemUser(self,uid,name,administrator):self._system_submit('update_user',uid,name,administrator)
    @Slot(str,str,str,str,bool)
    def createSystemUser(self,username,name,password,confirmation,administrator):self._system_submit('create_user',username,name,password,confirmation,administrator)
    @Slot(int,str,str)
    def resetSystemPassword(self,uid,password,confirmation):self._system_submit('reset_password',uid,password,confirmation)
    @Slot(int)
    def removeSystemUser(self,uid):self._system_submit('delete_user',uid)
    @Slot(str)
    def setSystemTimezone(self,zone):self._system_submit('set_timezone',zone)
    @Slot(bool)
    def setSystemNtp(self,enabled):self._system_submit('set_ntp',enabled)
    @Slot(str)
    def setSystemTime(self,value):self._system_submit('set_time',value)
    @Slot()
    def changeMyPassword(self):
        terminal=next((self._which(n) for n in ('x-terminal-emulator','foot','xfce4-terminal','gnome-terminal','konsole','xterm') if self._which(n)),None)
        if not terminal:self.fail('Install a terminal emulator to change your password securely.');return
        command=[terminal,*(['--'] if Path(terminal).name=='gnome-terminal' else [] if Path(terminal).name=='foot' else ['-e']),'/usr/bin/passwd']
        self.monitor.submit(lambda Gio:launch_tool(Gio,command,'Change my password'))
    @Slot(str)
    def open(self,key):
        row=self._tools.get(key)
        if not row or not row['available']:self.fail((row or {}).get('reason','This tool is unavailable'));return
        if row.get('builtin'):
            if key in ('users','datetime'):self.refreshSystem(key)
            self._viewSerial+=1;self._viewRequest=dict(name=key,serial=self._viewSerial);self.changed.emit();self.viewRequested.emit(key);return
        command=list(row['command']);label=row['label']
        def work(Gio):
            try:
                if len(command)==3 and command[:2]==['gio','open']:open_device_uri(command[2])
                else:launch_tool(Gio,command,label)
            except Exception as error:raise RuntimeError('Could not open '+label+': '+str(error)[:160]) from error
        self.monitor.submit(work)
    @Slot()
    def close(self):self._systemClosed=True;self.monitor.stop()
