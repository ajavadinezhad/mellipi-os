"""Bounded desktop-folder icons and explicit file actions; no thumbnails or polling."""
import configparser,os,re,stat,subprocess,json,tempfile,shutil,ctypes,errno,mimetypes,datetime
from urllib.parse import urlsplit
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from qt_compat import QObject,Property,Signal,Slot,QUrl,QDesktopServices,QApplication,QT5
if QT5:
    from PyQt5.QtCore import QFileSystemWatcher,QStandardPaths,QCoreApplication,QEvent,QTimer,QMimeData
else:
    from PySide6.QtCore import QFileSystemWatcher,QStandardPaths,QCoreApplication,QEvent,QTimer,QMimeData
import desktop
from file_transfers import Transfer,CancelToken,Cancelled,gio_modules,MAX_SOURCES
MAX_ITEMS=128
MAX_SCAN=512

def desktop_directory():
    location=QStandardPaths.DesktopLocation if QT5 else QStandardPaths.StandardLocation.DesktopLocation
    return Path(QStandardPaths.writableLocation(location) or str(Path.home()/'Desktop')).expanduser().resolve()

def shortcut_metadata(path):
    try:
        if path.stat().st_size>65536:return None
        parser=configparser.ConfigParser(interpolation=None,strict=False);parser.read_string(path.read_text(encoding='utf-8'))
        entry=parser['Desktop Entry']
        return dict(name=(entry.get('Name') or path.stem)[:160],icon=entry.get('Icon','application-x-executable')[:256],application=entry.get('Type')=='Application' and (bool(entry.get('Exec')) or entry.get('DBusActivatable','false').lower()=='true'),hidden=entry.get('Hidden','false').lower()=='true')
    except (OSError,ValueError,configparser.Error,UnicodeError,KeyError):return None

def file_icon(path):
    suffix=path.suffix.lower()
    for extensions,icon in [({'.png','.jpg','.jpeg','.gif','.webp','.svg','.bmp'},'image-x-generic'),({'.mp3','.ogg','.wav','.flac','.m4a'},'audio-x-generic'),({'.mp4','.webm','.mkv','.avi','.mov'},'video-x-generic'),({'.zip','.tar','.gz','.7z','.xz','.bz2'},'package-x-generic'),({'.pdf'},'application-pdf'),({'.doc','.docx','.odt'},'x-office-document'),({'.xls','.xlsx','.ods','.csv'},'x-office-spreadsheet'),({'.ppt','.pptx','.odp'},'x-office-presentation')]:
        if suffix in extensions:return icon
    return 'text-x-generic'

def scan_desktop(directory):
    root=Path(directory);items=[];truncated=False
    if root==Path.home().resolve():return dict(items=[],truncated=False,reason='Desktop folder is disabled in XDG user directories')
    try:
        with os.scandir(root) as entries:
            for index,entry in enumerate(entries):
                if index>=MAX_SCAN:truncated=True;break
                if entry.name.startswith('.'):continue
                try:
                    path=root/entry.name
                    if entry.is_dir():kind='folder';icon='folder';name=entry.name
                    elif entry.is_file():
                        kind='file';icon=file_icon(path);name=entry.name
                        if path.suffix.lower()=='.desktop':
                            metadata=shortcut_metadata(path)
                            if metadata and metadata['hidden']:continue
                            kind='launcher';icon=metadata['icon'] if metadata else 'application-x-executable';name=metadata['name'] if metadata else path.stem
                    else:continue
                    items.append(dict(id=str(path),path=str(path),name=name[:160],icon=icon,url=QUrl.fromLocalFile(str(path)).toString(),kind=kind))
                except OSError:continue
    except OSError as error:return dict(items=[],truncated=False,reason='Desktop folder unavailable: '+str(error)[:140])
    items.sort(key=lambda item:(item['kind']!='folder',item['name'].casefold(),item['path']))
    return dict(items=items[:MAX_ITEMS],truncated=truncated or len(items)>MAX_ITEMS,reason='')

def trusted_launcher(path):
    """Explicit launch only: trusted installed entry or executable user-owned file."""
    metadata=shortcut_metadata(path)
    if not metadata or not metadata['application']:return False
    try:
        target=path.resolve(strict=True);info=target.stat()
        if info.st_uid==os.getuid() and info.st_mode&stat.S_IXUSR and not info.st_mode&0o022:return True
        return any(Path(app['path']).resolve()==target for app in desktop.applications())
    except OSError:return False

