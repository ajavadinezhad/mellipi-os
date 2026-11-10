#!/usr/bin/env python3
"""Local session descriptors with project paths, generated after official-package extraction."""
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parents[1];data=ROOT/'.wayland-runtime/usr/share'
portal=data/'xdg-desktop-portal/sway-portals.conf';portal.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/'session/sway-portals.conf',portal)
service=data/'dbus-1/services/org.freedesktop.impl.portal.desktop.wlr.service';service.parent.mkdir(parents=True,exist_ok=True)
service.write_text('[D-BUS Service]\nName=org.freedesktop.impl.portal.desktop.wlr\nExec='+str(ROOT/'.wayland-runtime/usr/libexec/xdg-desktop-portal-wlr')+'\n')

portals=data/'xdg-desktop-portal/portals';portals.mkdir(parents=True,exist_ok=True)
shutil.copyfile('/usr/share/xdg-desktop-portal/portals/gtk.portal',portals/'gtk.portal')

compositor=ROOT/'.wayland-runtime/compositor-lib';compositor.mkdir(exist_ok=True)
for lib in (ROOT/'.wayland-runtime/usr/lib/x86_64-linux-gnu').glob('*.so*'):
    if lib.name.startswith(('libQt','libLayerShell')):continue
    link=compositor/lib.name
    if not link.exists():link.symlink_to(lib.resolve())

shutil.copyfile(ROOT/'session/sway-portals.conf',portals/'sway-portals.conf')
shutil.copyfile(ROOT/'session/sway-portals.conf',portals/'portals.conf')
