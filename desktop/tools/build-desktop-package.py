#!/usr/bin/env python3
"""Build a portable-path Debian/Ubuntu package. Does not install or stop anything."""
import argparse,gzip,json,os,re,shutil,struct,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DEPENDENCIES=('python3','python3-pyqt5','python3-pyqt5.qtquick','python3-gi','python3-cairo','gir1.2-gtk-3.0','gir1.2-rsvg-2.0','librsvg2-common','libqt5svg5','libxcb-damage0','libxcb-composite0','liblayershellqtinterface5','layer-shell-qt','qtwayland5','qml-module-qtquick2','qml-module-qtquick-controls2','qml-module-qtquick-layouts','qml-module-qtquick-window2','qml-module-qtquick-dialogs','dbus-user-session','libc6 (>= 2.38)','libegl1','libgles2','libgbm1','libinput10','libseat1','libudev1','libxkbcommon0','libwayland-client0','libwayland-server0','libcairo2','libpam0g','swaylock','swayidle','xwayland','grim','slurp','util-linux','xdg-utils','xdg-desktop-portal','xdg-desktop-portal-gtk','xdg-desktop-portal-wlr','pipewire','libpipewire-0.3-0t64 | libpipewire-0.3-0','libinih1','libglib2.0-bin','polkitd','pkexec','policykit-1-gnome | mate-polkit | lxqt-policykit | lxpolkit','pulseaudio-utils','pipewire-pulse | pulseaudio','wireplumber | pipewire-media-session','thunar | pcmanfm-qt | pcmanfm | nautilus','x-terminal-emulator','adwaita-icon-theme')
RECOMMENDS=('network-manager','network-manager-gnome','bluez','upower','power-profiles-daemon','gnome-keyring','gvfs','udisks2','system-config-printer','ddcutil','wvkbd','fcitx5','fcitx5-config-qt','fcitx5-frontend-qt5','fcitx5-frontend-gtk3','orca','gnome-system-tools | mate-user-admin','gnome-software | plasma-discover | synaptic')
RUNTIME_FILES=('.native-runtime/bin/orbit-compositor','backend/target/release/orbit-core','.lock-runtime/bin/swaylock','.portal-runtime/xdg-desktop-portal-wlr')

# Explicit opt-in installation profile. Merely installing abstract-shell never
# selects a greeter, adds another desktop, or changes a display-manager default.
DESKTOP_DEPENDENCIES=('systemd-sysv','libpam-systemd','dbus-user-session','lightdm','lightdm-gtk-greeter','xserver-xorg','network-manager','network-manager-gnome','bluez','upower','power-profiles-daemon','gnome-keyring','libpam-gnome-keyring','gvfs','gvfs-backends','udisks2','thunar','foot','mousepad','epiphany-browser | firefox-esr','synaptic','system-config-printer','fonts-dejavu-core','wvkbd','orca','fcitx5','fcitx5-config-qt','fcitx5-frontend-qt5','fcitx5-frontend-gtk3','ddcutil','gnome-system-tools')

def packaged_elfs(stage,architecture):
    if architecture!='amd64':raise ValueError('The supported release baseline is Ubuntu 24.04 amd64; rebuild and validate other targets separately')
    result=[]
    for path in sorted(Path(stage).rglob('*')):
        if path.is_symlink() or not path.is_file():continue
        with path.open('rb') as source:header=source.read(20)
        if not header.startswith(b'\x7fELF'):continue
        if len(header)<20 or header[4]!=2 or header[5]!=1 or struct.unpack('<H',header[18:20])[0]!=62:
            raise ValueError('Packaged ELF does not match amd64: '+str(path))
        result.append(path)
    return result

