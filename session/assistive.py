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
