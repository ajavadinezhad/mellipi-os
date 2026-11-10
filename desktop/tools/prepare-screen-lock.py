#!/usr/bin/env python3
"""Build pinned upstream swaylock/PAM locally; never install system packages.

Usage: python3 tools/prepare-screen-lock.py [--offline]
Ubuntu/Mint development .debs are downloaded then extracted into the project.
No PAM file, system binary, setuid bit, or global environment is changed.
"""
import argparse,hashlib,json,os,re,shutil,subprocess,sys,tarfile,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.screen-lock-build'
RUNTIME=ROOT/'.lock-runtime'
VERSION='1.8.6'
SOURCE=f'https://github.com/swaywm/swaylock/releases/download/v{VERSION}/swaylock-{VERSION}.tar.gz'
SOURCE_SHA256='a15154348fef852fdb224112d137c393c826478b777f63479beb15e8d3812eaf'
PACKAGES=('meson','ninja-build','libcairo2-dev','libwayland-dev','libwayland-bin','libxkbcommon-dev','wayland-protocols','libpam0g-dev','libpixman-1-dev','libfontconfig-dev','libfreetype-dev','libpng-dev','libxcb1-dev','libxcb-render0-dev','libxcb-shm0-dev','libx11-dev','libxext-dev','libxrender-dev','libxau-dev','libxdmcp-dev','zlib1g-dev','libffi-dev','libbrotli-dev','x11proto-dev','libexpat1-dev')