def launch_shortcut(path,files=()):
    result=subprocess.run(['gio','launch',str(path),*[str(file) for file in files]],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5,env=desktop.application_environment(),check=False,start_new_session=True)
    if result.returncode:raise RuntimeError('The desktop shortcut could not be launched')

def reveal_item(url):
    try:
        import sys
        if '/usr/lib/python3/dist-packages' not in sys.path:sys.path.append('/usr/lib/python3/dist-packages')
        from gi.repository import Gio,GLib
        bus=Gio.bus_get_sync(Gio.BusType.SESSION,None)
        bus.call_sync('org.freedesktop.FileManager1','/org/freedesktop/FileManager1','org.freedesktop.FileManager1','ShowItems',GLib.Variant('(ass)',([url],'')),None,Gio.DBusCallFlags.NONE,1500,None)
        return True
    except Exception:return False

def safe_name(name):
    if not isinstance(name,str) or not name.strip() or name in ('.','..') or '/' in name or '\\' in name or any(ord(c)<32 for c in name) or len(name.encode('utf-8'))>240:
        raise ValueError('Enter a file name without slashes or control characters')
    return name.strip()

def rename_no_replace(source,destination):
    """Linux atomic no-replace rename; existing files and links are never clobbered."""
    libc=ctypes.CDLL(None,use_errno=True)
    function=getattr(libc,'renameat2',None)
    if function is None:raise OSError('This system does not support safe no-replace rename')
    function.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
    if function(-100,os.fsencode(source),-100,os.fsencode(destination),1):
        code=ctypes.get_errno()
        if code==errno.EEXIST:raise ValueError('An item with that name already exists')
        raise OSError(code,os.strerror(code))

def trash_item(path):
    # GIO handles the user trash location, metadata and recoverability.
    result=subprocess.run(['gio','trash','--',str(path)],env=desktop.application_environment(),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=15,check=False)
    if result.returncode:raise OSError('Could not move this item to Trash')


