"""One cancellable local transfer at a time, staged before atomic publication.

Uses GIO's cancellable copy when available; the bounded chunk-copy fallback is
for local regular files. Existing destinations are never overwritten. No watcher,
thread or polling loop is created by this module.
"""
import errno,os,stat,tempfile,shutil,threading,time
from pathlib import Path
MAX_SOURCES=128
MAX_ENTRIES=100000
MAX_DEPTH=64
CHUNK=1024*1024

def gio_modules():
    try:
        import sys
        if '/usr/lib/python3/dist-packages' not in sys.path:sys.path.append('/usr/lib/python3/dist-packages')
        from gi.repository import Gio
        return Gio
    except (ImportError,ValueError):return None

class Cancelled(Exception):pass
class CancelToken:
    def __init__(self):
        self.event=threading.Event();self.condition=threading.Condition();self.answer=None
        Gio=gio_modules();self.gio=Gio.Cancellable() if Gio else None
    def cancel(self):
        self.event.set()
        if self.gio:self.gio.cancel()
        with self.condition:self.condition.notify_all()
    def check(self):
        if self.event.is_set():raise Cancelled('Transfer canceled')
    def resolve(self,answer):
        if answer not in ('keep-both','skip','cancel'):return
        if answer=='cancel':self.cancel();return
        with self.condition:self.answer=answer;self.condition.notify_all()
    def conflict(self,path,publish):
        self.check()
        with self.condition:self.answer=None
        publish(dict(conflict=str(path),message='An item named '+path.name+' already exists'))
        with self.condition:
            self.condition.wait_for(lambda:self.answer is not None or self.event.is_set())
            self.check();answer=self.answer;self.answer=None
        publish(dict(conflict=''))
        return answer

def identity(path):
    row=Path(path).lstat();return row.st_dev,row.st_ino,row.st_mode,row.st_size,row.st_mtime_ns

def unique_name(destination):
    destination=Path(destination)
    suffix=destination.suffix if not destination.is_dir() else ''
    stem=destination.name[:-len(suffix)] if suffix else destination.name
    for number in range(1,10001):
        candidate=destination.with_name(f'{stem} (copy{(" "+str(number)) if number>1 else ""}){suffix}')
        if not os.path.lexists(candidate):return candidate
    raise ValueError('Too many copies with the same name')

class Transfer:
    def __init__(self,directory,rename,trash=None,token=None,publish=None):
        self.directory=Path(directory);self.rename=rename;self.trash=trash;self.token=token or CancelToken();self.publish=publish or (lambda value:None)
        self.root_identity=identity(self.directory)[:2];self.entries=0;self.bytes=0;self.files=0;self.last_progress=0.;self.current='';self.current_bytes=0;self.current_total=0;self.snapshots={}
    def check_root(self):
        self.token.check()
        if self.directory.resolve()!=self.directory or identity(self.directory)[:2]!=self.root_identity:raise ValueError('The destination folder changed')
    def progress(self,force=False,**changes):
        now=time.monotonic()
        if not force and now-self.last_progress<.1:return
        self.last_progress=now
        self.publish(dict(bytes=self.bytes,files=self.files,current=self.current,currentBytes=self.current_bytes,currentTotal=self.current_total,**changes))
    def copy(self,source,destination,depth=0):
        self.token.check();self.entries+=1
        if self.entries>MAX_ENTRIES or depth>MAX_DEPTH:raise ValueError('This transfer is too large; use the file manager for this folder')
        before=identity(source);self.snapshots[str(source)]=before;mode=before[2]
        if stat.S_ISLNK(mode):os.symlink(os.readlink(source),destination)
        elif stat.S_ISDIR(mode):
            destination.mkdir(mode=0o700)
            with os.scandir(source) as items:
                for entry in items:self.copy(Path(source)/entry.name,destination/entry.name,depth+1)
            shutil.copystat(source,destination,follow_symlinks=False)
        elif stat.S_ISREG(mode):
            self.current=source.name;self.current_bytes=0;self.current_total=before[3];self.progress()
            Gio=gio_modules()
            if Gio:
                def copied(current,total,*_):
                    delta=current-self.current_bytes;self.current_bytes=current;self.current_total=total;self.bytes+=max(0,delta);self.progress()
                Gio.File.new_for_path(str(source)).copy(Gio.File.new_for_path(str(destination)),Gio.FileCopyFlags.NOFOLLOW_SYMLINKS,self.token.gio,copied,None)
            else:
                descriptor=os.open(source,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
                with os.fdopen(descriptor,'rb') as incoming,destination.open('xb') as outgoing:
                    if os.fstat(incoming.fileno()).st_ino!=before[1]:raise ValueError('The source file changed')
                    while True:
                        self.token.check();data=incoming.read(CHUNK)
                        if not data:break
                        outgoing.write(data);self.bytes+=len(data);self.current_bytes+=len(data);self.progress()
                shutil.copystat(source,destination,follow_symlinks=False)
            self.files+=1
        else:raise ValueError('Only regular files, folders and symbolic links can be transferred')
        self.token.check()
        if identity(source)!=before:raise ValueError('The source changed while it was being copied: '+source.name)
    def destination(self,name):
        result=self.directory/name
        if os.path.lexists(result):
            answer=self.token.conflict(result,self.publish)
            if answer=='skip':return None
            result=unique_name(result)
        return result
    def run(self,sources,move=False):
        if not 1<=len(sources)<=MAX_SOURCES:raise ValueError('Choose between1 and128 files')
        self.check_root();done=[];skipped=[]
        for index,source in enumerate(sources):
            self.check_root();source=Path(source);before=identity(source)
            if source.resolve()==self.directory or (stat.S_ISDIR(before[2]) and self.directory.is_relative_to(source.resolve())):raise ValueError('Cannot copy a folder into itself')
            if move and source.parent==self.directory:skipped.append(str(source));continue
            destination=self.destination(source.name)
            if destination is None:skipped.append(str(source));continue
            if source==destination:
                # Copy in place is a duplicate; cut in place changes nothing.
                if move:skipped.append(str(source));continue
            self.publish(dict(conflict='',current=source.name,completed=len(done),count=len(sources),message=('Moving ' if move else 'Copying ')+source.name))
            if move:
                try:
                    self.rename(source,destination);done.append(str(destination));self.progress(True,completed=len(done));continue
                except OSError as error:
                    if error.errno!=errno.EXDEV:raise
            # Only our private staging directory can be cleaned after failure.
            stage=Path(tempfile.mkdtemp(prefix='.abstract-transfer-',dir=self.directory));owned=identity(stage)[:2]
            try:
                self.snapshots={};staged=stage/'item';self.copy(source,staged);self.check_root()
                try:self.rename(staged,destination)
                except (FileExistsError,ValueError):
                    destination=self.destination(source.name)
                    if destination is None:skipped.append(str(source));continue
                    self.rename(staged,destination)
                done.append(str(destination));self.progress(True,completed=len(done))
                if move:
                    if any(identity(Path(path))!=saved for path,saved in self.snapshots.items()):raise ValueError('Copied successfully; the changed original was kept: '+source.name)
                    if not self.trash:raise ValueError('Copied successfully; use the file manager to remove the original')
                    try:self.trash(source)
                    except Exception as error:raise ValueError("Copied successfully; the original was kept: "+str(error)) from error
            finally:
                if stage.exists() and not stage.is_symlink() and identity(stage)[:2]==owned:shutil.rmtree(stage)
        self.progress(True,completed=len(done),message='Transfer complete')
        return dict(paths=done,skipped=skipped)
