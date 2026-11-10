"""Event-driven desktop-entry refresh and finite application launch acceptance."""
import os,subprocess,threading,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from qt_compat import QObject,Signal,Slot,QTimer,QT5,dispose_native_io
if QT5:
    from PyQt5.QtCore import QFileSystemWatcher
else:
    from PySide6.QtCore import QFileSystemWatcher
import desktop
MAX_WATCHES=256


def watch_directories():
    paths=set()
    for root in desktop.application_roots():
        parent=root
        while not parent.is_dir() and parent!=parent.parent:parent=parent.parent
        if parent.is_dir():paths.add(str(parent))
        if root.is_dir():
            for folder,dirs,_ in os.walk(root):
                dirs[:]=sorted(directory for directory in dirs if not directory.startswith('.'))
                paths.add(folder)
                if len(paths)>=MAX_WATCHES:break
        if len(paths)>=MAX_WATCHES:break
    return sorted(paths)[:MAX_WATCHES]


def launch_result(process,timeout=8):
    """Wait for gio's activation result, never for the application lifetime."""
    try:returncode=process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:process.wait(timeout=1)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=1)
        raise RuntimeError('Application activation timed out')
    if returncode:raise RuntimeError('The application could not start. Its launcher may be unavailable or invalid')
    return True


class AppCatalog(QObject):
    catalogChanged=Signal(object);notice=Signal(str);completed=Signal(object)
    def __init__(self,initial=None,parent=None,scanner=None):
        super().__init__(parent);self._closed=False;self._busy=False;self._again=False;self._last=0.;self._apps=list(initial or []);self.scanner=scanner or desktop.applications
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='orbit-apps');self.watcher=QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.schedule)
        self.watcher.fileChanged.connect(self.schedule)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(200);self.timer.timeout.connect(self.refresh)
        self.completed.connect(self.apply)
        self.update_watches(watch_directories())
    def update_watches(self,paths):
        # File watches catch in-place metadata edits; directory watches catch installs,
        # removals and atomic replacements. Limit native descriptors on small PCs.
        files=[app['path'] for app in self._apps if Path(app['path']).is_file()]
        wanted=set((paths+files)[:MAX_WATCHES]);old=set(self.watcher.files()+self.watcher.directories())
        if old-wanted:self.watcher.removePaths(list(old-wanted))
        if wanted-old:self.watcher.addPaths(list(wanted-old))
    @Slot()
    def schedule(self,*_):
        if not self._closed:self.timer.start()
    @Slot()
    def refresh(self):
        if self._closed:return
        if self._busy:self._again=True;return
        self.timer.stop();self._busy=True
        def work():return self.scanner(),watch_directories()
        future=self.pool.submit(work)
        def finished(result):
            if self._closed:return
            try:value=dict(value=result.result())
            except Exception as error:value=dict(error=str(error)[:180])
            if not self._closed:
                try:self.completed.emit(value)
                except RuntimeError:pass # QObject teardown can race a completed worker.
        future.add_done_callback(finished)
    @Slot()
    def refreshOnOpen(self):
        # Covers executable changes, inaccessible watch roots, and the descriptor cap.
        if time.monotonic()-self._last>2:self.refresh()
    @Slot(object)
    def apply(self,result):
        if self._closed:return
        self._busy=False;self._last=time.monotonic()
        if 'error' in result:self.notice.emit('Could not refresh applications: '+result['error'])
        else:
            apps,paths=result['value']
            if apps!=self._apps:self._apps=apps;self.catalogChanged.emit(apps)
            self.update_watches(paths)
        if self._again:self._again=False;self.timer.start()
    def close(self):
        if self._closed:return
        self._closed=True;self.timer.stop();self.watcher.directoryChanged.disconnect();self.watcher.fileChanged.disconnect()
        watched=self.watcher.files()+self.watcher.directories()
        if watched:self.watcher.removePaths(watched)
        self.pool.shutdown(wait=True,cancel_futures=True)
        dispose_native_io(self.watcher);dispose_native_io(self.timer)
