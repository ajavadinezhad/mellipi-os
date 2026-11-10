#!/usr/bin/env python3
import socket,sys
from control import socket_path
if len(sys.argv)!=2:sys.exit('Supply an Abstract command')
valid_workspace=sys.argv[1].startswith('workspace:') and sys.argv[1][10:].isdigit() and 1<=int(sys.argv[1][10:])<=10
valid_brightness=sys.argv[1]=='brightness-detect' or (sys.argv[1].startswith('brightness-select:') and sys.argv[1][18:].isdigit()) or (sys.argv[1].startswith('brightness-set:') and sys.argv[1][15:].isdigit() and 1<=int(sys.argv[1][15:])<=100)
if not valid_brightness and not valid_workspace and not sys.argv[1].startswith('output:') and sys.argv[1] not in ('prepare-reload','fold','launcher','ai','settings','system-settings','overview','quick','music','usage','notifications','tray','bluetooth','battery','screenshot','quit','status','capture','switch-next','switch-prev','switch-accept','switch-cancel'):sys.exit('Usage: orbitctl.py launcher|ai|settings|overview|quick|notifications|tray|quit')
try:
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(2);connection.connect(socket_path());connection.sendall((sys.argv[1]+'\n').encode())
        if sys.argv[1] in ('status','prepare-reload'):print(connection.recv(32768).decode())
except OSError:sys.exit('Abstract is not running in this session')