def elf_dependencies(stage,architecture,version):
    """Resolve every packaged ELF against distro metadata and private libraries."""
    stage=Path(stage).resolve();files=packaged_elfs(stage,architecture)
    required=[stage/'usr/lib/abstract'/name for name in RUNTIME_FILES]
    if any(path not in files for path in required):raise ValueError('Required runtime is not a valid amd64 ELF')
    for tool in ('readelf','dpkg-shlibdeps'):
        if not shutil.which(tool):raise ValueError('Build dependency missing: '+tool+' (install binutils and dpkg-dev)')
    sonames=set();library_dirs=set()
    for path in files:
        dynamic=subprocess.check_output(['readelf','-d',str(path)],text=True)
        match=re.search(r'\(SONAME\).*\[([^]]+)\]',dynamic)
        if match:sonames.add(match[1]);library_dirs.add(path.parent)
    with tempfile.TemporaryDirectory(prefix='abstract-shlibdeps-') as directory:
        work=Path(directory);(work/'debian').mkdir()
        write(work/'debian/control','Source: abstract-os\nSection: x11\nPriority: optional\nMaintainer: Abstract OS project\n\nPackage: abstract-shell\nArchitecture: amd64\nDescription: Abstract runtime\n')
        local=work/'debian/shlibs.local';lines=[]
        for soname in sorted(sonames):
            match=re.fullmatch(r'(.+)\.so\.(.+)',soname)
            if not match:raise ValueError('Unsupported bundled library SONAME: '+soname)
            lines.append(match[1]+' '+match[2]+' abstract-shell (= '+version+')')
        write(local,'\n'.join(lines)+'\n')
        args=['dpkg-shlibdeps','-O','-xabstract-shell','-L'+str(local),'-S'+str(stage)]
        args+=['-l'+str(path) for path in sorted(library_dirs)]
        args+=['-e'+str(path) for path in files]
        env=dict(os.environ,LC_ALL='C');env.pop('LD_LIBRARY_PATH',None)
        result=subprocess.run(args,cwd=work,env=env,capture_output=True,text=True,timeout=90)
        if result.returncode:raise ValueError('ELF dependency resolution failed: '+result.stderr[-4000:])
        value=next((line.partition('=')[2] for line in result.stdout.splitlines() if line.startswith('shlibs:Depends=')),None)
        if value is None:raise ValueError('dpkg-shlibdeps returned no dependency field')
        return [item.strip() for item in value.split(',') if item.strip()]

def stage_desktop_package(stage,version):
    stage=Path(stage)
    deps=['abstract-shell (= '+version+')',*DESKTOP_DEPENDENCIES,'gnome-themes-extra']
    write(stage/'DEBIAN/control',f'Package: abstract-desktop\nVersion: {version}\nSection: metapackages\nPriority: optional\nArchitecture: all\nMaintainer: Abstract OS project\nDepends: '+', '.join(deps)+'\nDescription: Complete Abstract desktop for an Ubuntu 24.04 systemd base\n Opt-in login greeter, hardware services, browser, editor and package tools.\n Uses distribution display-manager selection and PAM configuration.\n')
    write(stage/'etc/lightdm/lightdm-gtk-greeter.conf.d/60-abstract.conf',(ROOT/'packaging/abstract-greeter.conf').read_text())
    write(stage/'usr/share/backgrounds/abstract/login.svg',(ROOT/'packaging/abstract-login.svg').read_text())
    write(stage/'DEBIAN/conffiles','/etc/lightdm/lightdm-gtk-greeter.conf.d/60-abstract.conf\n')
    write(stage/'usr/share/doc/abstract-desktop/README','Abstract desktop installation profile\n\nInstall alongside abstract-shell on an Ubuntu 24.04 amd64 systemd base.\nLightDM and its GTK greeter are installed using distribution package policy;\nif another display manager exists, use its normal debconf selection.\nNo Abstract maintainer script chooses or overwrites a display manager or PAM.\nThe GTK greeter receives a dpkg-managed appearance fragment and a static SVG\nwallpaper. Existing main greeter configuration takes precedence; local edits\nto the Abstract fragment are protected as a conffile. No greeter is restarted.\nRemoving this metapackage alone does not remove its applications or services.\n')
    for path in stage.rglob('*'):
        if not path.is_symlink():path.chmod(0o755 if path.is_dir() else 0o644)
    return stage

def write(path,text,mode=0o644):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text);path.chmod(mode)

