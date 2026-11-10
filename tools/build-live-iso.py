#!/usr/bin/env python3
"""Build a Mellipi-only Ubuntu live/installer ISO inside a disposable QA VM.

Never invoke this tool on a workstation. It refuses non-QEMU QA guests and never
accepts a disk device. Installation choices belong to the interactive installer.
"""
import argparse,contextlib,hashlib,importlib.util,json,os,re,shutil,struct,subprocess,time
from pathlib import Path

ARCHIVE='https://ajavadinezhad.github.io/mellipi-os/apt'
FINGERPRINT='7D0FC30A9F2B9957B2970E3BB6B1D6FE6A4682AF'
CALAMARES_VERSION='3.3.5-0ubuntu4'
CALAMARES_PARTITION_PATH='usr/lib/x86_64-linux-gnu/calamares/modules/partition/libcalamares_viewmodule_partition.so'
CALAMARES_STOCK_MODULE_SHA256='55a6c6a1f0624dff6df59358eb2c77b535f520c525a9ec8c7ae06a9d36414ea8'
BASE_PACKAGES=['ca-certificates','systemd-sysv','udev','dbus','dbus-user-session','sudo','locales','tzdata','keyboard-configuration','console-setup','casper','initramfs-tools','linux-generic','linux-firmware','systemd-resolved','network-manager','calamares','grub-pc-bin','grub-efi-amd64-bin','grub-efi-amd64-signed','shim-signed','sbsigntool','mokutil','grub2-common','efibootmgr','os-prober','rsync','squashfs-tools','cryptsetup','cryptsetup-initramfs','dosfstools','e2fsprogs','parted','python3-yaml','xdg-user-dirs','fonts-dejavu-core','dmz-cursor-theme']

def run(args,**kwargs):
    print('+ '+' '.join(map(str,args)),flush=True)
    return subprocess.run(list(map(str,args)),check=True,**kwargs)

def write(root,name,text,mode=0o644):
    path=root/name.lstrip('/');path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text);path.chmod(mode)