class DesktopIcons(QObject):
    changed=Signal();notice=Signal(str);completed=Signal(object);editRequested=Signal(str,str);folderRequested=Signal();selectionChanged=Signal();transferChanged=Signal();transferEvent=Signal(object);filePanelChanged=Signal()
    def __init__(self,enabled=False,parent=None,directory=None,opener=None,launcher=None,places=None):
        super().__init__(parent);self.root=Path(directory).expanduser().resolve() if directory is not None else desktop_directory();self.opener=opener or QDesktopServices.openUrl;self.launcher=launcher or launch_shortcut
        self.layout_path=Path(os.environ.get('ORBIT_DATA',str(self.root.parent/'.orbit-desktop-layout') if directory is not None else str(Path.home()/'.local/share/orbit-shell')))/'desktop-layout.json'
        self._layout=self.read_layout();self.layout_timer=QTimer(self);self.layout_timer.setSingleShot(True);self.layout_timer.setInterval(250);self.layout_timer.timeout.connect(self.save_layout)
        self._places_enabled=(directory is None) if places is None else bool(places)
        self._places=[dict(id='orbit-place:home',path='orbit-place:home',name='Home',icon='user-home',url=QUrl.fromLocalFile(str(Path.home())).toString(),kind='place'),dict(id='orbit-place:root',path='orbit-place:root',name='File system',icon='drive-harddisk',url='file:///',kind='place'),dict(id='orbit-place:trash',path='orbit-place:trash',name='Trash',icon='user-trash',url='trash:///',kind='place')]
        self._selection=[];self._transfer={};self._transfer_token=None;self._file_panel={};self._open_with_apps={}
        self.transferEvent.connect(self.updateTransfer)
        self._enabled=False;self._items=[];self._known=set();self._truncated=False;self._reason='';self._closed=False;self._refreshing=False;self._refresh_again=False;self._pending=set();self._catalog=None
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='orbit-desktop');self.completed.connect(self.apply)
        self.watcher=QFileSystemWatcher(self);self.watcher.directoryChanged.connect(self.refresh);self.watcher.fileChanged.connect(self.refresh);self.setEnabled(enabled)
    items=Property('QVariantList',lambda self:[dict(item) for item in ((self._places if self._places_enabled and self._enabled else [])+self._items)[:MAX_ITEMS]],notify=changed)
    enabled=Property(bool,lambda self:self._enabled,notify=changed)
    truncated=Property(bool,lambda self:self._truncated,notify=changed)
    reason=Property(str,lambda self:self._reason,notify=changed)
    directory=Property(str,lambda self:str(self.root),constant=True)
    selectedFiles=Property('QVariantList',lambda self:list(self._selection),notify=selectionChanged)
    transferState=Property('QVariantMap',lambda self:dict(self._transfer),notify=transferChanged)
    filePanel=Property('QVariantMap',lambda self:dict(self._file_panel),notify=filePanelChanged)
    @Slot('QVariantList')
    def setSelection(self,values):
        chosen=list(dict.fromkeys(str(value) for value in values[:MAX_ITEMS] if str(value) in self._known))
        if chosen!=self._selection:self._selection=chosen;self.selectionChanged.emit()
    def selected_paths(self,values):
        if not isinstance(values,(list,tuple)):raise ValueError('Choose desktop files')
        if not values:values=self._selection
        paths=[]
        for value in list(dict.fromkeys(str(value) for value in values[:MAX_ITEMS])):
            if self.place(value):continue
            paths.append(self.validate(value))
        if not paths:raise ValueError('Choose desktop files first')
        return paths
    def file_mime(self,paths,cut=False):
        mime=QMimeData();urls=[QUrl.fromLocalFile(str(path)) for path in paths]
        mime.setUrls(urls);mime.setText('\n'.join(str(path) for path in paths))
        mime.setData('x-special/gnome-copied-files',(('cut' if cut else 'copy')+'\n'+'\n'.join(bytes(url.toEncoded()).decode('ascii') for url in urls)).encode('utf-8'))
        return mime
    def put_files(self,values,cut=False):
        try:
            paths=self.selected_paths(values);app=QApplication.instance()
            if app:app.clipboard().setMimeData(self.file_mime(paths,cut))
            self.notice.emit(('Cut ' if cut else 'Copied ')+str(len(paths))+(' item' if len(paths)==1 else ' items'))
        except (OSError,ValueError) as error:self.notice.emit(str(error))
    @Slot('QVariantList')
    def copyFiles(self,values):self.put_files(values,False)
    @Slot('QVariantList')
    def cutFiles(self,values):self.put_files(values,True)
    @Slot()
    def pasteFiles(self):
        if not self._enabled or self._closed:return
        app=QApplication.instance();mime=app.clipboard().mimeData() if app else None
        if mime is None:return
        raw=bytes(mime.data('x-special/gnome-copied-files'))
        if len(raw)>524288:self.notice.emit('Clipboard file list is too large');return
        move=False;urls=[]
        if raw:
            try:
                lines=raw.decode('utf-8').splitlines()
                if lines and lines[0] in ('copy','cut'):move=lines[0]=='cut';urls=lines[1:]
            except UnicodeError:self.notice.emit('Clipboard file list is invalid');return
        if not urls:
            uri_data=bytes(mime.data('text/uri-list'))
            if len(uri_data)>524288:self.notice.emit('Clipboard file list is too large');return
            try:urls=[line.strip() for line in uri_data.decode('utf-8').splitlines() if line.strip() and not line.startswith('#')]
            except UnicodeError:self.notice.emit('Clipboard file list is invalid');return
        if not urls:self.notice.emit('Copy or cut files before pasting');return
        self.beginTransfer(urls,move,raw)
    @Slot('QVariantList')
    def trashFiles(self,values):
        try:paths=self.selected_paths(values)
        except (OSError,ValueError) as error:self.notice.emit(str(error));return
        def work():
            self.writable_root()
            for path in paths:self.validate(str(path));trash_item(path)
        self.action('bulk-trash',work,lambda _:(self.refresh(),self.notice.emit('Moved '+str(len(paths))+' items to Trash')))
    @Slot(object)
    def updateTransfer(self,value):
        if self._closed:return
        self._transfer.update(value);self.transferChanged.emit()
    @Slot()
    def clearTransferStatus(self):
        if not self._transfer.get('busy'):self._transfer={};self.transferChanged.emit()
    @Slot()
    def cancelTransfer(self):
        if self._transfer_token:self._transfer_token.cancel()
    @Slot(str)
    def resolveTransferConflict(self,choice):
        if self._transfer_token:self._transfer_token.resolve(choice)
    def beginTransfer(self,values,move=False,clipboard_raw=b''):
        app=QApplication.instance()
        if self._transfer.get('busy'):self.notice.emit('Finish or cancel the current transfer first');return
        if len(self._pending)>=8:self.notice.emit('Wait for the desktop action to finish');return
        if not values or len(values)>MAX_SOURCES:self.notice.emit('Transfer at most128 items at a time');return
        urls=[]
        for value in values:
            if not isinstance(value,str) or len(value)>4096:self.notice.emit('Invalid file location');return
            url=QUrl(value)
            if (url.isLocalFile() and url.host() not in ('','localhost')) or (not url.isLocalFile() and not (not move and url.scheme().lower() in ('http','https') and url.host() and not any(c in value for c in '\r\n'))):
                self.notice.emit('Drop local files or web links');return
            urls.append(url)
        self._transfer_token=CancelToken();token=self._transfer_token
        self._transfer=dict(busy=True,conflict='',current='',bytes=0,files=0,completed=0,count=len(urls),message='Preparing transfer')
        self.transferChanged.emit()
        originals=[Path(url.toLocalFile()) for url in urls if url.isLocalFile()]
        def publish(value):
            if not self._closed:self.transferEvent.emit(value)
        def work():
            self.writable_root()
            with tempfile.TemporaryDirectory(prefix='abstract-file-links-') as temp:
                sources=[]
                for url in urls:
                    if url.isLocalFile():
                        source=Path(url.toLocalFile())
                        if not source.is_absolute() or not os.path.lexists(source):raise ValueError('The source file is unavailable')
                    else:
                        source=Path(temp)/safe_name('Link-'+re.sub(r'[^A-Za-z0-9._-]','_',url.host())[:80]+'.desktop')
                        source.write_text('[Desktop Entry]\nType=Link\nName='+url.host()+'\nIcon=text-html\nURL='+url.toString()+'\n')
                    sources.append(source)
                try:return Transfer(self.root,rename_no_replace,trash_item,token,publish).run(sources,move)
                except Cancelled:return dict(canceled=True)
                except Exception:
                    if token.event.is_set():return dict(canceled=True)
                    raise
        def done(result):
            self._transfer_token=None;self._transfer.update(busy=False,conflict='',message='Transfer canceled' if result.get('canceled') else 'Transfer complete');self.transferChanged.emit();self.refresh()
            if move and clipboard_raw and app:
                current=app.clipboard().mimeData()
                if current and bytes(current.data('x-special/gnome-copied-files'))==clipboard_raw:
                    remaining=[path for path in originals if os.path.lexists(path)]
                    if remaining:app.clipboard().setMimeData(self.file_mime(remaining,True))
                    else:app.clipboard().clear()
        self.action('transfer',work,done)
    @Slot()
    def closeFilePanel(self):self._file_panel={};self._open_with_apps={};self.filePanelChanged.emit()
    @Slot(str)
    def properties(self,value):
        try:path=self.validate(value)
        except (OSError,ValueError) as error:self.notice.emit(str(error));return
        def work():
            info=path.lstat();kind='Symbolic link' if path.is_symlink() else 'Folder' if path.is_dir() else (mimetypes.guess_type(path.name)[0] or 'File')
            return dict(kind='properties',name=path.name,path=str(path),type=kind,size='' if path.is_dir() else str(info.st_size)+' bytes',modified=datetime.datetime.fromtimestamp(info.st_mtime).strftime('%Y-%m-%d %H:%M'),permissions=stat.filemode(info.st_mode),target=os.readlink(path) if path.is_symlink() else '')
        def done(value):self._file_panel=value;self.filePanelChanged.emit()
        self.action('properties',work,done)
    @Slot(str)
    def openWith(self,value):
        try:path=self.validate(value)
        except (OSError,ValueError) as error:self.notice.emit(str(error));return
        if path.is_dir():self.reveal(value);return
        def work():
            Gio=gio_modules()
            if not Gio:raise ValueError('Application selection requires the installed GIO library')
            content_type,_=Gio.content_type_guess(str(path),None)
            apps=Gio.AppInfo.get_all_for_type(content_type)
            if not apps:apps=Gio.AppInfo.get_all()
            rows=[];mapping={}
            for app in apps:
                ident=app.get_id()
                if not ident or not app.should_show() or ident in mapping:continue
                icon=app.get_icon();icon_name=icon.get_names()[0] if icon and hasattr(icon,'get_names') and icon.get_names() else 'application-x-executable'
                rows.append(dict(id=ident,name=app.get_display_name(),icon=icon_name));mapping[ident]=app
                if len(rows)>=128:break
            rows.sort(key=lambda row:row['name'].casefold())
            return rows,mapping
        def done(value):
            rows,self._open_with_apps=value;self._file_panel=dict(kind='open-with',name=path.name,path=str(path),apps=rows);self.filePanelChanged.emit()
        self.action('open-with',work,done)
    @Slot(str)
    def chooseApplication(self,ident):
        info=self._open_with_apps.get(ident);value=self._file_panel.get('path')
        if info is None or not value:return
        try:path=self.validate(value)
        except (OSError,ValueError) as error:self.notice.emit(str(error));return
        def work():
            launcher=info.get_filename() if hasattr(info,'get_filename') else None
            if not isinstance(launcher,str) or not Path(launcher).is_absolute() or not Path(launcher).is_file():raise ValueError('This application no longer has an installed launcher')
            launch_shortcut(Path(launcher),[path])
        self.action('open-with-launch',work,lambda _:self.closeFilePanel())
    def read_layout(self):
        try:
            if self.layout_path.stat().st_size>262144:return {}
            value=json.loads(self.layout_path.read_text())
            if not isinstance(value,dict):return {}
            outputs={}
            for output,items in list(value.items())[:8]:
                if not isinstance(output,str) or len(output)>160 or not isinstance(items,dict):continue
                outputs[output]={key:[v[0],v[1]] for key,v in list(items.items())[:MAX_ITEMS] if isinstance(key,str) and len(key)<4096 and isinstance(v,list) and len(v)==2 and all(type(n) is int and 0<=n<128 for n in v)}
            return outputs
        except (OSError,ValueError,TypeError):return {}
    def prune_layout(self):
        known=self._known|{item['path'] for item in self._places}
        dirty=False
        for items in self._layout.values():
            for key in list(items):
                if key not in known:items.pop(key,None);dirty=True
        if dirty:self.layout_timer.start()
    def save_layout(self):
        if not self._layout:return
        try:
            self.layout_path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            fd,name=tempfile.mkstemp(prefix='.desktop-layout-',dir=self.layout_path.parent)
            try:
                with os.fdopen(fd,'w') as output:json.dump(self._layout,output,separators=(',',':'));output.flush();os.fsync(output.fileno())
                os.replace(name,self.layout_path)
            finally:
                if os.path.exists(name):os.unlink(name)
        except OSError as error:self.notice.emit('Could not save desktop positions: '+str(error)[:100])
    @Slot(str,int,int,result='QVariantMap')
    def layout(self,output,columns,rows):
        columns=max(1,min(128,columns));rows=max(1,min(128,rows));saved=self._layout.get(output,{});positions={};occupied=set()
        for item in self.items:
            point=saved.get(item['path'])
            if point is not None:
                cell=(min(columns-1,point[0]),min(rows-1,point[1]))
                if cell not in occupied:positions[item['path']]=list(cell);occupied.add(cell)
        for item in self.items:
            if item['path'] in positions:continue
            cell=next(((n%columns,n//columns) for n in range(columns*rows) if (n%columns,n//columns) not in occupied),None)
            if cell is None:break
            positions[item['path']]=list(cell);occupied.add(cell)
        return positions
    @Slot(str,str,int,int)
    def setPosition(self,path,output,column,row):
        if not self.place(path) and path not in self._known:return
        if not isinstance(output,str) or not output or len(output)>160:return
        if output not in self._layout and len(self._layout)>=8:return
        items=self._layout.setdefault(output,{})
        if path not in items and len(items)>=MAX_ITEMS:return
        target=[max(0,min(127,column)),max(0,min(127,row))];old=items.get(path)
        other=next((key for key,value in items.items() if key!=path and value==target),None)
        if other:
            if old is not None:items[other]=old
            else:items.pop(other,None)
        items[path]=target;self.layout_timer.start();self.changed.emit()
    @Slot(str)
    def arrange(self,output):
        if not self._enabled or self._closed or not isinstance(output,str) or not output or len(output)>160:return
        if output not in self._layout and len(self._layout)>=8:return
        self._layout.pop(output,None)
        # Keep an explicit empty output so arranging the last display is persisted.
        self._layout[output]={};self.layout_timer.start();self.changed.emit()
    @Slot(str)
    def requestRename(self,value):
        try:self.editRequested.emit(value,self.validate(value).name)
        except (OSError,ValueError) as error:self.notice.emit(str(error))
    @Slot()
    def requestNewFolder(self):
        if self._enabled and not self._closed:self.folderRequested.emit()
    def writable_root(self):
        if not self._enabled or self._closed or self.root==Path.home().resolve() or self.root.resolve()!=self.root:raise ValueError('The Desktop folder is unavailable')
        self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        if self.root.resolve()!=self.root:raise ValueError('The Desktop folder location changed')
    @Slot(str,str)
    def rename(self,value,name):
        def work():
            path=self.validate(value);destination=self.root/safe_name(name)
            if destination==path:return str(path)
            self.writable_root();rename_no_replace(path,destination);return str(destination)
        def done(destination):
            for items in self._layout.values():
                if value in items:items[destination]=items.pop(value)
            self.layout_timer.start();self.refresh()
        self.action('rename:'+value,work,done)
    @Slot(str)
    def moveToTrash(self,value):
        def work():
            path=self.validate(value);self.writable_root();trash_item(path)
        self.action('trash:'+value,work,lambda _:self.refresh())
    @Slot(str)
    def newFolder(self,name):
        def work():
            self.writable_root();(self.root/safe_name(name)).mkdir(mode=0o700)
        self.action('new-folder',work,lambda _:self.refresh())
    @Slot('QVariantList')
    def dropUrls(self,values):
        if self._enabled and not self._closed:self.beginTransfer([str(value) for value in values])
    @Slot(bool)
    def setEnabled(self,value):
        if self._closed or self._enabled==bool(value):return
        self._enabled=bool(value)
        if self._enabled:self.refresh()
        else:
            self._items=[];self._known=set();self.setSelection([]);self._truncated=False;self._reason='';self.watch()
        self.changed.emit()
    def submit(self,kind,work,done=None):
        future=self.pool.submit(work)
        def finished(result):
            if self._closed:return
            try:data=dict(kind=kind,value=result.result(),done=done)
            except Exception as error:data=dict(kind=kind,error=str(error)[:220])
            if not self._closed:self.completed.emit(data)
        future.add_done_callback(finished)
    @Slot()
    def refresh(self,*_):
        if self._closed or not self._enabled:return
        if self._refreshing:self._refresh_again=True;return
        self._refreshing=True;self.submit('scan',lambda:scan_desktop(self.root))
    def watch(self):
        wanted=set()
        if self._enabled and self.root!=Path.home().resolve():
            wanted.update(str(path) for path in (self.root,self.root.parent) if path.is_dir())
            wanted.update(item['path'] for item in self._items if item['kind']=='launcher' and Path(item['path']).is_file())
        old=set(self.watcher.files()+self.watcher.directories())
        if old-wanted:self.watcher.removePaths(list(old-wanted))
        if wanted-old:self.watcher.addPaths(list(wanted-old))
    @Slot(object)
    def apply(self,data):
        if self._closed:return
        if data['kind']=='scan':
            self._refreshing=False
            if self._enabled:
                value=data.get('value',dict(items=[],truncated=False,reason=data.get('error','Desktop folder unavailable')))
                self._items=value['items'];self._known={item['path'] for item in self._items};self.setSelection(self._selection);self.prune_layout();self._truncated=value['truncated'];self._reason=value['reason'];self.watch();self.changed.emit()
            if self._refresh_again:self._refresh_again=False;self.refresh()
        else:
            self._pending.discard(data['kind'])
            if 'error' in data:
                if data['kind']=='transfer':self._transfer_token=None;self._transfer.update(busy=False,conflict='',message=data['error']);self.transferChanged.emit();self.refresh()
                self.notice.emit(data['error'])
            elif data.get('done'):data['done'](data.get('value'))
    def validate(self,value):
        if not self._enabled or self._closed or not isinstance(value,str) or value not in self._known:raise ValueError('Choose an existing desktop item')
        path=Path(value)
        if not path.is_absolute() or path.parent!=self.root or not path.exists():raise ValueError('Desktop item moved or was removed')
        if not path.is_dir() and not path.is_file():raise ValueError('Unsupported desktop item')
        return path
    def action(self,kind,work,done=None):
        if kind in self._pending:return
        if len(self._pending)>=8:self.notice.emit('Wait for the desktop action to finish');return
        self._pending.add(kind);self.submit(kind,work,done)
    def place(self,value):
        return next((item for item in self._places if item['path']==value),None) if self._enabled and self._places_enabled else None
    @Slot(str)
    def open(self,value):
        item=self.place(value)
        if item:
            if not self.opener(QUrl(item['url'])):self.notice.emit('Could not open '+item['name'])
            return
        try:
            path=self.validate(value)
            if path.suffix.lower()=='.desktop' and path.is_file():
                parser=configparser.ConfigParser(interpolation=None,strict=False)
                try:
                    parser.read_string(path.read_text(encoding='utf-8'));entry=parser['Desktop Entry']
                    if entry.get('Type')=='Link':
                        url=QUrl(entry.get('URL',''))
                        if url.scheme() not in ('http','https') or not url.host():raise ValueError('This desktop link is invalid')
                        if not self.opener(url):raise ValueError('Could not open this link')
                        return
                except (configparser.Error,KeyError,UnicodeError) as error:raise ValueError('This desktop shortcut is invalid') from error
                def launch():
                    self.validate(value)
                    if not trusted_launcher(path):raise PermissionError('This shortcut is not trusted. Mark a known local launcher executable before opening it')
                    self.launcher(path)
                self.action('open:'+value,launch)
            elif not self.opener(QUrl.fromLocalFile(str(path))):self.notice.emit('No application could open this desktop item')
        except (OSError,ValueError) as error:self.notice.emit(str(error))
    @Slot(str)
    def reveal(self,value):
        if self.place(value):self.open(value);return
        try:
            path=self.validate(value);url=QUrl.fromLocalFile(str(path)).toString()
            self.action('reveal:'+value,lambda:reveal_item(url),lambda shown:None if shown else self.opener(QUrl.fromLocalFile(str(self.root))))
        except (OSError,ValueError) as error:self.notice.emit(str(error))
    @Slot(str)
    def addShortcut(self,app_id):
        if self._closed:return
        if not isinstance(app_id,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+-]{0,200}\.desktop',app_id):
            self.notice.emit('Choose an installed application for the desktop shortcut');return
        def create():
            if self._catalog is None or app_id not in self._catalog:self._catalog={app['id']:app for app in desktop.applications()}
            app=self._catalog.get(app_id)
            if app is None:raise ValueError('This application is not in the installed application catalog')
            source=Path(app['path']).resolve(strict=True)
            if not source.is_file() or source.stat().st_size>65536:raise ValueError('The application launcher is unavailable or too large')
            metadata=shortcut_metadata(source)
            if not metadata or not metadata['application'] or metadata['hidden']:raise ValueError('The application launcher is invalid')
            if self.root==Path.home().resolve():raise ValueError('Choose an enabled XDG Desktop folder before adding shortcuts')
            if self.root.resolve()!=self.root:raise ValueError('The Desktop folder location changed; enable desktop icons again')
            self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
            if self.root.resolve()!=self.root or not self.root.is_dir():raise ValueError('The Desktop folder location changed; enable desktop icons again')
            destination=self.root/app_id
            try:os.symlink(str(source),str(destination))
            except FileExistsError:raise ValueError('A desktop item named '+app_id+' already exists')
            return app.get('name',app_id)
        def added(name):self.refresh();self.notice.emit('Added '+name+' to Desktop')
        self.action('shortcut:'+app_id,create,added)
    @Slot(str)
    def copyPath(self,value):
        item=self.place(value)
        if item:
            app=QApplication.instance();url=QUrl(item['url'])
            if app:app.clipboard().setText(url.toLocalFile() if url.isLocalFile() else item['url'])
            return
        try:
            path=self.validate(value);app=QApplication.instance()
            if app:app.clipboard().setText(str(path))
        except (OSError,ValueError) as error:self.notice.emit(str(error))
    def close(self):
        if self._closed:return
        self.cancelTransfer();self.layout_timer.stop();self.save_layout();self._closed=True;self.watcher.directoryChanged.disconnect();self.watcher.fileChanged.disconnect()
        paths=self.watcher.files()+self.watcher.directories()
        if paths:self.watcher.removePaths(paths)
        self.pool.shutdown(wait=True,cancel_futures=True)
        self.completed.disconnect()
        # Dispose the native watch engine on its Qt thread before future/callback
        # references can be collected on an executor thread.
        self.watcher.deleteLater();QCoreApplication.sendPostedEvents(self.watcher,QEvent.Type.DeferredDelete)
