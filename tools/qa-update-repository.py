#!/usr/bin/env python3
"""Verify a public Mellipi archive using private APT state; never installs."""
import argparse,hashlib,json,os,re,subprocess,tempfile,urllib.parse,urllib.request
from pathlib import Path

def run(args,**kwargs):
    result=subprocess.run(args,capture_output=True,text=True,timeout=120,**kwargs)
    if result.returncode:
        raise RuntimeError(f'{args[0]} failed ({result.returncode}):\n{result.stdout}{result.stderr}')
    return result.stdout

def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()

PAIR=('mellipi-shell','mellipi-desktop')


def installed_pair(status):
    versions={}
    for paragraph in status.split('\n\n'):
        fields=dict(line.split(': ',1) for line in paragraph.splitlines()
                    if line and not line[0].isspace() and ': ' in line)
        package=fields.get('Package')
        if package in PAIR and fields.get('Status')=='install ok installed':
            version=fields.get('Version','')
            if not re.fullmatch(r'[0-9][A-Za-z0-9.+:~\-]*',version) or package in versions:
                raise ValueError('Invalid installed desktop status')
            versions[package]=version
    if len(versions)!=2 or len(set(versions.values()))!=1:
        raise ValueError('Status must contain an installed matching shell and desktop pair')
    return versions['mellipi-shell']


def verify_transaction(work,options,previous,candidate):
    def simulate(target):
        plan=run(['apt-get',*options,'-s','--allow-downgrades','--no-remove','install',
                  *(f'{package}={target}' for package in PAIR)],env=dict(os.environ,LC_ALL='C'))
        if re.search(r'^(Remv|Purg) ',plan,re.M):
            raise ValueError('APT plan removes installed packages')
        changed=set()
        for package,version in re.findall(r'^Inst (\S+)(?: \[[^\n]*?\])? \((\S+)',plan,re.M):
            package=package.partition(':')[0]
            if package not in PAIR or version!=target:
                raise ValueError(f'APT selected an unexpected package change: {package} {version}')
            changed.add(package)
        if changed!=set(PAIR):
            raise ValueError(f'APT did not select both Mellipi packages at {target}')
        return {'version':target,'removed_packages':0}
    subprocess.run(['dpkg','--compare-versions',previous,'lt',candidate],check=True)
    upgrade=simulate(candidate)
    # Ask APT to resolve the retained, signed predecessor as well. Model the
    # successful upgrade on a copy of the installed-status file, using the
    # exact candidate metadata verified and downloaded from the signed index.
    status=work/'status'
    entries=status.read_text().split('\n\n')
    for i,entry in enumerate(entries):
        package=re.search(r'^Package: (\S+)$',entry,re.M)
        if package and package[1] in PAIR:
            file=next((work/'downloads').glob(package[1]+'_*.deb'))
            control=run(['dpkg-deb','-f',str(file)]).rstrip()
            entries[i]=control+'\nStatus: install ok installed'
    status.write_text('\n\n'.join(entries))
    downgrade=simulate(previous)
    rollback=work/'rollback'
    rollback.mkdir()
    downgrade['packages']={}
    for package in PAIR:
        run(['apt-get',*options,'download',f'{package}={previous}'],cwd=rollback)
        path=next(rollback.glob(package+'_*.deb'))
        downgrade['packages'][package]=sha256(path)
    return {'mode':'APT simulation on copied dpkg status','upgrade':upgrade,'downgrade':downgrade}


def verify(url,fingerprint,installed_status=None):
    parts=urllib.parse.urlsplit(url)
    if parts.scheme not in ('https','file') or (parts.scheme=='file' and parts.netloc):raise ValueError('Use HTTPS or a local file archive')
    if parts.username or parts.password or parts.query or parts.fragment or any(c.isspace() for c in url):raise ValueError('Invalid archive URL')
    fingerprint=fingerprint.upper()
    if not re.fullmatch(r'[A-F0-9]{40}',fingerprint):raise ValueError('Full reviewed primary fingerprint required')
    with tempfile.TemporaryDirectory(prefix='abstract-public-apt-check-') as directory:
        work=Path(directory);key=work/'archive.gpg'
        with urllib.request.urlopen(url.rstrip('/')+'/mellipi-archive-keyring.gpg',timeout=30) as response:key.write_bytes(response.read(1048576))
        home=work/'gnupg';home.mkdir(mode=0o700)
        info=run(['gpg','--homedir',str(home),'--batch','--with-colons','--show-keys',str(key)])
        assert len([r for r in info.splitlines() if r.startswith('pub:')])==1
        assert next(r.split(':')[9] for r in info.splitlines() if r.startswith('fpr:'))==fingerprint
        for folder in ('lists/partial','cache/archives/partial','log','downloads'):(work/folder).mkdir(parents=True)
        status=work/'status';status.touch()
        previous=None
        if installed_status is not None:
            with Path(installed_status).open('rb') as stream: baseline=stream.read(32*1024*1024+1)
            if len(baseline)>32*1024*1024:raise ValueError('Installed package status exceeds size bound')
            previous=installed_pair(baseline.decode())
            status.write_bytes(baseline)
        source=work/'sources.list';source.write_text(f'deb [signed-by={key}] {url} noble main\n')
        values=[f'Dir::Etc::sourcelist={source}','Dir::Etc::sourceparts=-','Dir::Etc::main=-','Dir::Etc::parts=-',f'Dir::State::status={status}',f'Dir::State::extended_states={work}/extended_states',f'Dir::State::lists={work}/lists',f'Dir::Cache={work}/cache',f'Dir::Log={work}/log','Debug::NoLocking=true','Acquire::Languages=none','Acquire::Retries=0',f'APT::Sandbox::User={os.getuid()}','APT::Update::Error-Mode=any']
        options=[item for value in values for item in ('-o',value)]
        run(['apt-get',*options,'update'])
        packages={};candidates={}
        for package in PAIR:
            policy=run(['apt-cache',*options,'policy',package]);candidate=re.search(r'Candidate: (\S+)',policy);assert candidate and candidate[1]!='(none)',policy
            candidates[package]=candidate[1]
        version=candidates['mellipi-shell']
        if candidates['mellipi-desktop']!=version:
            raise ValueError('Archive needs matching shell and desktop candidates: '+str(candidates))
        for package in candidates:
            run(['apt-get',*options,'download',package+'='+version],cwd=work/'downloads')
            path=next((work/'downloads').glob(package+'_*.deb'));packages[package]={'candidate':version,'sha256':sha256(path),'bytes':path.stat().st_size}
            if package=='mellipi-desktop':
                dependencies=run(['dpkg-deb','-f',str(path),'Depends']).split(',')
                if not any(re.fullmatch(r'mellipi-shell\s*\(\s*=\s*'+re.escape(version)+r'\s*\)', dep.strip()) for dep in dependencies):
                    raise ValueError('Desktop candidate must depend on its exact shell version')
        transaction=verify_transaction(work,options,previous,version) if previous else None
        return {'archive':url,'fingerprint':fingerprint,'apt_signature_and_payload_verification':True,'packages':packages,'transaction':transaction,'host_apt_configuration_changed':False,'packages_installed':False}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--url',required=True);parser.add_argument('--fingerprint',required=True);parser.add_argument('--installed-status',type=Path,help='Copy of dpkg status from a previous full Mellipi installation, for no-removal upgrade and recovery simulation');args=parser.parse_args();print(json.dumps(verify(args.url,args.fingerprint,args.installed_status),indent=2))
if __name__=='__main__':main()
