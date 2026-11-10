#!/usr/bin/env python3
"""Renew already-published signed metadata locally; never upload or install."""
import argparse,gzip,importlib.util,json,re,shutil,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def module(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'tools'/file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def _renew_stage(public,home,key):
    pub=module('publication','prepare-public-release.py');apt=module('archive','build-apt-repository.py')
    raw=Path(public)
    if raw.is_symlink():raise ValueError('Publication directory must not be a symlink')
    public=raw.resolve();home=Path(home).resolve()
    if public==home or public in home.parents:raise ValueError('Signing key must remain outside publication')
    manifest=json.loads((public/'publication-manifest.json').read_text())
    before=pub.records(public)
    if before!=manifest['files']:raise ValueError('Publication manifest differs; inspect before renewal')
    archive=public/'apt';keyfile=archive/'mellipi-archive-keyring.gpg'
    if not keyfile.is_file():keyfile=archive/'abstract-archive-keyring.gpg'
    # Authenticate the old archive even when its metadata has expired.
    with tempfile.TemporaryDirectory(prefix='mellipi-renew-verify-') as d:
        identity=subprocess.check_output(['gpg','--homedir',d,'--batch','--with-colons','--show-keys',str(keyfile)],stderr=subprocess.PIPE,text=True)
        pubs=[r for r in identity.splitlines() if r.startswith('pub:')]
        fps=[r.split(':')[9] for r in identity.splitlines() if r.startswith('fpr:')]
        if len(pubs)!=1 or not fps or fps[0]!=key.upper():raise ValueError('Published key differs from requested trusted signer')
        command=['gpgv','--homedir',d,'--keyring',str(keyfile)]
        signed=subprocess.check_output([*command,'--output','-',str(archive/'dists/noble/InRelease')],stderr=subprocess.PIPE)
    if signed!=(archive/'dists/noble/Release').read_bytes():raise ValueError('Release signature/content mismatch')
    if apt.fingerprint(home,key)!=manifest['signing_fingerprint']:raise ValueError('Signing key differs from published identity')
    rows=signed.decode();origin=re.search(r'^Origin: (.+)$',rows,re.M)
    if not origin or origin[1] not in ('Mellipi','Abstract'):raise ValueError('Unknown archive identity')
    hashes=re.search(r'^SHA256:\n((?: .+\n)+)',rows,re.M)
    if not hashes:raise ValueError('Missing signed index hashes')
    for row in hashes[1].splitlines():
        checksum,size,name=row.split();pub.checked_file(archive/'dists/noble',name,size,checksum)
    paragraphs=gzip.decompress((archive/'dists/noble/main/binary-amd64/Packages.gz').read_bytes()).decode().strip().split('\n\n')
    packages=[]
    for paragraph in paragraphs:
        fields=dict(r.split(': ',1) for r in paragraph.splitlines() if ': ' in r and not r[0].isspace())
        packages.append(pub.checked_file(archive,fields['Filename'],fields['Size'],fields['SHA256']))
    if not packages:raise ValueError('Cannot renew an empty archive')
    # The builder atomically replaces metadata while retaining package/by-hash files.
    helper=archive/'install-update-source.sh';helper_bytes=helper.read_bytes() if helper.is_file() else None
    apt.build(archive,packages,home,key,origin=origin[1])
    if helper_bytes is not None:
        helper.write_bytes(helper_bytes);helper.chmod(0o755)
    after=pub.records(public)
    protected=lambda records:{n:v for n,v in records.items() if not n.startswith('apt/') or n.startswith('apt/pool/')}
    if protected(before)!=protected(after):raise ValueError('Renewal modified immutable publication files')
    manifest['files']=after
    (public/'publication-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    pub.validate_existing(public)
    return {'public_directory':str(public),'metadata_renewed':True,'package_and_source_bytes_preserved':True,'uploaded':False,'host_apt_changed':False}

def renew(public,home,key):
    raw=Path(public)
    if raw.is_symlink():raise ValueError('Publication directory must not be a symlink')
    public=raw.resolve();home=Path(home).resolve()
    if public==home or public in home.parents:raise ValueError('Signing key must remain outside publication')
    pub=module('renew_boundary','prepare-public-release.py')
    manifest=json.loads((public/'publication-manifest.json').read_text())
    if pub.records(public)!=manifest['files']:raise ValueError('Publication manifest differs; inspect before renewal')
    work=Path(tempfile.mkdtemp(prefix='.mellipi-renew-',dir=public.parent))
    stage=work/'next';backup=work/'previous'
    try:
        shutil.copytree(public,stage)
        result=_renew_stage(stage,home,key)
        # Do not expose any partial metadata/manifest update, even on a late
        # validation failure. Both renames stay on the same filesystem.
        public.rename(backup)
        try:stage.rename(public)
        except BaseException:
            backup.rename(public);raise
        shutil.rmtree(backup)
        result['public_directory']=str(public)
        return result
    finally:
        # If rollback itself fails, retain the old tree for explicit recovery.
        if not backup.exists():shutil.rmtree(work,ignore_errors=True)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--public-directory',type=Path,default=ROOT/'public');p.add_argument('--gnupg-home',type=Path,required=True);p.add_argument('--signing-key',required=True);a=p.parse_args();print(json.dumps(renew(a.public_directory,a.gnupg_home,a.signing_key),indent=2))
if __name__=='__main__':main()
