"""One cancellable local transfer at a time, staged before atomic publication.

Uses GIO's cancellable copy when available; the bounded chunk-copy fallback is
for local regular files. Existing destinations are never overwritten. No watcher,
thread or polling loop is created by this module.
"""
import errno,os,stat,tempfile,shutil,threading,time
from dataclasses import dataclass
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

def filename_prefix(text, budget):
    parts=[]
    for character in text:
        size=len(os.fsencode(character))
        if size>budget:break
        parts.append(character)
        budget-=size
    return ''.join(parts)


def unique_name(destination):
    destination=Path(destination)
    suffix=destination.suffix if not destination.is_dir() else ''
    stem=destination.name[:-len(suffix)] if suffix else destination.name
    try:limit=os.pathconf(destination.parent,'PC_NAME_MAX')
    except (OSError,ValueError):limit=255
    if limit<=0:limit=255
    for number in range(1,10001):
        marker=f' (copy{(" "+str(number)) if number>1 else ""})'
        budget=limit-len(os.fsencode(marker))
        if budget<1:raise ValueError('The destination does not allow a copy name')
        ending=filename_prefix(suffix,budget-1)
        head=filename_prefix(stem,budget-len(os.fsencode(ending)))
        candidate=destination.with_name(head+marker+ending)
        if not os.path.lexists(candidate):return candidate
    raise ValueError('Too many copies with the same name')

@dataclass
class ItemReceipt:
    source: str
    state: str = 'pending'
    destination: str = ''
    detail: str = ''
    source_identity: tuple | None = None

    @property
    def retryable(self):
        # Publication is irreversible here, even if trash or cleanup later fails.
        return self.state in ('pending', 'failed', 'canceled') and not self.destination


def new_receipt(sources):
    return [ItemReceipt(str(source)) for source in sources]


class Transfer:
    def __init__(self,directory,rename,trash=None,token=None,publish=None,expected_root=None):
        self.directory=Path(directory);self.rename=rename;self.trash=trash;self.token=token or CancelToken();self.publish=publish or (lambda value:None)
        self.root_identity=identity(self.directory)[:2]
        if expected_root is not None and self.root_identity != expected_root:
            raise ValueError('The destination folder was replaced. Start a new transfer after checking the destination.')
        self.receipt=[];self.entries=0;self.bytes=0;self.files=0;self.last_progress=0.;self.current='';self.current_bytes=0;self.current_total=0;self.snapshots={}
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
                try:
                    Gio.File.new_for_path(str(source)).copy(Gio.File.new_for_path(str(destination)),Gio.FileCopyFlags.NOFOLLOW_SYMLINKS,self.token.gio,copied,None)
                except Exception:
                    self.token.check()
                    raise
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
    def run(self,sources,move=False,receipt=None):
        if not 1<=len(sources)<=MAX_SOURCES:raise ValueError(f'Choose between 1 and {MAX_SOURCES} items')
        self.receipt=receipt if receipt is not None else new_receipt(sources)
        if [row.source for row in self.receipt]!=[str(source) for source in sources]:
            raise ValueError('Transfer receipt does not match the source items')
        done=[];skipped=[]
        for source,result in zip(sources,self.receipt):
            try:
                self.transfer_item(Path(source),result,move,len(sources),done,skipped)
            except Exception as error:
                if result.state!='transferred':
                    result.state=('copied' if result.destination else
                                  'canceled' if isinstance(error,Cancelled) else 'failed')
                result.detail=str(error)
                raise
        self.progress(True,completed=len(done),message='Transfer complete')
        return dict(paths=done,skipped=skipped)

    def transfer_item(self,source,result,move,count,done,skipped):
        self.check_root()
        before=identity(source)
        if result.source_identity is not None and result.source_identity!=before:
            raise ValueError('The source was replaced or changed. Start a new transfer after checking the source.')
        result.source_identity=before
        if source.resolve()==self.directory or (stat.S_ISDIR(before[2]) and self.directory.is_relative_to(source.resolve())):
            raise ValueError('Cannot copy a folder into itself')

        def skip():
            result.state='skipped'
            skipped.append(str(source))

        def published(destination):
            result.destination=str(destination)
            # A cross-device move is only fully done once removal of the source succeeds.
            result.state='copied' if move else 'transferred'
            done.append(result.destination)

        if move and source.parent==self.directory:
            skip()
            return
        destination=self.destination(source.name)
        if destination is None:
            skip()
            return
        self.current=source.name;self.current_bytes=0;self.current_total=0
        self.publish(dict(conflict='',current=source.name,currentBytes=0,currentTotal=0,
            completed=len(done),count=count,message=('Moving ' if move else 'Copying ')+source.name))
        if move:
            try:
                self.check_root()
                if identity(source)!=before:
                    raise ValueError('The source changed before it could be moved: '+source.name)
                self.rename(source,destination)
                published(destination)
                result.state='transferred'
                self.progress(True,completed=len(done))
                return
            except OSError as error:
                if error.errno!=errno.EXDEV:raise
        # Only our private staging directory can be cleaned after failure.
        stage=Path(tempfile.mkdtemp(prefix='.mellipi-transfer-',dir=self.directory));owned=identity(stage)[:2]
        try:
            self.snapshots={};staged=stage/'item'
            if identity(source)!=before:
                raise ValueError('The source changed before it could be copied: '+source.name)
            self.copy(source,staged);self.check_root()
            try:self.rename(staged,destination)
            except (FileExistsError,ValueError):
                destination=self.destination(source.name)
                if destination is None:
                    skip()
                    return
                self.check_root()
                self.rename(staged,destination)
            published(destination)
            if move:
                self.token.check()
                if any(identity(Path(path))!=saved for path,saved in self.snapshots.items()):
                    raise ValueError('Copied successfully; the changed original was kept: '+source.name)
                if not self.trash:raise ValueError('Copied successfully; use the file manager to remove the original')
                try:self.trash(source)
                except Exception as error:raise ValueError('Copied successfully; could not confirm removal of the original: '+str(error)) from error
                result.state='transferred'
            self.progress(True,completed=len(done))
        finally:
            if stage.exists() and not stage.is_symlink() and identity(stage)[:2]==owned:shutil.rmtree(stage)