def file_sha256(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def apply_calamares_partition_module(root,args):
    module=args.calamares_partition_module;expected=args.calamares_partition_sha256;metadata=args.calamares_partition_provenance
    if not module or not expected or not metadata:
        raise SystemExit('Image creation requires the validated Calamares GPT-boundary module, its SHA256 and build provenance.')
    module=Path(module);metadata=Path(metadata)
    if module.is_symlink() or metadata.is_symlink() or not module.is_file() or not metadata.is_file():
        raise ValueError('Calamares inputs must be ordinary files, not symbolic links')
    if not 20<=module.stat().st_size<=5_000_000 or metadata.stat().st_size>64_000:
        raise ValueError('Unexpected Calamares module/provenance size')
    with module.open('rb') as stream:header=stream.read(20)
    if header[:6]!=b'\x7fELF\x02\x01' or struct.unpack('<H',header[18:20])[0]!=62:
        raise ValueError('Calamares module must be an amd64 ELF')
    digest=file_sha256(module);provenance=json.loads(metadata.read_text())
    if not isinstance(provenance,dict):raise ValueError('Invalid Calamares build provenance')
    geometry={'GPT_last_usable':50331614,'MSDOS_last_usable':50331647,'default_encryption_only':False}
    patches=provenance.get('patches',{})
    required={'enable-only-present-with-encryption-partitions.patch','calamares-gpt-usable-boundary.patch','calamares-default-encryption-flag.patch'}
    if digest!=expected.lower() or provenance.get('module_sha256')!=digest or provenance.get('module_bytes')!=module.stat().st_size:
        raise ValueError('Calamares module SHA256/size differs from reviewed input')
    if provenance.get('ubuntu_package')!=CALAMARES_VERSION or provenance.get('geometry_regression')!=geometry or not isinstance(patches,dict) or not required.issubset(patches) or not all(isinstance(v,str) and re.fullmatch('[0-9a-f]{64}',v) for v in patches.values()):
        raise ValueError('Calamares source/patch/geometry provenance is incomplete')
    version=chroot(root,'dpkg-query','-W','--showformat=${Version}','calamares',capture_output=True,text=True).stdout.strip()
    if version!=CALAMARES_VERSION:raise ValueError('Calamares module ABI does not match the installed package')
    target=Path(root)/CALAMARES_PARTITION_PATH
    if target.is_symlink() or not target.is_file() or file_sha256(target) not in (CALAMARES_STOCK_MODULE_SHA256,digest):
        raise ValueError('Installed Calamares module differs from the pinned Noble input')
    shutil.copyfile(module,target);target.chmod(0o644)
    assert file_sha256(target)==digest
    return {'module_sha256':digest,'module_bytes':module.stat().st_size,'ubuntu_package':version,'upstream_module_sha256':CALAMARES_STOCK_MODULE_SHA256,'patches':patches,'geometry_regression':geometry,'sdk_versions':provenance.get('sdk_versions',{}),'only_partition_module_replaced':True}

def guard(work):
    if os.geteuid()!=0:raise SystemExit('Run with sudo inside the disposable Mellipi build VM only.')
    if Path('/etc/hostname').read_text().strip()!='abstract-qa' or not Path('/home/abstract/qa-guest.py').is_file():raise SystemExit('Refusing: this is not the named disposable QA guest.')
    virt=subprocess.check_output(['systemd-detect-virt'],text=True).strip()
    if virt not in ('kvm','qemu'):raise SystemExit('Refusing: QEMU/KVM guest required.')
    raw=Path(work)
    if raw.is_symlink():raise SystemExit('Refusing a symlink work directory.')
    work=raw.resolve()
    if not work.is_relative_to('/home/abstract/abstract-iso') or work==Path('/home/abstract/abstract-iso'):raise SystemExit('Use a dedicated directory beneath /home/abstract/abstract-iso/.')
    for parent in (work,*work.parents):
        if parent==Path('/'):break
        if parent.is_symlink():raise SystemExit('Symlink in work directory.')
    work.mkdir(parents=True,exist_ok=True);return work

def apt_sources(root,mirror,security):
    write(root,'etc/apt/sources.list',f'deb {mirror.rstrip("/")} noble main restricted universe multiverse\ndeb {mirror.rstrip("/")} noble-updates main restricted universe multiverse\ndeb {security.rstrip("/")} noble-security main restricted universe multiverse\n')

def chroot(root,*args,**kwargs):
    env=dict(os.environ,DEBIAN_FRONTEND='noninteractive',SYSTEMD_OFFLINE='1',RUNLEVEL='1',LC_ALL='C.UTF-8')
    # Build-network settings are explicit arguments, never inherited proxies.
    for key in list(env):
        if 'proxy' in key.lower() or key.startswith(('GH_','GITHUB_','ORBIT_')):env.pop(key,None)
    return run(['chroot',root,'/usr/bin/env','-i',*[f'{k}={env[k]}' for k in ('DEBIAN_FRONTEND','SYSTEMD_OFFLINE','RUNLEVEL','LC_ALL')],'PATH=/usr/sbin:/usr/bin:/sbin:/bin',*args],**kwargs)

@contextlib.contextmanager
def mounts(root):
    active=[]
    try:
        for name in ('dev','proc','sys'):(root/name).mkdir(exist_ok=True)
        run(['mount','--rbind','/dev',root/'dev']);active.append(root/'dev');run(['mount','--make-rslave',root/'dev'])
        run(['mount','-t','proc','proc',root/'proc']);active.append(root/'proc')
        run(['mount','--rbind','/sys',root/'sys']);active.append(root/'sys');run(['mount','--make-rslave',root/'sys'])
        yield
    finally:
        for path in reversed(active):run(['umount','--recursive',path])

def bootstrap(work,args):
    root=work/'rootfs'
    if (work/'bootstrap-origin.json').is_file() and (root/'etc/debian_version').is_file():
        print('Using previously bootstrapped clean target rootfs.',flush=True);return root
    if root.exists() and any(root.iterdir()):raise SystemExit('Incomplete target exists: inspect it before retrying; no automatic deletion.')
    run(['debootstrap','--arch=amd64','--variant=minbase','--components=main,restricted,universe,multiverse','--include=ca-certificates','noble',root,args.mirror])
    write(work,'bootstrap-origin.json',json.dumps({'method':'debootstrap-minbase','suite':'noble','architecture':'amd64','created_at':int(time.time()),'copied_builder_filesystem':False},indent=2)+'\n')
    return root

def configure_installer(root,version):
    settings='''modules-search: [ local ]
instances:
  - id: abstracttargetcheck
    module: shellprocess
    config: abstracttargetcheck.conf
  - id: abstractcleanup
    module: shellprocess
    config: abstractcleanup.conf
  - id: abstractbootcleanup
    module: shellprocess
    config: abstractbootcleanup.conf
sequence:
  - show: [ welcome, locale, keyboard, partition, users, summary ]
  - exec: [ partition, mount, shellprocess@abstracttargetcheck, unpackfs, machineid, fstab, locale, keyboard, localecfg, shellprocess@abstractcleanup, users, displaymanager, networkcfg, hwclock, initramfscfg, grubcfg, packages, initramfs, bootloader, shellprocess@abstractbootcleanup, umount ]
  - show: [ finished ]
branding: abstract
prompt-install: true
dont-chroot: false
oem-setup: false
disable-cancel: false
'''
    write(root,'etc/calamares/settings.conf',settings)
    configs={
    'welcome.conf':'''showSupportUrl: true
showKnownIssuesUrl: true
showReleaseNotesUrl: false
showDonateUrl: false
requirements:
  requiredStorage: 20.0
  requiredRam: 2.0
  check: [ storage, ram, root, screen ]
  required: [ storage, ram, root ]
geoip: { style: none }
''',
    'locale.conf':'region: "Etc"\nzone: "UTC"\ngeoip: { style: none }\n',
    'keyboard.conf':'{}\n',
    'partition.conf':'''efi: { mountPoint: /boot/efi, recommendedSize: 512MiB, minimumSize: 300MiB, label: EFI }
userSwapChoices: [ file, none ]
initialSwapChoice: file
initialPartitioningChoice: none
allowManualPartitioning: true
defaultFileSystemType: ext4
availableFileSystemTypes: [ ext4 ]
partitionLayout:
  - name: rootfs
    filesystem: ext4
    mountPoint: /
    size: "100%"
    minSize: "12G"
luksGeneration: luks1
''',
    'users.conf':'''defaultGroups: [ adm, audio, video, plugdev, netdev, sudo ]
autologinGroup: ""
setRootPassword: false
doAutologin: false
doReusePassword: false
passwordRequirements: { minLength: 1, maxLength: 256 }
allowWeakPasswords: true
allowWeakPasswordsDefault: false
user: { shell: /bin/bash, forbidden_names: [ root, nobody ] }
''',
    'unpackfs.conf':'unpack:\n  - source: /cdrom/casper/filesystem.squashfs\n    sourcefs: squashfs\n    destination: ""\n',
    'machineid.conf':'systemd: true\ndbus: true\ndbus-symlink: true\n',
    'mount.conf':'''extraMounts:
  - { device: proc, fs: proc, mountPoint: /proc }
  - { device: sys, fs: sysfs, mountPoint: /sys }
  - { device: /dev, mountPoint: /dev, options: [ bind ] }
  - { device: tmpfs, fs: tmpfs, mountPoint: /run }
  - { device: /run/udev, mountPoint: /run/udev, options: [ bind ] }
  - { device: efivarfs, fs: efivarfs, mountPoint: /sys/firmware/efi/efivars, efi: true }
  - { device: /run/systemd/resolve, mountPoint: /run/systemd/resolve, options: [ bind ] }
mountOptions:
  - { filesystem: default, options: [ defaults ] }
''',
    'fstab.conf':'''crypttabOptions: luks,keyscript=/bin/cat
tmpOptions:
  default: { tmpfs: false, options: "" }
  ssd: { tmpfs: true, options: "defaults,noatime,mode=1777" }
''',
    'localecfg.conf':'{}\n',
    'displaymanager.conf':'''displaymanagers: [ lightdm ]
defaultDesktopEnvironment: { executable: /usr/bin/mellipi-session, desktopFile: abstract }
basicSetup: false
sysconfigSetup: false
lightdm: { preferred_greeters: [ lightdm-gtk-greeter.desktop ] }
''',
    'networkcfg.conf':'{}\n',
    'hwclock.conf':'{}\n',
    'packages.conf':'''backend: apt
skip_if_no_internet: false
update_db: false
update_system: false
operations:
  - remove: [ casper, calamares ]
''',
    'initramfscfg.conf':'{}\n',
    'grubcfg.conf':'overwrite: false\ndefaults: { GRUB_ENABLE_CRYPTODISK: true }\n',
    'initramfs.conf':'kernel: all\nbe_unsafe: false\n',
    'bootloader.conf':'''efiBootLoader: grub
efiBootloaderId: ubuntu
grubInstall: /usr/lib/abstract/iso-grub-install
grubMkconfig: grub-mkconfig
grubCfg: /boot/grub/grub.cfg
grubProbe: grub-probe
efiBootMgr: efibootmgr
installEFIFallback: false
''',
    'finished.conf':'restartNowMode: user-unchecked\nrestartNowCommand: systemctl -i reboot\n',
    'umount.conf':'emergency: true\n',
    'abstracttargetcheck.conf':'''dontChroot: true
timeout: 10
script:
  - '/usr/lib/abstract/iso-check-target "${ROOT}"'
i18n: { name: "Check installation partition" }
''',
    'abstractcleanup.conf':'''dontChroot: false
timeout: 30
script:
  - /usr/lib/abstract/iso-target-cleanup
''',
    'abstractbootcleanup.conf':'''dontChroot: false
timeout: 10
script:
  - '/usr/bin/rm -f /usr/lib/abstract/iso-grub-install'
'''
    }
    for name,text in configs.items():write(root,'etc/calamares/modules/'+name,text)
    write(root,'usr/lib/abstract/iso-grub-install',r'''#!/usr/bin/python3 -I
"""Calamares-only signed Ubuntu UEFI install; ordinary BIOS install remains."""
import os,re,shutil,stat,subprocess,sys
from pathlib import Path

def plan(arguments):
    if '--target=i386-pc' in arguments:
        devices=[a for a in arguments if a.startswith('/dev/')]
        if len(devices)!=1 or '..' in devices[0].split('/') or not re.fullmatch(r'/dev/[A-Za-z0-9_./:+-]+',devices[0]):raise ValueError('Invalid selected BIOS disk')
        if any(a not in ('--target=i386-pc','--recheck','--force',devices[0]) for a in arguments):raise ValueError('Unexpected BIOS installer argument')
        return ['/usr/sbin/grub-install',*arguments],devices[0]
    expected={'--target=x86_64-efi','--efi-directory=/boot/efi','--bootloader-id=ubuntu','--force'}
    if len(arguments)!=4 or set(arguments)!=expected:raise ValueError('Unexpected signed UEFI installer arguments')
    # Never use Calamares --force as an escape from Secure Boot enforcement.
    return ['/usr/sbin/grub-install','--target=x86_64-efi','--efi-directory=/boot/efi','--bootloader-id=ubuntu','--uefi-secure-boot'],None

def main():
    if os.geteuid()!=0 or not Path('/etc/mellipi-release').is_file():raise SystemExit('Run only inside the selected Mellipi installation target')
    command,device=plan(sys.argv[1:])
    if device:
        if not stat.S_ISBLK(os.stat(device).st_mode):raise ValueError('The selected BIOS target is not a block device')
        return subprocess.run(command,check=True).returncode
    esp=Path('/boot/efi')
    if esp.is_symlink() or not os.path.ismount(esp):raise ValueError('The selected EFI system partition is not mounted')
    sources={'bootx64.efi':Path('/usr/lib/shim/shimx64.efi.signed.latest'),'grubx64.efi':Path('/usr/lib/grub/x86_64-efi-signed/grubx64.efi.signed'),'mmx64.efi':Path('/usr/lib/shim/mmx64.efi')}
    if not sources['bootx64.efi'].is_file():sources['bootx64.efi']=Path('/usr/lib/shim/shimx64.efi.signed')
    for source in sources.values():
        if not source.is_file():raise ValueError('A signed Ubuntu boot component is missing')
        check=subprocess.run(['/usr/bin/sbverify','--list',str(source)],capture_output=True,text=True,check=True)
        if 'signature 1' not in check.stdout:raise ValueError('An EFI input is unsigned')
    subprocess.run(command,check=True)
    # Signed Ubuntu GRUB has a fixed EFI/ubuntu prefix. Its normal distro
    # update scripts maintain that directory; a separate fallback starts shim.
    directory=esp/'EFI/ubuntu';fallback=esp/'EFI/BOOT';fallback.mkdir(parents=True,exist_ok=True)
    config=directory/'grub.cfg'
    if not config.is_file():raise ValueError('Signed GRUB did not create its root-filesystem configuration')
    for name,source in sources.items():shutil.copyfile(source,fallback/name)
    shutil.copyfile(config,fallback/'grub.cfg')
    return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,subprocess.SubprocessError) as error:raise SystemExit('Signed bootloader installation failed: '+str(error))
''',0o755)
    write(root,'usr/lib/abstract/iso-target-cleanup','''#!/bin/sh
set -eu
# Calamares invokes this inside its selected target, never in the live system.
test -f /etc/calamares/settings.conf
test -x /usr/bin/mellipi-session
rm -f /usr/share/initramfs-tools/scripts/casper-bottom/99mellipi-live /etc/initramfs-tools/conf.d/mellipi-live
rm -f /usr/share/applications/mellipi-install.desktop /usr/share/applications/calamares.desktop
rm -f /etc/skel/Desktop/mellipi-install.desktop /usr/bin/mellipi-install /usr/lib/abstract/iso-installer-root /usr/lib/abstract/iso-check-target
rm -f /etc/sudoers.d/casper /etc/lightdm/lightdm.conf
rm -f /etc/ssh/ssh_host_* /var/lib/systemd/random-seed
: > /etc/machine-id
rm -f /var/lib/dbus/machine-id
ln -sf /etc/machine-id /var/lib/dbus/machine-id
rm -rf /etc/calamares
rm -f /usr/lib/abstract/iso-target-cleanup
''',0o755)
    write(root,'usr/lib/abstract/iso-check-target','''#!/usr/bin/python3
"""Refuse filesystem copies unless Calamares mounted an actual target partition."""
import json,os,stat,subprocess,sys
from pathlib import Path

def check_target(path):
    target=str(Path(path).resolve(strict=True))
    data=json.loads(subprocess.check_output(['/usr/bin/findmnt','--json','--mountpoint',target,'--output','FSTYPE,SOURCE,TARGET'],text=True))
    filesystems=data.get('filesystems',[])
    if len(filesystems)!=1:raise ValueError('Target partition is not mounted')
    mount=filesystems[0]
    if mount.get('target')!=target or mount.get('fstype')!='ext4' or not stat.S_ISBLK(os.stat(mount.get('source','')).st_mode):
        raise ValueError('Target is not a mounted ext4 partition')

def main():
    if os.geteuid()!=0 or len(sys.argv)!=2 or 'boot=casper' not in Path('/proc/cmdline').read_text().split():
        raise SystemExit('Run this check from the live installer.')
    try:check_target(sys.argv[1])
    except (OSError,ValueError,subprocess.SubprocessError):
        raise SystemExit('No mounted installation partition was found. Choose a root (/) partition and try again.')

if __name__=='__main__':main()
''',0o755)
    branding=f'''componentName: abstract
welcomeStyleCalamares: false
windowExpanding: normal
windowSize: 900px,620px
windowPlacement: center
sidebar: widget
navigation: widget
slideshow: [ abstract.svg ]
strings:
  productName: Mellipi
  shortProductName: Mellipi
  version: "{version}"
  shortVersion: "{version}"
  versionedName: "Mellipi {version}"
  shortVersionedName: "Mellipi {version}"
  bootloaderEntryName: Mellipi
  productUrl: https://ajavadinezhad.github.io/mellipi-os/
  supportUrl: https://github.com/ajavadinezhad/mellipi-os/issues
  knownIssuesUrl: https://github.com/ajavadinezhad/mellipi-os/issues
images:
  productIcon: abstract.svg
  productLogo: abstract.svg
  productWelcome: abstract.svg
style:
  SidebarBackground: "#17221f"
  SidebarText: "#f0f3eb"
  SidebarBackgroundCurrent: "#d1ebbb"
  SidebarTextCurrent: "#17221f"
uploadServer: {{ type: none }}
'''
    write(root,'etc/calamares/branding/abstract/branding.desc',branding)
    write(root,'etc/calamares/branding/abstract/abstract.svg','<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="16" fill="#111a14"/><path d="m32 11 20 21-20 21L12 32Z" fill="none" stroke="#b8d893" stroke-width="3"/><path d="M32 12v40M22 32h20" stroke="#b8d893" stroke-width="3"/></svg>\n')

def install(work,root,args):
    apt_sources(root,args.mirror,args.security_mirror)
    write(root,'etc/apt/apt.conf.d/80abstract-build','Acquire::ForceIPv4 "true";\nAcquire::Retries "2";\nAcquire::Languages "none";\nAcquire::http::Timeout "60";\nAcquire::https::Timeout "60";\n')
    write(root,'usr/sbin/policy-rc.d','#!/bin/sh\nexit 101\n',0o755)
    resolv=root/'etc/resolv.conf'
    if resolv.is_symlink():resolv.unlink()
    shutil.copyfile('/etc/resolv.conf',resolv)
    key=root/'etc/apt/keyrings/mellipi-archive-keyring.gpg';key.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(args.keyring,key)
    info=subprocess.check_output(['gpg','--batch','--with-colons','--show-keys',str(key)],text=True)
    assert len([r for r in info.splitlines() if r.startswith('pub:')])==1
    assert next(r.split(':')[9] for r in info.splitlines() if r.startswith('fpr:'))==FINGERPRINT
    key.chmod(0o644)
    write(root,'etc/apt/sources.list.d/mellipi.sources',f'Types: deb\nURIs: {ARCHIVE}\nSuites: noble\nComponents: main\nArchitectures: amd64\nSigned-By: /etc/apt/keyrings/mellipi-archive-keyring.gpg\n')
    (root/'etc/apt/sources.list.d/abstract.sources').unlink(missing_ok=True)
    copied=[];package_inputs={}
    for name,package in [('mellipi-shell',args.core_deb),('mellipi-desktop',args.desktop_deb)]:
        found=subprocess.check_output(['dpkg-deb','-f',str(package),'Package'],text=True).strip();assert found==name
        version=subprocess.check_output(['dpkg-deb','-f',str(package),'Version'],text=True).strip();assert version==args.version
        arch=subprocess.check_output(['dpkg-deb','-f',str(package),'Architecture'],text=True).strip();assert arch==('amd64' if name=='mellipi-shell' else 'all')
        with Path(package).open('rb') as stream:package_inputs[name]={'version':version,'architecture':arch,'sha256':hashlib.file_digest(stream,'sha256').hexdigest()}
        target=root/'tmp'/Path(package).name;target.parent.mkdir(exist_ok=True);shutil.copyfile(package,target);copied.append('/tmp/'+target.name)
    with mounts(root):
        # The new project endpoint is enrolled in the image; local builds use
        # only signed Ubuntu indexes and the explicitly verified .deb pair.
        project_source=root/'etc/apt/sources.list.d/mellipi.sources'
        project_source.rename(project_source.with_suffix('.pending'))
        chroot(root,'apt-get','-o','APT::Update::Error-Mode=any','update')
        chroot(root,'apt-get','-y','--no-install-recommends','install',*BASE_PACKAGES,*copied)
        # Private QA candidates can be rebuilt at the same unpublished version.
        # Refresh only the local pair, never every base/firmware package.
        chroot(root,'apt-get','-y','--no-install-recommends','--reinstall','install',*copied)
        chroot(root,'update-alternatives','--set','x-terminal-emulator','/usr/bin/foot')
        write(root,'etc/locale.gen','en_US.UTF-8 UTF-8\n');chroot(root,'locale-gen')
        chroot(root,'update-locale','LANG=en_US.UTF-8')
        project_source.with_suffix('.pending').rename(project_source)
        configure_installer(root,args.version)
        configure_live(root,args.version)
        chroot(root,'update-initramfs','-u','-k','all')
        chroot(root,'apt-get','clean')
    for name in copied:(root/name.lstrip('/')).unlink(missing_ok=True)
    (root/'usr/sbin/policy-rc.d').unlink(missing_ok=True)
    apt_sources(root,'https://archive.ubuntu.com/ubuntu','https://security.ubuntu.com/ubuntu')
    (root/'etc/apt/apt.conf.d/80abstract-build').unlink(missing_ok=True)
    resolv.unlink(missing_ok=True);resolv.symlink_to('/run/systemd/resolve/stub-resolv.conf')
    for path in (root/'var/log').rglob('*'):
        if path.is_file() and not path.is_symlink():path.write_bytes(b'')
    for folder in ('tmp','var/tmp','var/lib/apt/lists'):
        for path in (root/folder).iterdir():
            if path.is_dir() and not path.is_symlink():shutil.rmtree(path)
            else:path.unlink()
    (root/'etc/machine-id').write_text('')
    (root/'var/lib/dbus/machine-id').unlink(missing_ok=True);(root/'var/lib/dbus/machine-id').symlink_to('/etc/machine-id')
    (root/'var/lib/systemd/random-seed').unlink(missing_ok=True)
    (work/'installed.json').write_text(json.dumps({'version':args.version,'rootfs':str(root),'base':'Ubuntu 24.04 noble minbase','only_desktop':'Mellipi','package_inputs':package_inputs},indent=2)+'\n')

def configure_live(root,version):
    for name in ('etc/abstract-release','etc/initramfs-tools/conf.d/abstract-live','usr/share/initramfs-tools/scripts/casper-bottom/99abstract-live','usr/bin/abstract-install','usr/share/applications/abstract-install.desktop','etc/skel/Desktop/abstract-install.desktop'):
        (root/name).unlink(missing_ok=True)
    write(root,'etc/hostname','mellipi-live\n')
    write(root,'etc/hosts','127.0.0.1 localhost\n127.0.1.1 mellipi-live\n::1 localhost ip6-localhost ip6-loopback\n')
    write(root,'etc/casper.conf','export USERNAME="mellipi"\nexport USERFULLNAME="Mellipi live session"\nexport HOST="mellipi-live"\nexport BUILD_SYSTEM="Ubuntu"\nexport FLAVOUR="Mellipi"\n')
    write(root,'etc/initramfs-tools/conf.d/mellipi-live','export CASPER_GENERATE_UUID=1\n')
    write(root,'etc/mellipi-release',f'Mellipi {version}\nBase: Ubuntu 24.04 noble\n')
    write(root,'etc/lightdm/lightdm.conf.d/50-abstract-session.conf','[Seat:*]\nuser-session=abstract\nautologin-session=abstract\nallow-guest=false\n')
    write(root,'etc/X11/default-display-manager','/usr/sbin/lightdm\n')
    write(root,'etc/NetworkManager/conf.d/90-abstract-managed.conf','[ifupdown]\nmanaged=true\n[keyfile]\nunmanaged-devices=\n')
    write(root,'etc/default/grub','GRUB_DEFAULT=0\nGRUB_TIMEOUT=3\nGRUB_DISTRIBUTOR="Mellipi"\nGRUB_CMDLINE_LINUX_DEFAULT="quiet"\nGRUB_CMDLINE_LINUX=""\n')
    for link,target in [('etc/systemd/system/default.target','/lib/systemd/system/graphical.target'),('etc/systemd/system/display-manager.service','/lib/systemd/system/lightdm.service')]:
        path=root/link;path.parent.mkdir(parents=True,exist_ok=True);path.unlink(missing_ok=True);path.symlink_to(target)
    prefs={'pins':['org.codeberg.dnkl.foot.desktop','thunar.desktop','org.xfce.mousepad.desktop','org.gnome.Epiphany.desktop'],'density':'compact','themePreset':'forest','mode':'dark','darkLevel':'normal','accent':'#b8d893','backgroundColor':'#111a14','wallpaper':'theme-forest','taskbarLength':'fit','taskbarFloating':True}
    write(root,'etc/skel/.config/abstract/settings.json',json.dumps(prefs)+'\n')
    # This runs only from Casper at live boot; the installed user keeps normal lock defaults.
    hook='''#!/bin/sh
PREREQ=""
case "$1" in prereqs) echo "$PREREQ"; exit 0;; esac
. /scripts/casper-functions
mkdir -p "/root/home/$USERNAME/.config/abstract"
cat > "/root/home/$USERNAME/.config/abstract/settings.json" <<'EOF'
'''+json.dumps(dict(prefs,idleLockEnabled=False,displayOffMinutes=0,lockBeforeSleep=False))+'''
EOF
chroot /root chown -R "$USERNAME:$USERNAME" "/home/$USERNAME/.config/abstract"
# A password-free live account must not enter a locker which ignores empty
# passwords. This is a Casper overlay change only: installation unpacks the
# original, unmodified binary from the read-only filesystem.squashfs.
cat > /root/usr/lib/abstract/.lock-runtime/bin/swaylock <<'LIVELOCK'
#!/bin/sh
echo 'Locking is unavailable in the password-free live session.' >&2
exit 1
LIVELOCK
chmod 0755 /root/usr/lib/abstract/.lock-runtime/bin/swaylock
'''
    write(root,'usr/share/initramfs-tools/scripts/casper-bottom/99mellipi-live',hook,0o755)
    write(root,'usr/bin/mellipi-install','''#!/bin/sh
set -eu
case " $(cat /proc/cmdline) " in *" boot=casper "*) ;; *) echo 'Run the installer from the Mellipi live USB.' >&2; exit 1;; esac
exec sudo -- /usr/lib/abstract/iso-installer-root "${XDG_RUNTIME_DIR:?Start the installer from the live desktop}" "${WAYLAND_DISPLAY:?Start the installer from the live desktop}"
''',0o755)
    write(root,'usr/lib/abstract/iso-installer-root','''#!/usr/bin/python3
"""Run the live installer on its user's Wayland display, with private root state."""
import os,stat,subprocess,sys,tempfile
from pathlib import Path

def display_socket(runtime,display,uid):
    directory=Path(runtime)
    if uid<1000 or directory!=Path('/run/user')/str(uid):
        raise ValueError('Invalid live-session runtime directory')
    info=directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=uid or info.st_mode&0o077:
        raise ValueError('Unsafe live-session runtime directory')
    socket=Path(display) if Path(display).is_absolute() else directory/display
    if socket.parent!=directory or socket.name in ('','.','..'):
        raise ValueError('Invalid live-session display')
    info=socket.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid!=uid:
        raise ValueError('The live-session display is unavailable')
    return str(socket)

def main():
    if os.geteuid()!=0 or len(sys.argv)!=3 or 'boot=casper' not in Path('/proc/cmdline').read_text().split():
        raise SystemExit('Start Install Mellipi from the live desktop.')
    try:socket=display_socket(sys.argv[1],sys.argv[2],int(os.environ.get('SUDO_UID','-1')))
    except (OSError,ValueError):raise SystemExit('The live desktop display is unavailable.')
    with tempfile.TemporaryDirectory(prefix='mellipi-installer-',dir='/run') as runtime:
        os.chmod(runtime,0o700)
        environment=dict(os.environ)
        for key in ('DISPLAY','XAUTHORITY','DBUS_SESSION_BUS_ADDRESS','QT_PLUGIN_PATH','QML2_IMPORT_PATH','PYTHONPATH','LD_LIBRARY_PATH'):
            environment.pop(key,None)
        environment.update(HOME='/root',XDG_RUNTIME_DIR=runtime,WAYLAND_DISPLAY=socket,QT_QPA_PLATFORM='wayland',QT_WAYLAND_SHELL_INTEGRATION='xdg-shell',XDG_CONFIG_DIRS='/etc/xdg',XDG_DATA_DIRS='/usr/local/share:/usr/share')
        return subprocess.call(['/usr/bin/calamares'],env=environment,cwd='/')

if __name__=='__main__':sys.exit(main())
''',0o755)
    desktop='[Desktop Entry]\nType=Application\nName=Install Mellipi\nComment=Choose a disk and install Mellipi on this computer\nExec=/usr/bin/mellipi-install\nIcon=system-software-install\nTerminal=false\nCategories=System;\nStartupWMClass=calamares\n'
    write(root,'usr/share/applications/mellipi-install.desktop',desktop)
    write(root,'etc/skel/Desktop/mellipi-install.desktop',desktop,0o755)
    (root/'usr/share/applications/calamares.desktop').unlink(missing_ok=True)

def image(work,root,args):
    mounted=subprocess.check_output(['findmnt','-rn','-o','TARGET'],text=True).splitlines()
    assert not any(p==str(root) or p.startswith(str(root)+'/') for p in mounted),'Unmount the target rootfs before imaging.'
    calamares_override=apply_calamares_partition_module(root,args)
    target=work/'image';(target/'casper').mkdir(parents=True,exist_ok=True);(target/'boot/grub').mkdir(parents=True,exist_ok=True)
    users=[line.split(':')[0] for line in (root/'etc/passwd').read_text().splitlines() if 1000<=int(line.split(':')[2])<65534]
    assert not users,users
    assert not (root/'home/abstract').exists()
    assert not (root/'usr/sbin/sshd').exists()
    sessions=sorted(p.name for p in (root/'usr/share/wayland-sessions').glob('*.desktop'))
    other=list((root/'usr/share/xsessions').glob('*.desktop'))
    # The sole normal desktop is Mellipi. Its optional authenticated recovery
    # terminal is an Xorg escape hatch, not another desktop environment.
    assert sessions==['abstract.desktop'] and sorted(p.name for p in other)==['mellipi-recovery.desktop'],(sessions,other)
    for p in (root/'etc/apt').rglob('*'):
        if p.is_file() and not p.is_symlink():assert b'10.0.2.2' not in p.read_bytes() and b'127.0.0.1' not in p.read_bytes(),p
    assert not any(root.rglob('id_ed25519')) and not any(root.rglob('id_rsa'))
    versions=[p.name.removeprefix('vmlinuz-') for p in (root/'boot').glob('vmlinuz-*')];assert versions
    kernel=subprocess.check_output(['sort','-V'],input='\n'.join(versions)+'\n',text=True).splitlines()[-1]
    shutil.copyfile(root/'boot'/('vmlinuz-'+kernel),target/'casper/vmlinuz');shutil.copyfile(root/'boot'/('initrd.img-'+kernel),target/'casper/initrd')
    audit=root/'tmp/abstract-initrd-audit'
    if audit.exists():raise SystemExit('Inspect the existing initrd audit before retrying.')
    chroot(root,'unmkinitramfs','/boot/initrd.img-'+kernel,'/tmp/abstract-initrd-audit')
    identifiers=list(audit.rglob('uuid.conf'));assert len(identifiers)==1,identifiers
    identifier=identifiers[0].read_text().strip();assert re.fullmatch(r'[a-fA-F0-9-]{36}',identifier)
    write(target,'.disk/casper-uuid-generic',identifier+'\n')
    write(target,'.disk/info','Mellipi '+args.version+' Ubuntu noble amd64 live/installer\n')
    shutil.rmtree(audit)
    write(target,'boot/grub/grub.cfg',f'''set default=0
set timeout=5
menuentry "Try or install Mellipi {args.version}" {{
    linux /casper/vmlinuz boot=casper quiet noprompt noeject ---
    initrd /casper/initrd
}}
menuentry "Restart" {{ reboot }}
menuentry "Power off" {{ halt }}
''')
    with (target/'casper/filesystem.manifest').open('w') as output:
        chroot(root,'dpkg-query','-W','--showformat=${Package} ${Version}\n',stdout=output)
    manifest=(target/'casper/filesystem.manifest').read_text();assert 'mellipi-shell ' in manifest
    (target/'casper/filesystem.manifest-desktop').write_text('\n'.join(line for line in manifest.splitlines() if not line.startswith(('casper ','calamares ')))+'\n')
    size=int(subprocess.check_output(['du','-sx','--block-size=1',str(root)],text=True).split()[0]);write(target,'casper/filesystem.size',str(size)+'\n')
    squash=target/'casper/filesystem.squashfs'
    if squash.exists():raise SystemExit('Refusing to overwrite an existing squashfs; preserve or explicitly remove your prior unpublished build.')
    run(['mksquashfs',root,squash,'-comp','zstd','-Xcompression-level','6','-b','1M','-processors','1','-mem','512M','-noappend','-no-progress'])
    sums=[]
    for path in sorted(target.rglob('*')):
        if path.is_file():
            with path.open('rb') as stream:value=hashlib.file_digest(stream,'md5').hexdigest()
            sums.append(value+'  ./'+str(path.relative_to(target)))
    write(target,'md5sum.txt','\n'.join(sums)+'\n')
    output=work/f'mellipi-{args.version}-noble-amd64.iso'
    if output.exists():raise SystemExit('Refusing to overwrite an existing ISO.')
    secure_report=None
    if getattr(args,'unsigned_efi',False):
        run(['grub-mkrescue','-o',output,target,'-V','MELLIPI_'+args.version.replace('.','_')])
    else:
        # Keep the unsigned intermediate private; only the signed-chain image
        # becomes the versioned release candidate. No local keys are enrolled.
        helper=Path(__file__).resolve().with_name('secure-boot-image.py')
        if not helper.is_file():raise SystemExit('Copy secure-boot-image.py alongside the ISO builder before image creation')
        unsigned=work/('mellipi-'+args.version+'-unsigned-build.iso')
        boot_work=work/('secure-boot-'+args.version)
        if unsigned.exists() or boot_work.exists():raise SystemExit('Preserve/inspect previous private boot-image inputs before retrying')
        run(['grub-mkrescue','-o',unsigned,target,'-V','MELLIPI_'+args.version.replace('.','_')])
        boot_work.mkdir(mode=0o700)
        spec=importlib.util.spec_from_file_location('mellipi_secure_boot_image',helper)
        boot=importlib.util.module_from_spec(spec);spec.loader.exec_module(boot)
        secure_report=boot.build(unsigned,output,root,boot_work)
        unsigned.unlink()
    with output.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    report={'compression':{'format':'zstd','level':6,'processors':1,'memory_mib':512},'iso':output.name,'bytes':output.stat().st_size,'sha256':digest,'kernel':kernel,'base':'debootstrap Ubuntu24.04 noble minbase','only_desktop':'Mellipi','user_accounts_embedded':False,'ssh_server_embedded':False,'secure_boot':'signed Ubuntu EFI chain; actual firmware acceptance required' if secure_report else 'unsupported; explicitly requested unsigned GRUB rescue loader','secure_boot_tested':False,'boot_tested':False,'installation_tested':False,'built_inside_disposable_guest':True,'package_inputs':json.loads((work/'installed.json').read_text()).get('package_inputs',{})}
    if secure_report:report['secure_boot_build']=secure_report
    report['calamares_partition_override']=calamares_override
    write(work,'iso-build-report.json',json.dumps(report,indent=2)+'\n');write(work,'SHA256SUMS',digest+'  '+output.name+'\n');print(json.dumps(report),flush=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--workdir',type=Path,required=True);parser.add_argument('--core-deb',type=Path,required=True);parser.add_argument('--desktop-deb',type=Path,required=True);parser.add_argument('--keyring',type=Path,required=True);parser.add_argument('--version',default='0.1.9');parser.add_argument('--mirror',default='https://archive.ubuntu.com/ubuntu');parser.add_argument('--security-mirror',default='https://security.ubuntu.com/ubuntu');parser.add_argument('--phase',choices=('bootstrap','install','image','all'),default='all');parser.add_argument('--unsigned-efi',action='store_true',help='Build an explicitly unsigned development ISO; Secure Boot will reject it')
    parser.add_argument('--calamares-partition-module',type=Path);parser.add_argument('--calamares-partition-sha256');parser.add_argument('--calamares-partition-provenance',type=Path);args=parser.parse_args()
    module_inputs=(args.calamares_partition_module,args.calamares_partition_sha256,args.calamares_partition_provenance)
    if (any(module_inputs) and not all(module_inputs)) or (args.phase in ('image','all') and not all(module_inputs)):
        parser.error('Image creation requires --calamares-partition-module, --calamares-partition-sha256 and --calamares-partition-provenance together')
    if args.calamares_partition_sha256 and not re.fullmatch('[0-9a-fA-F]{64}',args.calamares_partition_sha256):parser.error('Use the complete reviewed Calamares module SHA256')
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',args.version):parser.error('Use a numeric release version')
    for value in (args.mirror,args.security_mirror):
        if not re.fullmatch(r'https?://[A-Za-z0-9.:-]+/[A-Za-z0-9/._~-]+',value):parser.error('Mirror must be a plain HTTP(S) public or VM-cache URL without credentials')
    work=guard(args.workdir);root=work/'rootfs'
    if args.phase in ('bootstrap','all'):root=bootstrap(work,args)
    if args.phase in ('install','all'):
        assert (root/'etc/debian_version').is_file();install(work,root,args)
    if args.phase in ('image','all'):
        assert (work/'installed.json').is_file();image(work,root,args)
if __name__=='__main__':main()
