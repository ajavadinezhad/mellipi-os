#!/usr/bin/env python3
"""Extract missing official Ubuntu runtime packages locally; never runs maintainer scripts."""
import re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; cache=ROOT/'.wayland-packages';cache.mkdir(exist_ok=True)
base=['xdg-desktop-portal-wlr','slurp','libqt5gui5t64','libqt5quick5','sway','swaybg','swayidle','swaylock','grim','layer-shell-qt','liblayershellqtinterface5','python3-pyqt5','python3-pyqt5.qtquick','qtwayland5','qml-module-qtquick2','qml-module-qtquick-controls2','qml-module-qtquick-layouts','qml-module-qtquick-window2','qml-module-qtqml-models2','qml-module-qtqml-workerscript2']
queue=list(base);seen=set();needed=[]
while queue:
    package=queue.pop(0)
    if package in seen or package.endswith("-gles"):continue
    seen.add(package)
    status=subprocess.run(['dpkg-query','-W','-f=${Status}',package],capture_output=True,text=True)
    if status.returncode==0 and status.stdout=='install ok installed':continue
    info=subprocess.run(['/usr/bin/apt-cache','depends',package],capture_output=True,text=True,check=True).stdout
    needed.append(package)
    for line in info.splitlines():
        match=re.match(r'\s*(?:PreDepends|Depends): ([\w.+-]+)(?::\w+)?$',line)
        if match:queue.append(match.group(1))
print('Missing runtime packages:',', '.join(needed),flush=True)
subprocess.run(['/usr/bin/apt-get','download',*needed],cwd=cache,check=True)
for deb in cache.glob('*.deb'):
    if '-gles_' in deb.name:continue
    subprocess.run(['dpkg-deb','-x',str(deb),str(ROOT/'.wayland-runtime')],check=True)
print('Extracted:',len(list(cache.glob('*.deb'))),'packages',flush=True)

subprocess.run(['/usr/bin/python3',str(ROOT/'tools/prepare-wayland-runtime.py')],check=True)
