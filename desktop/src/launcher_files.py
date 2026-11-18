"""Explicit, cancellable Launcher search of folders bookmarked in Files."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

from folder_search import find_nested_names
from qt_compat import QObject, Property, QDesktopServices, QSettings, QTimer, QUrl, Signal, Slot


class LauncherFiles(QObject):
    changed = Signal()
    completed = Signal(object)
    opened = Signal()

    def __init__(self, parent=None, settings=None, opener=None):
        super().__init__(parent)
        self.settings = settings if settings is not None else QSettings('Mellipi', 'Files')
        self.opener = opener or QDesktopServices.openUrl
        self._folders = []
        self._rows = []
        self._note = ''
        self._job = self._desired = self._pool = None
        self._scope = None
        self._closed = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._start)
        self.completed.connect(self._finish)

    folders = Property('QVariantList', lambda self: list(self._folders), notify=changed)
    rows = Property('QVariantList', lambda self: list(self._rows), notify=changed)
    note = Property(str, lambda self: self._note, notify=changed)

    @Slot()
    def refresh(self):
        self.settings.sync()
        bookmarks = self.settings.value('bookmarks', {})
        self._folders = []
        if isinstance(bookmarks, dict):
            for path, label in list(bookmarks.items())[:64]:
                if (isinstance(path, str) and len(path) <= 4096 and Path(path).is_absolute()
                        and isinstance(label, str) and label.strip()):
                    self._folders.append(dict(path=path, label=label.strip()[:128]))
        if self._desired and not any(row['path'] == str(self._desired[0]) for row in self._folders):
            self.cancel()
        else:
            self.changed.emit()

    @Slot()
    def cancel(self):
        self._timer.stop()
        if self._desired:
            self._desired[2].set()
        if self._job:
            self._job[2].set()
        self._desired = None
        self._scope = None
        self._rows = []
        self._note = ''
        self.changed.emit()

    @Slot(str, str)
    def search(self, path, query):
        if self._closed:
            return
        self.cancel()
        query = query.strip()
        if any(row['path'] == path for row in self._folders) and query and len(query) <= 256:
            self._desired = (Path(path), query, Event())
            self._note = 'Searching favorite folder…'
            self._timer.start()
        else:
            self._note = 'Enter a file name' if path else 'Choose a favorite folder'
        self.changed.emit()

    def _start(self):
        if self._closed or self._job or not self._desired:
            return
        self._job = request = self._desired
        folder, query, stop = request
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='launcher-files')

        def work():
            try:
                scope = folder.resolve(strict=True)
            except (OSError, RuntimeError):
                return [], 'This favorite folder is unavailable', None
            if not scope.is_dir():
                return [], 'This favorite folder is unavailable', None
            paths, limited, skipped = find_nested_names(scope, query, stop, limit=80, scan_limit=30000)
            rows = []
            for path in sorted(paths, key=lambda item: (item.name.casefold(), str(item))):
                if stop.is_set():
                    return [], '', None
                try:
                    if not path.resolve(strict=True).is_relative_to(scope):
                        continue
                except (OSError, RuntimeError):
                    continue
                rows.append(dict(kind='file',id=str(folder/path.relative_to(scope)),appId='',name=path.name,
                                 description=str(path.parent.relative_to(scope)),
                                 icon='document-open',category='Favorite folder'))
            note = 'Refine your search to see more' if limited else 'Some folders could not be searched' if skipped else ''
            return rows, note, scope

        def deliver(future):
            if self._closed:
                return
            try:
                result = future.result()
            except Exception:
                result = [], 'Could not search this favorite folder', None
            try:
                self.completed.emit((request, result))
            except RuntimeError:
                pass

        self._pool.submit(work).add_done_callback(deliver)

    def _finish(self, message):
        request, (rows, note, scope) = message
        self._job = None
        if self._closed:
            return
        if request is self._desired and not request[2].is_set():
            self._rows, self._note, self._scope = rows, note, scope
            self.changed.emit()
        elif not self._timer.isActive():
            self._start()

    @Slot(str)
    def open(self, path):
        if not self._desired or not self._scope or not any(row['id'] == path for row in self._rows):
            return
        self.refresh()
        if not self._desired or not self._scope or not any(row['id'] == path for row in self._rows):
            return
        folder = self._desired[0]
        try:
            # Recheck the original bookmark root and the result after the
            # asynchronous scan. A replaced directory or symlink cannot
            # redirect a staged path to a different favorite.
            resolved = Path(path).resolve(strict=True)
            if folder.resolve(strict=True) != self._scope or not resolved.is_relative_to(self._scope):
                raise ValueError('Result is outside the favorite folder')
        except (OSError, RuntimeError, ValueError):
            self._rows = [row for row in self._rows if row['id'] != path]
            self._note = 'This search result changed. Search again to find it.'
            self.changed.emit()
            return
        if self.opener(QUrl.fromLocalFile(str(resolved))):
            self.opened.emit()
        else:
            self._note = 'Could not open this item'
            self.changed.emit()

    def close(self):
        self._closed = True
        self.cancel()
        if self._pool:
            self._pool.shutdown(wait=False, cancel_futures=True)
