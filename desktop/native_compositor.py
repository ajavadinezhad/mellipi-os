"""Bounded client for the experimental native compositor; no Sway/session mutation."""
import json,os,socket,stat
from pathlib import Path
class NativeCompositor:
    def __init__(self,path):
        self.path=Path(path)
        info=self.path.stat()
        if not self.path.is_absolute() or self.path.is_symlink() or not stat.S_ISSOCK(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:
            raise ValueError('Expected this user’s private native compositor socket')
    def request(self,command,**values):
        payload=(json.dumps(dict(command=command,**values))+'\n').encode()
        if len(payload)>4096:raise ValueError('Request too large')
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(4);connection.connect(str(self.path));connection.sendall(payload);data=bytearray()
            while not data.endswith(b'\n'):
                block=connection.recv(16384)
                if not block:break
                data.extend(block)
                if len(data)>1048576:raise ValueError('Response too large')
        if not data:raise RuntimeError('Native compositor did not reply')
        if not data.endswith(b'\n'):raise ValueError('Incomplete native compositor response')
        result=json.loads(data)
        if not isinstance(result,dict):raise ValueError('Invalid native compositor response')
        if result.get('ok') is False:raise RuntimeError(result.get('error','Native action failed'))
        return result
    def snapshot(self):return self.request('snapshot')
    def subscribe(self,connection=None):
        """Blocking bounded event stream; caller closes its socket to cancel."""
        owned=connection is None;subscription=None
        connection=connection or socket.socket(socket.AF_UNIX)
        try:
            connection.settimeout(4);connection.connect(str(self.path));connection.sendall(b'{"command":"subscribe"}\n');connection.settimeout(None)
            with connection.makefile('rb') as stream:
                while True:
                    line=stream.readline(1048577)
                    if not line:return
                    if len(line)>1048576 or not line.endswith(b'\n'):raise ValueError('Native event too large')
                    event=json.loads(line)
                    if not isinstance(event,dict):raise ValueError('Invalid native event')
                    subscription=event.get('subscription',subscription)
                    if event.get('ok') is False:raise RuntimeError(event.get('error','Subscription failed'))
                    yield event
        finally:
            if owned:connection.close()
            if subscription is not None:
                try:self.request('unsubscribe',id=subscription)
                except (OSError,ValueError,RuntimeError):pass
    def status(self):return self.request('status')
    def windows(self):return self.request('windows')['windows']
    def switch_workspace(self,workspace,direction=None):
        if type(workspace) is not int or not 1<=workspace<=4:raise ValueError('Workspace must be 1–4')
        values=dict(workspace=workspace)
        if direction is not None:
            if direction not in (-1,1):raise ValueError('Direction must be -1 or1')
            values['direction']=direction
        return self.request('workspace',**values)
    def move(self,ident,workspace):return self.request('move',id=ident,workspace=workspace)
