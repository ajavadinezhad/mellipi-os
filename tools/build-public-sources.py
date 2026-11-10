#!/usr/bin/env python3
"""Stage explicit corresponding sources, never the developer working directory.

Only local project source allowlists and checksum-verified source archives enter
output. No signing keys, user state, VM images, build trees or ELF binaries.
"""
import argparse, gzip, hashlib, io, json, re, shutil, tarfile, tomllib, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT / 'desktop' if (ROOT / 'desktop').is_dir() else ROOT
UPSTREAM_RUNTIME_SOURCES = (
 ('.portal-build', '.portal-runtime/manifest.json', 'xdg-desktop-portal-wlr-0.7.1.tar.gz', 'https://github.com/emersion/xdg-desktop-portal-wlr/releases/download/v0.7.1/xdg-desktop-portal-wlr-0.7.1.tar.gz', 'eec6e4be808e1a445e677dba1e20e5acb2f091825f5ff4c6ac49d5843b2185f9'),
 ('.screen-lock-build', '.lock-runtime/manifest.json', 'swaylock-1.8.6.tar.gz', 'https://github.com/swaywm/swaylock/releases/download/v1.8.6/swaylock-1.8.6.tar.gz', 'a15154348fef852fdb224112d137c393c826478b777f63479beb15e8d3812eaf'),
)
DISTRO_SOURCES = (
 ('calamares', '3.3.5-0ubuntu4', 'c/calamares/calamares_3.3.5-0ubuntu4.dsc'),
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
 root=PROJECT_ROOT
 source=root/'src' if (root/'src').is_dir() else root
 paths=list(source.glob('*.py'))+[root/'README.md',root/'requirements-native.txt']
 paths.extend(path for path in (source/'session').rglob('*') if path.is_file() and path.suffix in ('.py','.conf','.sh','.desktop'))
 for name in ('native','themes','patches','packaging'):
  paths.extend(path for path in (root/name).rglob('*') if path.is_file() and (path.suffix in ('.py','.qml','.js','.svg','.json','.conf','.sh','.h','.c','.patch','.policy','.service','.rules','.desktop','.txt','.gpg','.asc') or path.name=='qmldir'))
 for name in ('compositor','backend'):
  paths.extend(path for path in (root/name/'src').rglob('*') if path.is_file())
  paths.extend(path for path in (root/name).glob('Cargo.*') if path.is_file())
  paths.extend(path for path in (root/name).glob('LICENSE*') if path.is_file())
 paths.extend(path for path in (root/'compositor/vendor').rglob('*') if path.is_file() and 'target' not in path.parts and '.git' not in path.parts)
 paths.extend(path for path in (root/'tools').iterdir() if path.is_file() and path.suffix in ('.py','.sh','.json') and path.name!='rustup-init.sh')
 if (root/'tools/abstract-charge-limit').is_file():paths.append(root/'tools/abstract-charge-limit')
 for name in ('abstract-synaptic-root','abstract-package-manager'):
  if (root/'packaging'/name).is_file():paths.append(root/'packaging'/name)
 paths.extend(path for path in root.glob('run-*') if path.is_file() and path.suffix in ('.py','.sh'))
 for name in ('test_package_manager_bridge.py','test_package_manager_discovery.py','test_package_manager_launcher.py','test_permission_agent_backend.py','test_mellipi_rename.py'):
  if (root/'tests'/name).is_file():paths.append(root/'tests'/name)
 paths=sorted(set(path for path in paths if path.is_file() and not path.is_symlink() and '__pycache__' not in path.parts and path.suffix not in ('.pyc','.log')))
 result=[(path,(Path('desktop')/path.relative_to(root) if root!=ROOT else path.relative_to(root))) for path in paths]
 if root!=ROOT:
  result.extend((path,Path('tools')/path.name) for path in sorted((ROOT/'tools').glob('*')) if path.is_file() and not path.is_symlink() and path.suffix in ('.py','.sh','.json'))
  result.extend((path,Path('tests/fixtures')/path.name) for path in sorted((ROOT/'tests/fixtures').glob('*.cpp')) if path.is_file() and not path.is_symlink())
  if (ROOT/'README.md').is_file():result.append((ROOT/'README.md',Path('README.md')))
  if (ROOT/'docs/live-iso.md').is_file():result.append((ROOT/'docs/live-iso.md',Path('docs/live-iso.md')))
 return sorted(result,key=lambda item:str(item[1]))
def local_source(cache,name,expected=None):
 candidates=[cache/name]
 # A source-only checkout can reuse previously published immutable sources.
 for section in ('upstream','qt-compatibility-inputs','rust-crates'):
  candidates.extend(sorted((ROOT/'public/sources').glob('*/'+section+'/'+name)))
 return next((path for path in candidates if path.is_file() and not path.is_symlink() and (expected is None or sha(path)==expected)),cache/name)
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--cache',type=Path,required=True);parser.add_argument('--version',default='0.1.8');parser.add_argument('--fetch',action='store_true');parser.add_argument('--project-root',type=Path,help='Optional application source root (default desktop/ when present)');args=parser.parse_args()
 global PROJECT_ROOT
 if args.project_root:PROJECT_ROOT=args.project_root.resolve()
 source=PROJECT_ROOT/'src' if (PROJECT_ROOT/'src').is_dir() else PROJECT_ROOT
 if not (source/'native_app.py').is_file():parser.error('Application source root is missing src/native_app.py (or flat native_app.py)')
 if not re.fullmatch(r'[A-Za-z0-9.+~-]+',args.version):parser.error('Invalid source version')
 output=args.output.resolve();cache=args.cache.resolve();output.mkdir(parents=True,exist_ok=True);cache.mkdir(parents=True,exist_ok=True);rows=[]
 source_archive=cache/f'mellipi-{args.version}-project-source.tar.gz'
 buffer=io.BytesIO()
 with tarfile.open(fileobj=buffer,mode='w') as archive:
  for path,relative in project_paths():
   info=archive.gettarinfo(str(path),arcname=f'mellipi-{args.version}/'+str(relative));info.uid=info.gid=0;info.uname=info.gname='';info.mtime=0;info.mode=0o755 if path.stat().st_mode&0o111 else 0o644
   with path.open('rb') as stream:archive.addfile(info,stream)
 source_archive.write_bytes(gzip.compress(buffer.getvalue(),mtime=0))
 stage_file(source_archive,output,Path(source_archive.name),rows)
 for package,version,relative in DISTRO_SOURCES:
  url='https://archive.ubuntu.com/ubuntu/pool/universe/'+relative;descriptor=local_source(cache,Path(relative).name);obtain(url,descriptor,fetch=args.fetch)
  text=descriptor.read_text();assert re.search(r'^Source: '+re.escape(package)+r'$',text,re.M) and re.search(r'^Version: '+re.escape(version)+r'$',text,re.M),descriptor
  stage_file(descriptor,output,Path('upstream')/descriptor.name,rows,url)
  match=re.search(r'^Checksums-Sha256:\n((?: .+\n)+)',text,re.M)
  if not match:raise ValueError('No SHA256 source list: '+descriptor.name)
  for line in match[1].splitlines():
   checksum,size,name=line.split();assert re.fullmatch('[0-9a-f]{64}',checksum) and Path(name).name==name
   source=local_source(cache,name,checksum);source_url=url.rsplit('/',1)[0]+'/'+name;obtain(source_url,source,checksum,args.fetch);assert source.stat().st_size==int(size)
   stage_file(source,output,Path('upstream')/name,rows,source_url)
 inputs=json.loads((PROJECT_ROOT/'tools/qt5-a11y-inputs.json').read_text())['downloads']
 for item in inputs:
  if item['kind']!='source':continue
  source=local_source(cache,item['name'],item['sha256']);obtain(item['url'],source,item['sha256'],args.fetch)
  stage_file(source,output,Path('qt-compatibility-inputs')/item['name'],rows,item['url'])
 for folder,manifest,archive_name,url,expected in UPSTREAM_RUNTIME_SOURCES:
  metadata_path=PROJECT_ROOT/manifest
  metadata=json.loads(metadata_path.read_text()) if metadata_path.is_file() else {'source':url,'sourceSha256':expected}
  source=PROJECT_ROOT/folder/archive_name
  if not source.is_file():source=local_source(cache,archive_name,metadata['sourceSha256']);obtain(metadata['source'],source,metadata['sourceSha256'],args.fetch)
  assert sha(source)==metadata['sourceSha256'];stage_file(source,output,Path('upstream')/archive_name,rows,metadata['source'])
 crates={}
 for name in ('compositor','backend'):
  lock=tomllib.loads((PROJECT_ROOT/name/'Cargo.lock').read_text())
  for package in lock['package']:
   if package.get('source','').startswith('registry+'):
    filename=package['name']+'-'+package['version']+'.crate';expected=package['checksum']
    if filename in crates:assert crates[filename]==(package['name'],expected)
    crates[filename]=(package['name'],expected)
 for filename,(crate_name,expected) in sorted(crates.items()):
  candidates=list((PROJECT_ROOT/'.toolchain/cargo/registry/cache').glob('*/'+filename));source=next((p for p in candidates if sha(p)==expected),None)
  if source is None:
   source=local_source(cache,filename,expected);obtain('https://static.crates.io/crates/'+crate_name+'/'+filename,source,expected,args.fetch)
  stage_file(source,output,Path('rust-crates')/filename,rows,'Cargo.lock SHA256-pinned crate')
 (output/'manifest.json').write_text(json.dumps({'version':args.version,'files':rows,'private_state_included':False,'note':'Third-party terms remain as supplied. No new license is assigned to Mellipi source by this archive.'},indent=2)+'\n')
 (output/'SHA256SUMS').write_text(''.join(row['sha256']+'  '+row['path']+'\n' for row in rows))
 print(json.dumps({'files':len(rows),'bytes':sum(row['bytes'] for row in rows),'output':str(output)}))
if __name__=='__main__':main()
