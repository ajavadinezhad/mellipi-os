"""Private Rust IPC plus an explicit Python adapter for compatibility tests."""
import concurrent.futures, json, os, subprocess, threading, uuid
from pathlib import Path
import core
ROOT=Path(__file__).resolve().parent

class RustStore:
    backend='rust'
    def __init__(self,on_event=None):
        binary=ROOT/'backend/target/release/orbit-core'
        self.process=subprocess.Popen([str(binary)],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
        self.on_event=on_event or (lambda event:None)
        self._pending={};self._lock=threading.Lock();self._counter=0
        self._reader=threading.Thread(target=self._read,name='orbit-core-ipc',daemon=True);self._reader.start()
        self.call('ping')
    def _read(self):
        try:
            for line in self.process.stdout:
                value=json.loads(line)
                if 'event' in value: self.on_event(value); continue
                with self._lock: future=self._pending.pop(value.get('id'),None)
                if future:
                    if 'error' in value: future.set_exception(ValueError(value['error']))
                    else: future.set_result(value.get('result'))
        finally:
            with self._lock:
                for future in self._pending.values(): future.set_exception(RuntimeError('Abstract core disconnected'))
                self._pending.clear()
    def call(self,op,args=None):
        future=concurrent.futures.Future()
        with self._lock:
            self._counter+=1;ident=self._counter;self._pending[ident]=future
            try:
                self.process.stdin.write(json.dumps({'id':ident,'op':op,'args':args or {}},ensure_ascii=False)+'\n'); self.process.stdin.flush()
            except (OSError,ValueError) as e:
                self._pending.pop(ident,None);raise RuntimeError('Abstract core is unavailable') from e
        try: return future.result(timeout=5)
        except concurrent.futures.TimeoutError:
            with self._lock:self._pending.pop(ident,None)
            raise RuntimeError('Abstract core timed out')
    def state(self,workspace='',offset=0,query=''):return self.call('state',{'workspace':workspace,'offset':offset,'query':query})
    def load(self,ident):return self.call('load',{'id':ident})
    def create(self,data):return self.call('create',data)['id']
    def share(self,ident,workspace):return self.call('share',{'object':ident,'workspace':workspace})
    def remove(self,ident,workspace):return self.call('remove',{'object':ident,'workspace':workspace})
    def undo(self,token):return self.call('undo',{'token':token})
    def ask(self,prompt,ids):return self.call('ai',{'prompt':prompt,'objects':ids})['id']
    def cancel(self,job):return self.call('cancel',{'job':job})
    def close(self):
        try:self.process.stdin.close(); self.process.wait(timeout=3)
        except (OSError,subprocess.TimeoutExpired):self.process.terminate();self.process.wait(timeout=3)
        self._reader.join(timeout=2)
        self.process.stdout.close()

class LazyRustStore:
    """Preserve historical capture access without an idle subprocess.

    First explicit legacy capture/context operation starts the existing store.
    Closure without use never starts it. Startup is serialized across workers.
    """
    backend='rust'
    deferred=True
    def __init__(self,on_event=None):
        self.on_event=on_event or (lambda event:None)
        self._instance=None
        self._start_lock=threading.Lock()
        self._closed=False
    def _get(self):
        with self._start_lock:
            if self._closed:raise RuntimeError('Abstract store is closed')
            if self._instance is None:self._instance=RustStore(lambda event:self.on_event(event))
            return self._instance
    def __getattr__(self,name):
        if name.startswith('_'):raise AttributeError(name)
        return getattr(self._get(),name)
    def close(self):
        with self._start_lock:
            self._closed=True
            if self._instance is not None:self._instance.close()


class PythonStore:
    """Test adapter; production native launches the compiled Rust store."""
    backend='python'
    def __init__(self,on_event=None):self.on_event=on_event or (lambda e:None)
    def state(self,workspace='',offset=0,query=''):return core.state()
    def load(self,ident):return next(o for o in core.state()['objects'] if o['id']==ident)
    def create(self,data):return core.create_object(data)
    def share(self,ident,workspace):
        with core.connect() as db:db.execute('INSERT OR IGNORE INTO links VALUES (?,?)',(workspace,ident))
        return {'undo':None}
    def remove(self,ident,workspace):
        with core.connect() as db:db.execute('DELETE FROM links WHERE workspace=? AND object=?',(workspace,ident))
        return {'undo':None}
    def ask(self,prompt,ids):
        job=str(uuid.uuid4())
        with core.connect() as db:db.execute("INSERT INTO jobs(id,status) VALUES (?,'running')",(job,))
        def work():
            core.run_ai(job,prompt,ids,None)
            with core.connect() as db:row=db.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone()
            self.on_event(dict(event='ai_done' if row['status']=='done' else 'ai_error',job=job,text=row['result'],error=row['error']))
        threading.Thread(target=work,daemon=True).start();return job
    def cancel(self,job):pass
    def close(self):pass
