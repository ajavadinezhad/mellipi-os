#!/usr/bin/env python3
"""Stage explicit corresponding sources, never the developer working directory.

Only local project source allowlists and checksum-verified source archives enter
output. No signing keys, user state, VM images, build trees or ELF binaries.
"""
import argparse, gzip, hashlib, io, json, re, shutil, tarfile, tomllib, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DISTRO_SOURCES = (
 ('plasma-workspace', '4:5.27.12-0ubuntu0.1', 'p/plasma-workspace/plasma-workspace_5.27.12-0ubuntu0.1.dsc'),
 ('kwindowsystem', '5.115.0-0ubuntu4', 'k/kwindowsystem/kwindowsystem_5.115.0-0ubuntu4.dsc'),
 ('qtx11extras-opensource-src', '5.15.13-1', 'q/qtx11extras-opensource-src/qtx11extras-opensource-src_5.15.13-1.dsc'),
 ('qtwayland-opensource-src', '5.15.13-1', 'q/qtwayland-opensource-src/qtwayland-opensource-src_5.15.13-1.dsc'),
 ('qtbase-opensource-src', '5.15.13+dfsg-1ubuntu1', 'q/qtbase-opensource-src/qtbase-opensource-src_5.15.13+dfsg-1ubuntu1.dsc'),
)
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as stream:
  for data in iter(lambda:stream.read(1024*1024),b''):h.update(data)
 return h.hexdigest()
def obtain(url, path, expected=None, fetch=False):
 if path.is_file() and (expected is None or sha(path)==expected):return
 if not fetch:raise ValueError('Missing source cache; rerun with --fetch: '+path.name)
 temporary=path.with_name(path.name+'.part')
 try:
  with urllib.request.urlopen(url, timeout=90) as incoming,temporary.open('wb') as target:shutil.copyfileobj(incoming,target)
  if expected and sha(temporary)!=expected:raise ValueError('Source checksum mismatch: '+path.name)
  temporary.replace(path)
 finally:temporary.unlink(missing_ok=True)
def stage_file(source, output, relative, rows, origin=None):
 assert source.is_file() and not source.is_symlink(),source
 destination=output/relative;destination.parent.mkdir(parents=True,exist_ok=True)
 if destination.exists() and sha(destination)!=sha(source):raise ValueError('Immutable source path changed: '+str(relative))
 if not destination.exists():shutil.copyfile(source,destination)
 rows.append(dict(path=str(relative),bytes=destination.stat().st_size,sha256=sha(destination),origin=origin or 'local reviewed source'))