def run(argv,**kwargs):return subprocess.run([str(a) for a in argv],check=True,**kwargs)
def output(argv,**kwargs):return subprocess.check_output([str(a) for a in argv],text=True,**kwargs).strip()
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--offline',action='store_true');args=parser.parse_args()
    if os.geteuid()==0:parser.error('Run as your normal desktop user; this build needs no sudo')
    for name in ('cc','pkg-config','dpkg-deb','ldd','readelf','nm','patch'):
        if not shutil.which(name):parser.error('Missing '+name+'; install the distribution build tool before retrying')
    packages=BASE/'packages';sysroot=BASE/'sysroot';build=BASE/'build';packages.mkdir(parents=True,exist_ok=True);sysroot.mkdir(exist_ok=True)
    candidates={}
    for path in sorted(packages.glob('*.deb')):
        info=output(['dpkg-deb','-f',path,'Package','Version']).splitlines()
        package=next((line.split(': ',1)[1] for line in info if line.startswith('Package: ')),'')
        version=next((line.split(': ',1)[1] for line in info if line.startswith('Version: ')),'')
        if not package:continue
        previous=candidates.get(package)
        if previous is None or subprocess.run(['dpkg','--compare-versions',version,'gt',previous[1]],check=False).returncode==0:candidates[package]=(path,version)
    missing=[name for name in PACKAGES if name not in candidates]
    if missing:
        if args.offline:parser.error('Offline cache is missing: '+', '.join(missing))
        if not shutil.which('apt-get'):parser.error('Ubuntu/Mint apt-get is required to fetch development packages')
        run(['apt-get','download',*missing],cwd=packages)
        for path in sorted(packages.glob('*.deb')):
            package=output(['dpkg-deb','-f',path,'Package']);version=output(['dpkg-deb','-f',path,'Version'])
            previous=candidates.get(package)
            if previous is None or subprocess.run(['dpkg','--compare-versions',version,'gt',previous[1]],check=False).returncode==0:candidates[package]=(path,version)
    archive=BASE/f'swaylock-{VERSION}.tar.gz'
    if not archive.exists():
        if args.offline:parser.error('Offline cache is missing the pinned upstream source archive')
        with urllib.request.urlopen(SOURCE,timeout=30) as source:data=source.read(2_000_001)
        if len(data)>2_000_000:raise RuntimeError('Unexpectedly large upstream archive')
        archive.write_bytes(data)
    if sha(archive)!=SOURCE_SHA256:raise RuntimeError('Pinned source SHA-256 does not match; refusing to build')
    with tarfile.open(archive) as source:source.extractall(BASE,filter='data')
    # Apply only the optional presentation branch to the pinned upstream source.
    # Authentication/input sources must remain byte-for-byte upstream.
    source_dir=BASE/f'swaylock-{VERSION}'
    auth_files=('pam.c','password.c','password-buffer.c','main.c','seat.c','comm.c')
    auth_hashes={name:sha(source_dir/name) for name in auth_files}
    render_patch=ROOT/'native/swaylock-textbox.patch'
    run(['patch','--batch','--forward','-p1','-i',render_patch],cwd=source_dir)
    shutil.copy2(ROOT/'native/lock-textbox-render.h',source_dir/'include/orbit-lock-textbox.h')
    shutil.copy2(ROOT/'native/lock-status.h',source_dir/'include/orbit-lock-status.h')
    if any(sha(source_dir/name)!=value for name,value in auth_hashes.items()):raise RuntimeError('Presentation patch changed an authentication/input source')
    package_info=[]
    for name in PACKAGES:
        path,version=candidates[name];run(['dpkg-deb','-x',path,sysroot]);package_info.append(dict(name=name,version=version,sha256=sha(path)))
    triplet=output(['cc','-dumpmachine'])
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',triplet):raise RuntimeError('Invalid compiler architecture identifier')
    library_dir=sysroot/'usr/lib'/triplet
    # Development .so links point at the matching host's existing runtime libs.
    for link in library_dir.glob('*.so'):
        if link.is_symlink() and not link.exists():
            host=Path('/usr/lib')/triplet/Path(os.readlink(link)).name
            if host.exists():link.unlink();link.symlink_to(host.resolve())
    for path in sysroot.rglob('*.pc'):
        text=path.read_text().replace('=/usr','='+str(sysroot)+'/usr').replace('=/lib','='+str(sysroot)+'/lib');path.write_text(text)
    env=os.environ.copy();env.pop('LD_LIBRARY_PATH',None)
    env.update(PYTHONPATH=str(sysroot/'usr/lib/python3/dist-packages'),PATH=str(sysroot/'usr/bin')+':'+env.get('PATH',''),PKG_CONFIG_LIBDIR=':'.join(str(p) for p in (library_dir/'pkgconfig',sysroot/'usr/share/pkgconfig',sysroot/'usr/lib/pkgconfig')),LIBRARY_PATH=str(library_dir))
    meson=['/usr/bin/python3',sysroot/'usr/bin/meson']
    setup=[*meson,'setup']
    if build.exists():setup.append('--wipe')
    run([*setup,build,BASE/f'swaylock-{VERSION}','--prefix=/usr','--sysconfdir=/etc','--buildtype=release','-Dpam=enabled','-Dgdk-pixbuf=disabled','-Dman-pages=disabled','-Dc_args='+json.dumps(['-I'+str(sysroot/'usr/include')]),'-Dc_link_args='+json.dumps(['-L'+str(library_dir)])],env=env)
    run(['nice','-n','15',sysroot/'usr/bin/ninja','-C',build,'-j1'],env=env)
    run(['/usr/bin/python3',ROOT/'tools/check-lock-textbox.py'],env=env)
    run(['/usr/bin/python3',ROOT/'tools/check-lock-status.py'],env=env)
    compile_commands=json.loads((build/'compile_commands.json').read_text())
    if not any(Path(row['file']).name=='pam.c' for row in compile_commands) or any(Path(row['file']).name=='shadow.c' for row in compile_commands):raise RuntimeError('PAM authentication was not compiled in')
    stage=BASE/'install-root';run([*meson,'install','-C',build,'--destdir',stage],env=env)
    destination=stage/'usr/bin/swaylock'
    runtime_env=os.environ.copy();runtime_env.pop('LD_LIBRARY_PATH',None);runtime_env.pop('PYTHONPATH',None)
    libraries=output(['ldd',destination],env=runtime_env);dynamic=output(['readelf','-d',destination],env=runtime_env);symbols=output(['nm','-D',destination],env=runtime_env)
    if 'not found' in libraries or 'libpam.so.0' not in libraries or 'pam_authenticate' not in symbols:raise RuntimeError('PAM/runtime library verification failed')
    if str(BASE) in dynamic:raise RuntimeError('Binary retains a private build-directory runtime search path')
    version=output([destination,'--version'],env=runtime_env)
    help_result=subprocess.run([str(destination),'--help'],env=runtime_env,text=True,capture_output=True)
    help_text=help_result.stdout+help_result.stderr
    if help_result.returncode not in (0,1):raise RuntimeError('Locker help probe failed')
    if VERSION not in version or '--ready-fd' not in help_text:raise RuntimeError('Unexpected locker version/options')
    installed=RUNTIME/'bin/swaylock';installed.parent.mkdir(parents=True,exist_ok=True)
    temporary=installed.with_name('.swaylock-render-install')
    try:
        shutil.copy2(destination,temporary);temporary.chmod(0o755);os.replace(temporary,installed)
    finally:
        if temporary.exists():temporary.unlink()
    destination=installed
    manifest=dict(presentationPatch=dict(environment='ORBIT_LOCK_TEXTBOX=1',renderPatchSha256=sha(render_patch),renderHeaderSha256=sha(ROOT/'native/lock-textbox-render.h'),statusHeaderSha256=sha(ROOT/'native/lock-status.h'),liveUpdateSeconds=60,branding='Abstract',keyboardLayout=True,adaptiveHeight=True,networkStatus='bounded read-only carrier, no Internet claim or network identifiers',authenticationSources=auth_hashes),version=VERSION,source=SOURCE,sourceSha256=SOURCE_SHA256,pamEnabled=True,binary=str(destination),binarySha256=sha(destination),binaryBytes=destination.stat().st_size,buildPackages=package_info,linkedLibraries=libraries.splitlines(),versionOutput=version,systemFilesChanged=False)
    (RUNTIME/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({key:manifest[key] for key in ('version','pamEnabled','binary','binaryBytes','sourceSha256','systemFilesChanged')},indent=2))

if __name__=='__main__':main()
