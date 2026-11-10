"""Activate the selected enabled audio profile once at a real desktop login.

Installing units while a user manager is already running does not start them.
Never restart an existing server, enable a unit, undo a mask/disable, or run from
installation checks, previews or shell recovery. These are distribution units,
not additional Abstract daemons.
"""
import os,shutil,socket,subprocess
from pathlib import Path
UNITS=('pipewire.socket','pipewire.service','pipewire-pulse.socket','pipewire-pulse.service','wireplumber.service','pipewire-media-session.service','pulseaudio.socket','pulseaudio.service')

def parse_units(text):
    if len(text)>32768:return {}
    units={}
    for block in text.split('\n\n'):
        properties=dict(line.split('=',1) for line in block.splitlines() if '=' in line)
        name=properties.get('Id')
        if name in UNITS:units[name]=properties
    return units

def existing_audio_server(environment):
    runtime=environment.get('XDG_RUNTIME_DIR','')
    if not runtime or not Path(runtime).is_absolute():return False
    # Also respect servers launched outside user units (for example an existing
    # PulseAudio autostart). An explicit Unix socket avoids pactl autospawning.
    try:
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(.2);connection.connect(str(Path(runtime)/'pulse/native'))
        return True
    except OSError:return False

def selected_units(units,server_active=False):
    def active(name):return units.get(name,{}).get('ActiveState') in ('active','activating','reloading')
    def eligible(name):
        row=units.get(name,{})
        return row.get('LoadState')=='loaded' and row.get('ActiveState')=='inactive' and row.get('UnitFileState') in ('enabled','enabled-runtime')
    selected=[]
    if eligible('pipewire.socket'):selected.append('pipewire.socket')
    pulse_running=active('pulseaudio.service') or active('pulseaudio.socket')
    pipewire_pulse_running=active('pipewire-pulse.service') or active('pipewire-pulse.socket')
    if not server_active and not pulse_running and not pipewire_pulse_running:
        servers=[name for name in ('pipewire-pulse.socket','pulseaudio.socket') if eligible(name)]
        # Conflicting enabled profiles need an explicit user choice. Do not
        # silently steal the common Pulse socket from the other audio server.
        if len(servers)==1:selected.extend(servers)
    pipewire_ready=active('pipewire.service') or active('pipewire.socket') or 'pipewire.socket' in selected
    managers=('wireplumber.service','pipewire-media-session.service')
    if pipewire_ready and not any(active(name) for name in managers):
        enabled=[name for name in managers if eligible(name)]
        if len(enabled)==1:selected.extend(enabled)
    return selected

def start_enabled_audio(environment=None,*,runner=None,which=None,server_available=None):
    env=dict(os.environ if environment is None else environment)
    if env.get('ORBIT_NESTED'):return dict(requested=[],ok=True,reason='nested')
    if env.get('PULSE_SERVER') or env.get('PULSE_RUNTIME_PATH'):return dict(requested=[],ok=True,reason='custom audio server')
    runner=runner or subprocess.run;which=which or shutil.which
    binary=which('systemctl',path=env.get('PATH',os.defpath))
    if not binary:return dict(requested=[],ok=False,reason='user systemd manager unavailable')
    selected=[]
    try:
        probe=runner([binary,'--user','--no-pager','show','--property=Id','--property=LoadState','--property=ActiveState','--property=UnitFileState',*UNITS],env=env,capture_output=True,text=True,timeout=4,check=False)
        # show may return nonzero for absent alternatives while still reporting
        # the installed units accurately. Only loaded, enabled rows are eligible.
        units=parse_units(probe.stdout or '')
        if not units:return dict(requested=[],ok=False,reason='audio user unit state unavailable')
        selected=selected_units(units,(server_available or existing_audio_server)(env))
        if not selected:return dict(requested=[],ok=True,reason='existing or unselected audio profile')
        result=runner([binary,'--user','start',*selected],env=env,capture_output=True,text=True,timeout=8,check=False)
        return dict(requested=selected,ok=result.returncode==0,reason='enabled audio profile activated' if result.returncode==0 else 'enabled audio unit startup failed; inspect the user journal')
    except (OSError,subprocess.TimeoutExpired):return dict(requested=selected,ok=False,reason='audio user unit startup did not confirm within its bounded deadline')
