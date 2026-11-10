"""Configured input engines and installed permission agents; no polling daemon."""
import os,shutil
from pathlib import Path

POLKIT_CANDIDATES=(
 '/usr/lib/policykit-1-gnome/polkit-gnome-authentication-agent-1',
 '/usr/libexec/polkit-gnome-authentication-agent-1',
 '/usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1',
 '/usr/lib/polkit-mate/polkit-mate-authentication-agent-1',
 'lxqt-policykit-agent','lxpolkit',
)

def permission_agent():
    for name in POLKIT_CANDIDATES:
        path=shutil.which(name)
        if path and Path(path).name==Path(name).name and Path(path).is_file() and os.access(path,os.X_OK):return [path]
    return None

def configured_input_method(environment=None):
    env=os.environ if environment is None else environment
    if env.get('ORBIT_NESTED'):return None
    values=[env.get('GTK_IM_MODULE',''),env.get('QT_IM_MODULE',''),env.get('XMODIFIERS','')]
    # Respect a selected engine; merely installing an engine does not opt in.
    for value in values:
        lowered=value.lower()
        if lowered in ('fcitx','fcitx5','@im=fcitx'):
            binary=shutil.which('fcitx5');return [binary] if binary else None
        if lowered in ('ibus','@im=ibus'):
            binary=shutil.which('ibus-daemon');return [binary,'--xim'] if binary else None
    return None

def service_environment(command, environment):
    """Keep Noble's X11-only polkit timestamp call off native GTK Wayland.

    Ubuntu's policykit-1-gnome patch calls gdk_x11_get_server_time without a
    backend check. Scope compatibility to that agent in our native session;
    other GTK applications, input engines and caller state keep their backend.
    """
    import re
    env=dict(environment)
    if (command and Path(command[0]).name=='polkit-gnome-authentication-agent-1'
            and env.get('ORBIT_NATIVE_CONTROL')
            and re.fullmatch(r':[0-9]+(?:\.[0-9]+)?',env.get('DISPLAY',''))):
        env['GDK_BACKEND']='x11'
    return env