def stage_package(stage,version,architecture,root=ROOT):
    root=Path(root);stage=Path(stage);lib=stage/'usr/lib/abstract'
    source_root=root/'src' if (root/'src').is_dir() else root
    docs_root=root/'docs' if (root/'docs').is_dir() else root.parent/'docs'
    for name in RUNTIME_FILES:
        if not (root/name).is_file():raise ValueError('Build required runtime first: '+name)
    lib.mkdir(parents=True)
    for p in source_root.glob('*.py'):shutil.copy2(p,lib/p.name)
    for name in ('run-native-session.sh','run-native-shell.sh'):
        shutil.copy2(root/name,lib/name)
    for folder in ('native','themes','session'):
        source=(source_root if folder=='session' else root)/folder
        shutil.copytree(source,lib/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.log','*.sqlite3','*.sock'))
    for name in RUNTIME_FILES:
        target=lib/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/name,target)
    if (root/'.tray-runtime').is_dir():shutil.copytree(root/'.tray-runtime',lib/'.tray-runtime',symlinks=True)
    if (root/'.portal-runtime').is_dir():shutil.copytree(root/'.portal-runtime',lib/'.portal-runtime',symlinks=True,dirs_exist_ok=True)
    accessibility=root/'.qt5-a11y-runtime'
    if accessibility.is_dir():
        if not (accessibility/'lib/libQt5WaylandClient.so.5').is_file():raise ValueError('Finish the Qt5 accessibility runtime build before packaging')
        shutil.copytree(accessibility,lib/'.qt5-a11y-runtime',symlinks=True)
    for name in ('wayland-env.sh','qt5-env.sh','native-output-power.py','display-watchdog.py','migrate-user-state.py'):
        target=lib/'tools'/name;target.parent.mkdir(exist_ok=True);shutil.copy2(root/'tools'/name,target)
    for name in ('tools/prepare-qt5-a11y-runtime.py','tools/qt5-a11y-inputs.json','patches/qt5-a11y-connection-ready.patch'):
        source=root/name
        if source.is_file():
            target=lib/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    for command,kind in (('abstract-session','session'),('abstractctl','control')):
        write(stage/'usr/bin'/command,'#!/bin/sh\nexec /usr/bin/python3 /usr/lib/abstract/installed_launcher.py '+kind+' "$@"\n',0o755)
    write(stage/'usr/share/wayland-sessions/abstract.desktop','[Desktop Entry]\nName=Abstract\nComment=Lightweight independent Wayland desktop\nExec=/usr/bin/abstract-session\nTryExec=/usr/bin/abstract-session\nType=Application\nDesktopNames=Orbit;\n')
    write(stage/'usr/share/applications/orbit-settings.desktop','[Desktop Entry]\nType=Application\nName=Abstract Settings\nExec=/usr/bin/abstractctl system-settings\nIcon=preferences-system\nCategories=Settings;DesktopSettings;\nStartupWMClass=orbit-settings\n')
    write(stage/'usr/share/applications/orbit.desktop','[Desktop Entry]\nType=Application\nName=Abstract\nExec=/usr/bin/abstractctl launcher\nIcon=preferences-desktop\nOnlyShowIn=Orbit;\nCategories=System;\n')
    assets={
      'tools/abstract-charge-limit':('usr/lib/abstract/abstract-charge-limit',0o755),
      'packaging/org.abstract.charge-limit.policy':('usr/share/polkit-1/actions/org.abstract.charge-limit.policy',0o644),
      'packaging/abstract-charge-limits.service':('usr/lib/systemd/system/abstract-charge-limits.service',0o644),
      'packaging/90-abstract-charge-limits.rules':('usr/lib/udev/rules.d/90-abstract-charge-limits.rules',0o644)}
    for source,(target,mode) in assets.items():
        if (root/source).is_file():write(stage/target,(root/source).read_text(),mode)
    write(stage/'DEBIAN/postinst','#!/bin/sh\nset -e\nif [ "$1" = configure ]; then\n chmod 0755 /usr/lib/abstract\n if command -v systemctl >/dev/null 2>&1; then systemctl daemon-reload || true; fi\n if command -v deb-systemd-helper >/dev/null 2>&1; then deb-systemd-helper enable abstract-charge-limits.service >/dev/null || true; fi\n if command -v udevadm >/dev/null 2>&1; then udevadm control --reload || true; fi\nfi\n',0o755)
    write(stage/'DEBIAN/postrm','#!/bin/sh\nset -e\nif [ "$1" = purge ] && command -v deb-systemd-helper >/dev/null 2>&1; then\n deb-systemd-helper purge abstract-charge-limits.service >/dev/null || true\nfi\nif [ "$1" = remove ] || [ "$1" = purge ]; then\n if command -v systemctl >/dev/null 2>&1; then systemctl daemon-reload || true; fi\n if command -v udevadm >/dev/null 2>&1; then udevadm control --reload || true; fi\nfi\n',0o755)
    portal=source_root/'session/configs/xdg-desktop-portal/orbit-portals.conf'
    write(stage/'usr/share/xdg-desktop-portal/orbit-portals.conf',portal.read_text())
    doc=stage/'usr/share/doc/abstract-shell';doc.mkdir(parents=True)
    shutil.copy2(root/'README.md',doc/'README.md')
    for name in ('independent-desktop.md','request-recheck-2026-11-08.md','native-protocols.md','hardware-acceptance-2026-11-08.md','operational-readiness.md','clean-install-acceptance.md','source-build-baseline.md','audits/2026-11-09-clean-full-minimum.json'):
        source=docs_root/name
        if source.is_file():
            # Keep old flat doc paths and README's repository-relative links.
            for destination in (doc/name,doc/'docs'/name):
                destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)
    for source,name in ((root/'compositor/LICENSE-SMITHAY','smithay-LICENSE'),(root/'.screen-lock-build/swaylock-1.8.6/LICENSE','swaylock-LICENSE')):
        if source.is_file():shutil.copy2(source,doc/name)
    write(doc/'runtime-provenance.json',json.dumps({name:json.loads((root/name).read_text()) for name in ('.lock-runtime/manifest.json','.native-drm-runtime/manifest.json','.qt5-a11y-runtime/manifest.json') if (root/name).is_file()},indent=2)+'\n')
    generated=elf_dependencies(stage,architecture,version)
    dependencies=list(dict.fromkeys([*DEPENDENCIES,*generated]))
    write(doc/'elf-dependencies.json',json.dumps(dict(architecture=architecture,generated=generated),indent=2)+'\n')
    control=f'Package: abstract-shell\nVersion: {version}\nSection: x11\nPriority: optional\nArchitecture: {architecture}\nMaintainer: Abstract OS project\nDepends: '+', '.join(dependencies)+'\nRecommends: '+', '.join(RECOMMENDS)+'\nDescription: Abstract lightweight native Wayland desktop\n Native compositor, desktop shell and system integrations. Uses standard\n Linux services and stores user data in private XDG directories.\n'
    write(stage/'DEBIAN/control',control)
    # Staging must not inherit a developer umask that permits group writes.
    for path in stage.rglob("*"):
        if not path.is_symlink():path.chmod(0o755 if path.is_dir() else (path.stat().st_mode & 0o777 & ~0o022))
    return stage

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--version',default='0.1.6');parser.add_argument('--output-dir',type=Path,default=ROOT/'dist');parser.add_argument('--with-desktop',action='store_true',help='Also build the optional complete desktop metapackage');args=parser.parse_args()
    if not re.fullmatch(r'[0-9][A-Za-z0-9.+~:-]{0,63}',args.version):parser.error('Invalid Debian version')
    architecture=subprocess.check_output(['dpkg','--print-architecture'],text=True).strip()
    args.output_dir.mkdir(parents=True,exist_ok=True)
    destination=args.output_dir/f'abstract-shell_{args.version}_{architecture}.deb'
    with tempfile.TemporaryDirectory(prefix='abstract-package-') as temporary:
        stage_package(Path(temporary)/'root',args.version,architecture)
        subprocess.run(['nice','-n','15','dpkg-deb','--root-owner-group','-Zxz','-z3','--threads-max=1','--build',str(Path(temporary)/'root'),str(destination)],check=True)
    print(destination)
    if args.with_desktop:
        desktop=args.output_dir/f'abstract-desktop_{args.version}_all.deb'
        with tempfile.TemporaryDirectory(prefix='abstract-desktop-package-') as temporary:
            stage_desktop_package(Path(temporary)/'root',args.version)
            subprocess.run(['dpkg-deb','--root-owner-group','--build',str(Path(temporary)/'root'),str(desktop)],check=True)
        print(desktop)
if __name__=='__main__':main()
