#!/usr/bin/env python3
"""Verify a public Mellipi archive using private APT state; never installs."""
import argparse,hashlib,json,os,re,subprocess,tempfile,urllib.parse,urllib.request
from pathlib import Path

def run(args,**kwargs):return subprocess.run(args,check=True,capture_output=True,text=True,timeout=120,**kwargs).stdout

def verify(url,fingerprint):
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
        (work/'status').touch();source=work/'sources.list';source.write_text(f'deb [signed-by={key}] {url} noble main\n')
        values=[f'Dir::Etc::sourcelist={source}','Dir::Etc::sourceparts=-','Dir::Etc::main=-','Dir::Etc::parts=-',f'Dir::State::status={work}/status',f'Dir::State::lists={work}/lists',f'Dir::Cache={work}/cache',f'Dir::Log={work}/log','Debug::NoLocking=true','Acquire::Languages=none','Acquire::Retries=0',f'APT::Sandbox::User={os.getuid()}','APT::Update::Error-Mode=any']
        options=[item for value in values for item in ('-o',value)]
        run(['apt-get',*options,'update'])
        packages={}
        for package in ('mellipi-shell','mellipi-desktop'):
            policy=run(['apt-cache',*options,'policy',package]);candidate=re.search(r'Candidate: (\S+)',policy);assert candidate and candidate[1]!='(none)',policy
            version=candidate[1];run(['apt-get',*options,'download',package+'='+version],cwd=work/'downloads')
            path=next((work/'downloads').glob(package+'_*.deb'));packages[package]={'candidate':version,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size}
        return {'archive':url,'fingerprint':fingerprint,'apt_signature_and_payload_verification':True,'packages':packages,'host_apt_configuration_changed':False,'packages_installed':False}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--url',required=True);parser.add_argument('--fingerprint',required=True);args=parser.parse_args();print(json.dumps(verify(args.url,args.fingerprint),indent=2))
if __name__=='__main__':main()
