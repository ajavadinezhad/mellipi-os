#!/usr/bin/env python3
"""Prepare pinned distro development files locally; never installs system packages."""
import argparse,hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PACKAGES={'libgbm-dev':'25.2.8-0ubuntu0.24.04.4','libdrm-dev':'2.4.125-1ubuntu0.1~24.04.2','libinput-dev':'1.25.0-1ubuntu3.7','libudev-dev':'255.4-1ubuntu8.18','libseat-dev':'0.8.0-1','libseat1':'0.8.0-1'}
def main():
 p=argparse.ArgumentParser();p.add_argument('--offline',action='store_true');args=p.parse_args()
 cache=ROOT/'.native-drm-build/packages';runtime=ROOT/'.native-drm-runtime';cache.mkdir(parents=True,exist_ok=True);runtime.mkdir(exist_ok=True)
 manifest=[]
 for package,version in PACKAGES.items():
  matches=list(cache.glob(package+'_'+version.replace(':','%3a')+'*.deb'))
  if not matches:
   if args.offline:raise SystemExit('Missing cached package: '+package+'='+version)
   subprocess.run(['apt-get','download',package+'='+version],cwd=cache,check=True)
   matches=list(cache.glob(package+'_*.deb'))
  if len(matches)!=1:raise SystemExit('Expected exactly one pinned archive for '+package)
  archive=matches[0];subprocess.run(['dpkg-deb','-x',str(archive),str(runtime)],check=True)
  manifest.append(dict(package=package,version=version,archive=archive.name,sha256=hashlib.sha256(archive.read_bytes()).hexdigest()))
 for pc in (runtime/'usr/lib/x86_64-linux-gnu/pkgconfig').glob('*.pc'):
  text=pc.read_text().replace('prefix=/usr','prefix='+str(runtime/'usr'))
  pc.write_text(text)
 lib=runtime/'usr/lib/x86_64-linux-gnu'
 for name,soname in (('gbm','1'),('drm','2'),('udev','1'),('input','10')):
  target=lib/('lib'+name+'.so')
  if target.is_symlink():target.unlink()
  source=Path('/usr/lib/x86_64-linux-gnu')/('lib'+name+'.so.'+soname)
  if not source.exists():source=Path('/lib/x86_64-linux-gnu')/source.name
  if not source.is_file():raise SystemExit('Missing existing system runtime '+source.name)
  if target.exists():target.unlink()
  target.symlink_to(source)
 (runtime/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 print('Prepared '+str(runtime))
 print('PKG_CONFIG_PATH='+str(lib/'pkgconfig'))
 print('LD_LIBRARY_PATH='+str(lib))
if __name__=='__main__':main()
