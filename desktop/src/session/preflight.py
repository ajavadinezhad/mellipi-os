"""Read-only prerequisites for installation and a real systemd/logind login.

Never opens DRM/input devices, creates a bus, authenticates, changes a unit or
acquires a seat. Driver metadata and active service names are diagnostics, not a
claim that EGL, audio hardware or PAM authentication has been validated.
"""
import itertools,os,re,shutil,stat,subprocess
from pathlib import Path

PROPERTIES=('Active','Remote','Type','Class','Seat','VTNr')

def inspect(environment=None,phase='install',*,root=Path('/'),which=None,runner=None,uid=None):
    if phase not in ('install','login'):raise ValueError('Unknown preflight phase')
    env=dict(os.environ if environment is None else environment)
    root=Path(root);which=which or shutil.which;runner=runner or subprocess.run
    uid=os.getuid() if uid is None else uid
    findings=[];details={};tools={}
    def path(name):return root/str(name).lstrip('/')
    def add(key,status,message,required=False):
        findings.append(dict(id=key,status=status,severity='error' if required else 'warning',message=message))
    def executable(name):
        if name not in tools:tools[name]=which(name,path=env.get('PATH',os.defpath))
        return tools[name]
    def command(args):
        try:
            result=runner(args,env=env,capture_output=True,text=True,timeout=3,check=False)
            output=result.stdout or ''
            return result.returncode,output[:32768] if len(output)<=32768 else ''
        except (OSError,subprocess.TimeoutExpired):return None,''
    def bus_names(kind):
        binary=executable('busctl')
        if not binary:return None
        code,output=command([binary,'--'+kind,'--timeout=2','--no-pager','call','org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','ListNames'])
        if code!=0 or not output.startswith('as '):return None
        return set(re.findall(r'"([A-Za-z0-9_.:-]{1,255})"',output))
    # A root package installation may precede the first user login. Do not
    # require /run/user/<uid>, a user manager, active seat or bus at this stage.
    for name in ('systemctl','loginctl','busctl'):
        if not executable(name):add(name,'missing','Install the supported systemd/logind login profile; '+name+' is missing.',True)
    details['systemd_running']=path('/run/systemd/system').is_dir()
    if phase=='login' and not details['systemd_running']:
        add('systemd','inactive','The supported login profile requires systemd as the running init and a logind-managed PAM login; seatd-only/OpenRC sessions are not yet supported.',True)
    pam=path('/etc/pam.d/swaylock')
    try:pam_readable=pam.is_file() and os.access(pam,os.R_OK) and 0<pam.stat().st_size<=65536
    except OSError:pam_readable=False
    details['pam_config_readable']=pam_readable
    if not pam_readable:add('pam','missing','Install the distribution swaylock PAM configuration at /etc/pam.d/swaylock and make it readable; authentication has not been tested.',True)
    details['authentication_validated']=False
    # Presence of vendor metadata alone never proves GBM/EGL initialization.
    vendors=path('/usr/share/glvnd/egl_vendor.d')
    try:vendor_count=sum(1 for index,item in enumerate(itertools.islice(vendors.iterdir(),64)) if index<64 and item.suffix=='.json' and item.is_file())
    except OSError:vendor_count=0
    details['graphics']=dict(egl_vendor_metadata_present=bool(vendor_count),egl_initialized=False,seat_acquired=False)
    if not vendor_count:add('graphics','unverified','No EGL vendor metadata was found. Install the GPU EGL/GBM driver and required firmware. This read-only check does not initialize EGL or validate scanout.')
    details['network']=dict(tool_present=bool(executable('nmcli')),daemon_status='not_checked')
    details['audio']=dict(tool_present=bool(executable('pactl')),daemon_status='not_checked')
    if not details['network']['tool_present']:add('network-tool','missing','NetworkManager controls are unavailable: install NetworkManager/nmcli in the full desktop profile; do not replace an existing network setup implicitly.')
    if not details['audio']['tool_present']:add('audio-tool','missing','Audio controls require pactl (pulseaudio-utils), PipeWire/PulseAudio compatibility and a session manager.')
    details['phase']=phase;details['supported_profile']='systemd-logind';details['hardware_validated']=False
    details['seatd_supported']=False
    if phase=='login':
        if uid==0:add('user','root','Start Mellipi as the desktop user through PAM/login, not with sudo.',True)
        runtime=env.get('XDG_RUNTIME_DIR','');private=False
        if runtime and Path(runtime).is_absolute():
            try:
                info=path(runtime).lstat()
                private=stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode) and info.st_uid==uid and stat.S_IMODE(info.st_mode)==0o700
            except OSError:pass
        details['runtime_private']=private
        if not private:add('runtime','invalid','XDG_RUNTIME_DIR must be an existing non-symlink directory owned by this user with mode 0700. Use a PAM/logind login; do not create a shared runtime directory.',True)
        system_names=bus_names('system');user_names=bus_names('user') if private and uid!=0 else None
        details['system_bus_available']=system_names is not None;details['user_bus_available']=user_names is not None
        if system_names is None:add('system-bus','unavailable','The system D-Bus is unavailable. Start the distribution D-Bus service before graphical login.',True)
        if user_names is None:add('user-bus','unavailable','The desktop user D-Bus is unavailable. Enable the distribution user-session bus/PAM profile; a private nested-test bus is not a replacement for a configured login.',True)
        logind=system_names is not None and 'org.freedesktop.login1' in system_names
        details['logind_available']=logind
        if not logind:add('logind','unavailable','org.freedesktop.login1 is not running on the system bus. Enable systemd-logind and log in through its PAM stack.',True)
        session={}
        if logind and executable('loginctl'):
            code,output=command([executable('loginctl'),'--no-pager','show-session','self',*[argument for prop in PROPERTIES for argument in ('--property',prop)]])
            if code==0:session=dict(line.split('=',1) for line in output.splitlines() if '=' in line)
        # Access to DRM and input is granted by libseat for the active login.
        # Requiring raw device read/write permissions here would reject normal
        # unprivileged logind sessions and encourage unsafe chmod/group fixes.
        local_active=session.get('Active')=='yes' and session.get('Remote')=='no' and bool(session.get('Seat')) and session.get('VTNr','0').isdigit() and int(session.get('VTNr','0'))>0
        details['active_local_seat']=local_active
        if not local_active:add('seat','unavailable','No active local VT login seat was confirmed. Start Mellipi from a display-manager login or a local PAM TTY; do not use sudo, SSH or change /dev/dri/input permissions.',True)
        if system_names is not None:
            network_active='org.freedesktop.NetworkManager' in system_names
            details['network']['daemon_status']='active' if network_active else 'inactive'
            if details['network']['tool_present'] and not network_active:add('network-daemon','inactive','nmcli is installed but NetworkManager is not active on the system bus. Enable the selected network profile, or use the existing system network manager.')
        if private and executable('systemctl') and uid!=0:
            _,output=command([executable('systemctl'),'--user','--no-pager','is-active','pipewire.service','pipewire-pulse.service','wireplumber.service','pipewire-media-session.service','pulseaudio.service'])
            states=output.splitlines()
            if len(states)==5 and all(state in ('active','inactive','failed','activating','deactivating','unknown') for state in states):
                details['audio']['units']=dict(zip(('pipewire','pipewire-pulse','wireplumber','pipewire-media-session','pulseaudio'),states))
                active=states[4]=='active' or (states[0]=='active' and states[1]=='active' and 'active' in states[2:4])
                details['audio']['daemon_status']='active' if active else 'inactive'
            else:details['audio']['daemon_status']='unknown'
            if details['audio']['tool_present'] and details['audio']['daemon_status']!='active':
                add('audio-daemon',details['audio']['daemon_status'],'pactl is installed, but an active PulseAudio service or PipeWire + pulse compatibility + a session manager was not confirmed. Check the user audio services; no service was started or restarted.')
    errors=[item['message'] for item in findings if item['severity']=='error']
    warnings=[item['message'] for item in findings if item['severity']=='warning']
    return dict(ok=not errors,issues=errors,warnings=warnings,findings=findings,details=details,changes_active_session=False)
