#!/usr/bin/env python3
"""Assemble only reviewed public website/archive files; never copy a working tree."""
import argparse, hashlib, json, re, shutil, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def assemble(output,packages,key_home,fingerprint,sources=()):
    raw_output=Path(output)
    if raw_output.is_symlink():raise ValueError('Output must not be a symlink')
    output=raw_output.resolve()
    if output==ROOT or ROOT in output.parents and output.relative_to(ROOT).parts[0] not in ('public','dist'):
        raise ValueError('Choose public/ or dist/ output, or a dedicated path outside the project')
    if not re.fullmatch(r'[A-Fa-f0-9]{40}',fingerprint):raise ValueError('A full signing fingerprint is required')
    if output.is_symlink():raise ValueError('Output must not be a symlink')
    output.mkdir(parents=True,exist_ok=True)
    subprocess.run(['python3',str(ROOT/'tools/export-website-themes.py'),'--output',str(ROOT/'website/themes.json')],check=True)
    for name in ('index.html','style.css','theme-init.js','site.js','site-config.json','themes.json','favicon.svg'):
        source=ROOT/'website'/name
        if source.is_file():shutil.copy2(source,output/name)
    if not (output/'index.html').is_file():raise ValueError('Build website/ first')
    html=output/'index.html'
    content=html.read_text()
    for name in ('style.css','theme-init.js','site.js'):
        asset=output/name
        if asset.is_file():
            version=hashlib.sha256(asset.read_bytes()).hexdigest()[:12]
            content=content.replace('"'+name+'"','"'+name+'?v='+version+'"')
    html.write_text(content)
    assets=ROOT/'website/assets'
    if assets.is_dir():shutil.copytree(assets,output/'assets',dirs_exist_ok=True)
    subprocess.run(['python3',str(ROOT/'tools/build-apt-repository.py'),'--output',str(output/'apt'),'--packages',*[str(Path(p).resolve()) for p in packages],'--gnupg-home',str(Path(key_home).resolve()),'--signing-key',fingerprint.upper()],check=True)
    shutil.copy2(ROOT/'tools/install-update-source.sh',output/'apt/install-update-source.sh')
    (output/'.nojekyll').write_text('')
    published_sources=[]
    for source in map(Path,sources):
        if not source.is_file() or source.is_symlink() or not source.name.endswith(('.tar.gz','.tar.xz','.json','.md')):raise ValueError('Only reviewed source archives/manifests may be published')
        target=output/'sources'/source.name;target.parent.mkdir(exist_ok=True);shutil.copy2(source,target);published_sources.append('sources/'+source.name)
    published_sources=sorted(str(p.relative_to(output)) for p in (output/'sources').rglob('*') if p.is_file()) if (output/'sources').exists() else []
    manifest={'release':json.loads((output/'site-config.json').read_text())['release'],'signing_fingerprint':fingerprint.upper(),'sources':published_sources,'files':{}}
    for p in sorted(output.rglob('*')):
        if p.is_symlink():raise ValueError('Public output contains a symlink')
        if p.is_file() and p.name!='publication-manifest.json':
            data=p.read_bytes()
            if b'-----BEGIN PGP PRIVATE KEY BLOCK-----' in data or b'-----BEGIN OPENSSH PRIVATE KEY-----' in data:raise ValueError('Private key found in public output')
            manifest['files'][str(p.relative_to(output))]={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    (output/'publication-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'public_directory':str(output),'files':len(manifest['files']),'bytes':sum(f['bytes'] for f in manifest['files'].values())}))

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=ROOT/'public');parser.add_argument('--packages',type=Path,nargs='+',required=True);parser.add_argument('--gnupg-home',type=Path,required=True);parser.add_argument('--signing-key',required=True);parser.add_argument('--sources',type=Path,nargs='*',default=[]);args=parser.parse_args()
    assemble(args.output,args.packages,args.gnupg_home,args.signing_key,args.sources)
if __name__=='__main__':main()
