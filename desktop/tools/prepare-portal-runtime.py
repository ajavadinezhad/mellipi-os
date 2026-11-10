#!/usr/bin/env python3
"""Build pinned xdpw with a minimal SHM compatibility fix, locally only.

No system package, D-Bus activation file or running portal service is changed.
Uses the already prepared native-DRM and screen-lock development sysroots.
"""
import argparse,hashlib,json,os,re,shutil,subprocess,tarfile,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'.portal-build';RUNTIME=ROOT/'.portal-runtime'
VERSION='0.7.1'
SOURCE='https://github.com/emersion/xdg-desktop-portal-wlr/releases/download/v0.7.1/xdg-desktop-portal-wlr-0.7.1.tar.gz'
SOURCE_SHA256='eec6e4be808e1a445e677dba1e20e5acb2f091825f5ff4c6ac49d5843b2185f9'
PACKAGES={
 'libinih-dev':('55-1ubuntu2','b095fe90efe49a6572429ce26b7206cbc9404a19510e61bdebd1ae829340b888'),
 'libpipewire-0.3-dev':('1.0.5-1ubuntu3.3','1a0267989f02a8729cdb4df36d9acf3a5ac1a525200d428baffe8961ccb0e0ba'),
 'libspa-0.2-dev':('1.0.5-1ubuntu3.3','93a60e7656fb35c97a78159fd0556842c62c2d8b9aff096009f9a20c64c1f272'),
 'libsystemd-dev':('255.4-1ubuntu8.18','37f42520029a429bd9931677c965eecab146d5e3bd34e2a54f4e70dffedaeccb'),
}
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def run(args,**kwargs):return subprocess.run([str(arg) for arg in args],check=True,**kwargs)
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--offline',action='store_true');args=parser.parse_args()
    if os.geteuid()==0:parser.error('Build as your desktop user; this does not require sudo.')
    lock=ROOT/'.screen-lock-build/sysroot';drm=ROOT/'.native-drm-runtime'
    if not (lock/'usr/bin/meson').is_file() or not (drm/'usr/include/gbm.h').is_file():parser.error('Prepare the screen-lock and native-DRM development sysroots first.')
    architecture=subprocess.check_output(['dpkg','--print-architecture'],text=True).strip()
    if architecture!='amd64':parser.error('This pinned development cache targets Ubuntu/Mint amd64; use distribution development headers on other build platforms.')
    packages=BASE/'packages';sysroot=BASE/'sysroot';packages.mkdir(parents=True,exist_ok=True);sysroot.mkdir(exist_ok=True)
    archive=BASE/f'xdg-desktop-portal-wlr-{VERSION}.tar.gz'
    if not archive.exists():
        if args.offline:parser.error('Offline cache is missing the upstream source archive.')
        with urllib.request.urlopen(SOURCE,timeout=30) as response:data=response.read(4_000_001)
        if len(data)>4_000_000:raise RuntimeError('Unexpected source archive size')
        archive.write_bytes(data)
    if sha(archive)!=SOURCE_SHA256:raise RuntimeError('Pinned portal source hash mismatch')
    package_info=[]
    for name,(version,expected) in PACKAGES.items():
        matches=list(packages.glob(f'{name}_{version}_amd64.deb'))
        if not matches:
            if args.offline:parser.error('Offline cache is missing '+name+'='+version)
            run(['apt-get','download',name+'='+version],cwd=packages);matches=list(packages.glob(f'{name}_{version}_amd64.deb'))
        if len(matches)!=1 or sha(matches[0])!=expected:raise RuntimeError('Pinned development package hash mismatch: '+name)
        run(['dpkg-deb','-x',matches[0],sysroot]);package_info.append(dict(name=name,version=version,sha256=expected))
    with tarfile.open(archive) as source:source.extractall(BASE,filter='data')
    source_dir=BASE/f'xdg-desktop-portal-wlr-{VERSION}'
    patch=ROOT/'patches/xdg-desktop-portal-wlr-shm.patch'
    run(['patch','--batch','--forward','-p1','-i',patch],cwd=source_dir)
    triplet=subprocess.check_output(['cc','-dumpmachine'],text=True).strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',triplet):raise RuntimeError('Invalid compiler triplet')
    library=sysroot/'usr/lib'/triplet
    for link in library.glob('*.so'):
        if link.is_symlink() and not link.exists():
            host=Path('/usr/lib')/triplet/Path(os.readlink(link)).name
            if host.exists():link.unlink();link.symlink_to(host.resolve())
    for pc in sysroot.rglob('*.pc'):
        pc.write_text(pc.read_text().replace('=/usr','='+str(sysroot)+'/usr').replace('=/lib','='+str(sysroot)+'/lib'))
    roots=[sysroot,drm,lock];pkgdirs=[path for root in roots for path in (root/'usr/lib'/triplet/'pkgconfig',root/'usr/share/pkgconfig',root/'usr/lib/pkgconfig') if path.is_dir()]
    env=dict(os.environ);env.pop('LD_LIBRARY_PATH',None);env.pop('PKG_CONFIG_PATH',None)
    env.update(PYTHONPATH=str(lock/'usr/lib/python3/dist-packages'),PATH=str(lock/'usr/bin')+':'+env.get('PATH',''),PKG_CONFIG_LIBDIR=':'.join(map(str,pkgdirs)),LIBRARY_PATH=':'.join(str(root/'usr/lib'/triplet) for root in roots))
    build=BASE/'build';meson=['/usr/bin/python3',lock/'usr/bin/meson']
    setup=[*meson,'setup',*(['--wipe'] if build.exists() else []),build,source_dir,'--prefix=/usr','--libexecdir=libexec','--buildtype=release','-Dsystemd=disabled','-Dman-pages=disabled','-Dsd-bus-provider=libsystemd','-Dc_args='+json.dumps(['-I'+str(root/'usr/include') for root in roots]),'-Dc_link_args='+json.dumps(['-L'+str(root/'usr/lib'/triplet) for root in roots])]
    run(setup,env=env);run(['nice','-n','15',lock/'usr/bin/ninja','-C',build,'-j1'],env=env)
    stage=BASE/'install-root';run([*meson,'install','-C',build,'--destdir',stage],env=env)
    binary=stage/'usr/libexec/xdg-desktop-portal-wlr'
    dynamic=subprocess.check_output(['readelf','-d',binary],text=True)
    libraries=subprocess.check_output(['ldd',binary],text=True,env={k:v for k,v in env.items() if k not in ('LD_LIBRARY_PATH','PYTHONPATH')})
    if 'not found' in libraries or str(BASE) in dynamic:raise RuntimeError('Portal binary retains missing/build-directory runtime dependencies')
    RUNTIME.mkdir(exist_ok=True);destination=RUNTIME/'xdg-desktop-portal-wlr';temporary=RUNTIME/'.xdg-desktop-portal-wlr.new'
    shutil.copy2(binary,temporary);temporary.chmod(0o755)
    if shutil.which('strip'):run(['strip',temporary])
    os.replace(temporary,destination)
    shutil.copy2(source_dir/'LICENSE',RUNTIME/'LICENSE.xdpw')
    manifest=dict(version=VERSION,source=SOURCE,sourceSha256=SOURCE_SHA256,patchSha256=sha(patch),patch='Accept valid SHM capture without requiring optional DMA-BUF export',binarySha256=sha(destination),binaryBytes=destination.stat().st_size,buildPackages=package_info,linkedLibraries=libraries.splitlines(),systemFilesChanged=False)
    (RUNTIME/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(dict(binary=str(destination),bytes=manifest['binaryBytes'],sourceSha256=SOURCE_SHA256,systemFilesChanged=False)))
if __name__=='__main__':main()
