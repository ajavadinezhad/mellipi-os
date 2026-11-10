#!/usr/bin/env python3
"""Check signed archive/key expiry without touching system APT or installing."""
import argparse,json,re,subprocess,tempfile,urllib.request
from datetime import datetime,timedelta,timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

FINGERPRINT='7D0FC30A9F2B9957B2970E3BB6B1D6FE6A4682AF'
ENDPOINTS={'Mellipi':'https://ajavadinezhad.github.io/mellipi-os/apt','Abstract':'https://ajavadinezhad.github.io/abstract-os/apt'}
LIMIT=2*1024*1024

def fetch(url):
    if not url.startswith('https://') or any(c.isspace() for c in url):raise ValueError('HTTPS archive required')
    with urllib.request.urlopen(url,timeout=30) as r:
        if not r.geturl().startswith('https://'):raise ValueError('Insecure redirect')
        data=r.read(LIMIT+1)
    if len(data)>LIMIT:raise ValueError('Archive metadata exceeds size bound')
    return data

def assess(release,key_rows,origin,now=None,warn_days=30):
    now=now or datetime.now(timezone.utc)
    fields={}
    for line in release.splitlines():
        if line and not line[0].isspace() and ':' in line:
            k,v=line.split(':',1)
            if k in fields:raise ValueError('Duplicate release field: '+k)
            fields[k]=v.strip()
    for k,v in {'Origin':origin,'Label':origin,'Suite':'noble','Codename':'noble','Architectures':'amd64','Components':'main'}.items():
        if fields.get(k)!=v:raise ValueError('Unexpected release '+k)
    issued=parsedate_to_datetime(fields['Date']);expiry=parsedate_to_datetime(fields['Valid-Until'])
    if issued.tzinfo is None or expiry.tzinfo is None or issued>now+timedelta(hours=24) or expiry<=issued:raise ValueError('Invalid release dates')
    pubs=[r.split(':') for r in key_rows.splitlines() if r.startswith('pub:')]
    fps=[r.split(':')[9] for r in key_rows.splitlines() if r.startswith('fpr:')]
    if len(pubs)!=1 or not fps or fps[0]!=FINGERPRINT:raise ValueError('Unexpected archive signing key')
    if pubs[0][1] in ('r','d','i'):raise ValueError('Signing key revoked, disabled or invalid')
    warnings=[]
    if expiry<=now+timedelta(days=warn_days):warnings.append('Archive metadata expired' if expiry<=now else 'Renew archive metadata within '+str(max(0,(expiry-now).days))+' days')
    key_expiry=int(pubs[0][6] or 0)
    if key_expiry and key_expiry<=int((now+timedelta(days=warn_days)).timestamp()):warnings.append('Archive signing key needs renewal or rotation')
    return {'origin':origin,'valid_until':expiry.isoformat(),'metadata_days_remaining':(expiry-now).days,'key_expires':datetime.fromtimestamp(key_expiry,timezone.utc).isoformat() if key_expiry else None,'warnings':warnings,'ok':not warnings}

def check(url,origin,now=None,warn_days=30):
    with tempfile.TemporaryDirectory(prefix='mellipi-update-health-') as d:
        work=Path(d);home=work/'gnupg';home.mkdir(mode=0o700)
        key=work/'key.gpg';key.write_bytes(fetch(url+'/mellipi-archive-keyring.gpg'))
        signed=work/'InRelease';signed.write_bytes(fetch(url+'/dists/noble/InRelease'))
        rows=subprocess.check_output(['gpg','--homedir',str(home),'--batch','--with-colons','--show-keys',str(key)],text=True,stderr=subprocess.DEVNULL,timeout=15)
        # Check the pinned identity before using this key to authenticate metadata.
        fps=[r.split(':')[9] for r in rows.splitlines() if r.startswith('fpr:')]
        if not fps or fps[0]!=FINGERPRINT:raise ValueError('Archive key fingerprint mismatch')
        verified=subprocess.run(['gpgv','--homedir',str(home),'--keyring',str(key),'--output','-',str(signed)],capture_output=True,text=True,timeout=15,check=True).stdout
        return dict(url=url,signature_verified=True,**assess(verified,rows,origin,now,warn_days))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--warn-days',type=int,default=30);p.add_argument('--output',type=Path);args=p.parse_args()
    if not 1<=args.warn_days<=60:p.error('Choose 1–60 days')
    results=[]
    for origin,url in ENDPOINTS.items():
        try:results.append(check(url,origin,warn_days=args.warn_days))
        except (OSError,ValueError,KeyError,subprocess.SubprocessError) as e:results.append({'url':url,'ok':False,'error':str(e)})
    report={'ok':all(r['ok'] for r in results),'archives':results,'host_apt_changed':False,'packages_installed':False}
    text=json.dumps(report,indent=2)+'\n'
    if args.output:args.output.write_text(text)
    print(text,end='');return 0 if report['ok'] else 1

if __name__=='__main__':raise SystemExit(main())
