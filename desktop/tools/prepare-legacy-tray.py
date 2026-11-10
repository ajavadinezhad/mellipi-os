#!/usr/bin/env python3
"""Extract a pinned distro XEmbed-to-SNI proxy locally; never install Plasma.

Downloads use APT's configured signed repositories. --offline verifies cached
package hashes against tray-runtime-lock.json. Only the proxy, its two extra
libraries, its small X11 window-system plugin, and copyright/license files are retained in .tray-runtime.
"""
import argparse,hashlib,json,os,shutil,subprocess,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def metadata(path):
    return {key:subprocess.check_output(['dpkg-deb','-f',str(path),key],text=True).strip() for key in ('Package','Version','Architecture')}

def prepare(cache,offline=False):
    lock=json.loads((ROOT/'tools/tray-runtime-lock.json').read_text());cache=Path(cache);cache.mkdir(parents=True,exist_ok=True)
    architecture=subprocess.check_output(['dpkg','--print-architecture'],text=True).strip()
    if architecture!=lock['architecture']:raise RuntimeError('The pinned legacy tray runtime requires '+lock['architecture'])
    candidates={}
    for path in cache.glob('*.deb'):
        info=metadata(path);candidates[(info['Package'],info['Version'],info['Architecture'])]=path
    selected=[]
    for package in lock['packages']:
        key=(package['name'],package['version'],architecture);path=candidates.get(key)
        if path is None:
            if offline:raise RuntimeError('Offline package missing: '+package['name']+'='+package['version'])
            subprocess.run(['apt-get','download',package['name']+'='+package['version']],cwd=cache,check=True)
            for item in cache.glob('*.deb'):
                info=metadata(item)
                if (info['Package'],info['Version'],info['Architecture'])==key:path=item;break
        if path is None or hashlib.sha256(path.read_bytes()).hexdigest()!=package['sha256']:raise RuntimeError('Pinned package hash mismatch: '+package['name'])
        selected.append((package,path))
    target=ROOT/'.tray-runtime'
    if target.is_symlink():raise RuntimeError('Refusing a symbolic tray runtime directory')
    target.mkdir(exist_ok=True)
    for name in ('bin','lib','licenses','plugins','plugins/kf5','plugins/kf5/kwindowsystem'):
        directory=target/name
        if directory.is_symlink():raise RuntimeError('Refusing a linked tray runtime subdirectory')
        directory.mkdir(exist_ok=True)
    files=[]
    for package,path in selected:
        process=subprocess.Popen(['dpkg-deb','--fsys-tarfile',str(path)],stdout=subprocess.PIPE)
        try:
            with tarfile.open(fileobj=process.stdout,mode='r|') as archive:
                for item in archive:
                    name=item.name.removeprefix('./');base=Path(name).name;destination=None
                    if name=='usr/bin/xembedsniproxy':destination=target/'bin'/base
                    elif name.startswith('usr/lib/x86_64-linux-gnu/') and (base.startswith('libKF5WindowSystem.so.') or base.startswith('libQt5X11Extras.so.')):destination=target/'lib'/base
                    elif name=='usr/lib/x86_64-linux-gnu/qt5/plugins/kf5/kwindowsystem/KF5WindowSystemX11Plugin.so':destination=target/'plugins/kf5/kwindowsystem'/base
                    elif name=='usr/share/doc/'+package['name']+'/copyright':destination=target/'licenses'/(package['name']+'.copyright')
                    if destination is None:continue
                    if destination.is_symlink() or destination.exists():destination.unlink()
                    if item.issym():
                        if Path(item.linkname).name!=item.linkname:raise RuntimeError('Unsafe library link in package')
                        destination.symlink_to(item.linkname)
                    elif item.isfile():
                        with archive.extractfile(item) as source:destination.write_bytes(source.read())
                        destination.chmod(0o755 if name=='usr/bin/xembedsniproxy' else 0o644)
                        files.append(dict(path=str(destination.relative_to(target)),sha256=hashlib.sha256(destination.read_bytes()).hexdigest()))
        finally:
            process.stdout.close()
            if process.wait()!=0:raise RuntimeError('Package extraction failed')
    for name in ('GPL-2','GPL-3','LGPL-2.1','LGPL-3'):
        source=Path('/usr/share/common-licenses')/name
        if source.is_file():shutil.copyfile(source,target/'licenses'/name)
    binary=target/'bin/xembedsniproxy'
    env=os.environ.copy();env['LD_LIBRARY_PATH']=str(target/'lib')
    for executable in (binary,target/'plugins/kf5/kwindowsystem/KF5WindowSystemX11Plugin.so'):
        result=subprocess.run(['ldd',str(executable)],env=env,capture_output=True,text=True,check=True)
        if 'not found' in result.stdout:raise RuntimeError('Missing host runtime libraries: '+result.stdout)
    manifest=dict(**lock,files=files,systemPackagesInstalled=False,sourceRetrieval='apt-get source plasma-workspace=4:5.27.12-0ubuntu0.1 kwindowsystem=5.115.0-0ubuntu4 qtx11extras-opensource-src=5.15.13-1')
    (target/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--offline',action='store_true');parser.add_argument('--cache-dir',default=str(ROOT/'.tray-build/packages'));args=parser.parse_args()
    try:print(json.dumps(prepare(args.cache_dir,args.offline),indent=2))
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as error:parser.exit(1,str(error)+'\n')
if __name__=='__main__':main()