def project_paths():
 paths=list(ROOT.glob('*.py'))+[ROOT/'README.md',ROOT/'requirements-native.txt']
 for name in ('native','themes','session','patches','packaging'):
  paths.extend(path for path in (ROOT/name).rglob('*') if path.is_file() and path.suffix in ('.py','.qml','.js','.svg','.json','.conf','.sh','.h','.patch','.policy','.service','.rules','.desktop','.txt'))
 for name in ('compositor','backend'):
  paths.extend(path for path in (ROOT/name/'src').rglob('*') if path.is_file())
  paths.extend(path for path in (ROOT/name).glob('Cargo.*') if path.is_file())
  paths.extend(path for path in (ROOT/name).glob('LICENSE*') if path.is_file())
 paths.extend(path for path in (ROOT/'compositor/vendor').rglob('*') if path.is_file() and 'target' not in path.parts and '.git' not in path.parts)
 paths.extend(path for path in (ROOT/'tools').iterdir() if path.is_file() and path.suffix in ('.py','.sh','.json') and path.name!='rustup-init.sh')
 paths.extend(path for path in ROOT.glob('run-*') if path.is_file() and path.suffix in ('.py','.sh'))
 return sorted(set(path for path in paths if not path.is_symlink() and '__pycache__' not in path.parts and path.suffix not in ('.pyc','.log')))
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--cache',type=Path,required=True);parser.add_argument('--version',default='0.1.6');parser.add_argument('--fetch',action='store_true');args=parser.parse_args()
 if not re.fullmatch(r'[A-Za-z0-9.+~-]+',args.version):parser.error('Invalid source version')
 output=args.output.resolve();cache=args.cache.resolve();output.mkdir(parents=True,exist_ok=True);cache.mkdir(parents=True,exist_ok=True);rows=[]
 source_archive=cache/f'abstract-{args.version}-project-source.tar.gz'
 buffer=io.BytesIO()
 with tarfile.open(fileobj=buffer,mode='w') as archive:
  for path in project_paths():
   relative=path.relative_to(ROOT);info=archive.gettarinfo(str(path),arcname=f'abstract-{args.version}/'+str(relative));info.uid=info.gid=0;info.uname=info.gname='';info.mtime=0;info.mode=0o755 if path.stat().st_mode&0o111 else 0o644
   with path.open('rb') as stream:archive.addfile(info,stream)
 source_archive.write_bytes(gzip.compress(buffer.getvalue(),mtime=0))
 stage_file(source_archive,output,Path(source_archive.name),rows)
 for package,version,relative in DISTRO_SOURCES:
  url='https://archive.ubuntu.com/ubuntu/pool/universe/'+relative;descriptor=cache/Path(relative).name;obtain(url,descriptor,fetch=args.fetch)
  text=descriptor.read_text();assert re.search(r'^Source: '+re.escape(package)+r'$',text,re.M) and re.search(r'^Version: '+re.escape(version)+r'$',text,re.M),descriptor
  stage_file(descriptor,output,Path('upstream')/descriptor.name,rows,url)
  match=re.search(r'^Checksums-Sha256:\n((?: .+\n)+)',text,re.M)
  if not match:raise ValueError('No SHA256 source list: '+descriptor.name)
  for line in match[1].splitlines():
   checksum,size,name=line.split();assert re.fullmatch('[0-9a-f]{64}',checksum) and Path(name).name==name
   source=cache/name;source_url=url.rsplit('/',1)[0]+'/'+name;obtain(source_url,source,checksum,args.fetch);assert source.stat().st_size==int(size)
   stage_file(source,output,Path('upstream')/name,rows,source_url)
 inputs=json.loads((ROOT/'tools/qt5-a11y-inputs.json').read_text())['downloads']
 for item in inputs:
  if item['kind']!='source':continue
  source=cache/item['name'];obtain(item['url'],source,item['sha256'],args.fetch)
  stage_file(source,output,Path('qt-compatibility-inputs')/item['name'],rows,item['url'])
 for folder,manifest,archive_name in [('.portal-build','.portal-runtime/manifest.json','xdg-desktop-portal-wlr-0.7.1.tar.gz'),('.screen-lock-build','.lock-runtime/manifest.json','swaylock-1.8.6.tar.gz')]:
  metadata=json.loads((ROOT/manifest).read_text());source=ROOT/folder/archive_name
  if not source.is_file():source=cache/archive_name;obtain(metadata['source'],source,metadata['sourceSha256'],args.fetch)
  assert sha(source)==metadata['sourceSha256'];stage_file(source,output,Path('upstream')/archive_name,rows,metadata['source'])
 crates={}
 for name in ('compositor','backend'):
  lock=tomllib.loads((ROOT/name/'Cargo.lock').read_text())
  for package in lock['package']:
   if package.get('source','').startswith('registry+'):
    filename=package['name']+'-'+package['version']+'.crate';expected=package['checksum']
    if filename in crates:assert crates[filename]==(package['name'],expected)
    crates[filename]=(package['name'],expected)
 for filename,(crate_name,expected) in sorted(crates.items()):
  candidates=list((ROOT/'.toolchain/cargo/registry/cache').glob('*/'+filename));source=next((p for p in candidates if sha(p)==expected),None)
  if source is None:
   source=cache/filename;obtain('https://static.crates.io/crates/'+crate_name+'/'+filename,source,expected,args.fetch)
  stage_file(source,output,Path('rust-crates')/filename,rows,'Cargo.lock SHA256-pinned crate')
 (output/'manifest.json').write_text(json.dumps({'version':args.version,'files':rows,'private_state_included':False,'note':'Third-party terms remain as supplied. No new license is assigned to Abstract source by this archive.'},indent=2)+'\n')
 (output/'SHA256SUMS').write_text(''.join(row['sha256']+'  '+row['path']+'\n' for row in rows))
 print(json.dumps({'files':len(rows),'bytes':sum(row['bytes'] for row in rows),'output':str(output)}))
if __name__=='__main__':main()
