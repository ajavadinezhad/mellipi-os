"""Bounded local files, explicit handoffs and a durable note for Orbit Fold.

No thumbnails, directory watchers, automatic clipboard reads or content indexing.
Directory metadata and explicitly requested text reads use one lazy worker.
"""
import json
import os
import stat
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote, urlparse

from qt_compat import QObject, Property, Signal, Slot, QTimer, QUrl, QDesktopServices, QT5
if QT5:
    from PyQt5.QtCore import QMimeData
else:
    from PySide6.QtCore import QMimeData

ROOT = Path(__file__).resolve().parent
MAX_SCAN = 256
MAX_ITEMS = 80
MAX_IMPORTS = 20
MAX_TEXT_BYTES = 16384
MAX_NOTE_BYTES = 65536


def local_path(value):
    """Accept an explicit local path or URI, never a shell expression or remote URL."""
    value = value.toString() if isinstance(value, QUrl) else str(value)
    if not value or len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise ValueError('Choose a local folder or file')
    if value.startswith('file:'):
        parsed = urlparse(value)
        if parsed.scheme != 'file' or parsed.netloc not in ('', 'localhost') or parsed.query or parsed.fragment:
            raise ValueError('Only local files are supported')
        value = unquote(parsed.path)
    elif '://' in value:
        raise ValueError('Only local files are supported')
    if any(ord(c) < 32 for c in value):
        raise ValueError('Invalid local path')
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError('Use an absolute local path')
    return path


def item_for(path):
    """Metadata only; resolving a user-selected reference never reads its content."""
    path = path.resolve(strict=True)
    info = path.stat()
    directory = stat.S_ISDIR(info.st_mode)
    if not directory and not stat.S_ISREG(info.st_mode):
        raise ValueError('Only regular files and folders are supported')
    source = path.as_uri()
    return dict(id=source, name=path.name or str(path), kind='folder' if directory else 'file',
                source=source, body='', isDir=directory, size=0 if directory else info.st_size,
                modified=info.st_mtime)


def scan_folder(folder):
    folder = local_path(folder).resolve(strict=True)
    if not folder.is_dir():
        raise ValueError('Choose an existing folder')
    rows = []
    visited = 0
    with os.scandir(folder) as entries:
        for entry in entries:
            visited += 1
            if visited > MAX_SCAN:
                break
            if entry.name.startswith('.'):
                continue
            try:
                # Symlinks are visible references, but an automatic scan must not
                # follow them into remote mounts or unrelated directory trees.
                info = entry.stat(follow_symlinks=False)
                directory = stat.S_ISDIR(info.st_mode)
                if not directory and not stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode):
                    continue
                path = folder / entry.name
                source = path.as_uri()
                rows.append(dict(id=source, name=entry.name, kind='folder' if directory else 'file',
                                 source=source, body='', isDir=directory,
                                 size=0 if directory else info.st_size, modified=info.st_mtime))
            except OSError:
                continue
    rows.sort(key=lambda row:(not row['isDir'], row['name'].casefold()))
    return dict(folder=str(folder), items=rows[:MAX_ITEMS], limited=visited > MAX_SCAN or len(rows) > MAX_ITEMS)


def carry_item(record):
    path = local_path(record['source']).resolve(strict=True)
    item = item_for(path)
    if item['isDir']:
        return item
    # O_NONBLOCK prevents a changed file type from turning a bounded read into a
    # wait on a pipe/device. fstat checks the actual opened descriptor.
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('The selected item is no longer a regular file')
        if info.st_size > MAX_TEXT_BYTES:
            return item
        data = os.read(descriptor, MAX_TEXT_BYTES + 1)
        if len(data) > MAX_TEXT_BYTES or b'\0' in data:
            return item
        try:
            body = data.decode('utf-8')
        except UnicodeDecodeError:
            return item
        item.update(kind='text', body=body)
        return item
    finally:
        os.close(descriptor)


class FoldState(QObject):
    changed = Signal()
    itemsChanged = Signal()
    notice = Signal(str)
    received = Signal(object)

    def __init__(self, app, enabled=True, state_path=None, folder=None):
        super().__init__()
        self.app = app
        self.path = Path(state_path or os.environ.get('ORBIT_FOLD_STATE') or Path(os.environ.get('ORBIT_DATA', str(ROOT / 'data'))) / 'fold-state.json')
        self._enabled = bool(enabled)
        self._active = False
        self._scanned = False
        self._state = dict(carried={}, noteText='', selectedId='', busy=False, error='', view='work', folder='', limited=False)
        self._items = []
        self._imports = {}
        self._pool = None
        self._running = False
        self._pending_scan = None
        self._generation = 0
        self._carry_serial = 0
        self._closed = False
        self._dirty = False
        self.received.connect(self._apply)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(400)
        self.save_timer.timeout.connect(self.flush)
        self._load()
        chosen = folder or os.environ.get('ORBIT_FOLD_DIR')
        if not chosen and os.environ.get('ORBIT_NESTED'):
            chosen = self.path.parent / 'fold-files'
            try:
                Path(chosen).mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
        if not chosen:
            documents = Path.home() / 'Documents'
            chosen = documents if documents.is_dir() else Path.home()
        self._state['folder'] = str(local_path(chosen))

    state = Property('QVariantMap', lambda self:dict(self._state), notify=changed)
    items = Property('QVariantList', lambda self:[dict(row) for row in self._items], notify=itemsChanged)

    def _error(self, error):
        self._state['error'] = ' '.join(str(error).split())[:240]
        self.changed.emit()
        self.notice.emit(self._state['error'])

    def _load(self):
        try:
            if self.path.is_symlink() or self.path.stat().st_size > MAX_NOTE_BYTES * 6 + 1024:
                return
            data = json.loads(self.path.read_text(encoding='utf-8'))
            text = data.get('noteText', '') if isinstance(data, dict) else ''
            if isinstance(text, str) and len(text.encode('utf-8')) <= MAX_NOTE_BYTES:
                self._state['noteText'] = text
        except (OSError, ValueError, UnicodeError, RecursionError):
            pass

    def _start(self, kind, value, generation):
        if self._closed:
            return
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='orbit-fold')
        self._running = True
        self._state.update(busy=True, error='')
        self.changed.emit()
        carry_serial = self._carry_serial
        def work():
            try:
                if kind == 'scan': result = scan_folder(value)
                elif kind == 'carry': result = carry_item(value)
                else: result = [item_for(local_path(item)) for item in value]
                return dict(kind=kind, generation=generation, carrySerial=carry_serial, value=result)
            except Exception as error:
                return dict(kind=kind, generation=generation, error=str(error))
        def completed(future):
            if not future.cancelled() and not self._closed:
                self.received.emit(future.result())
        self._pool.submit(work).add_done_callback(completed)

    @Slot(object)
    def _apply(self, result):
        if self._closed:
            return
        self._running = False
        if result['generation'] == self._generation:
            if 'error' in result:
                self._error(result['error'])
            elif result['kind'] == 'scan':
                value = result['value']
                self._scanned = True
                if self._state['folder'] != value['folder']:
                    self._imports.clear()
                self._state.update(folder=value['folder'], limited=value['limited'])
                rows = {row['id']:row for row in value['items']}
                rows.update(self._imports)
                self._items = list(rows.values())[:MAX_ITEMS]
                self.itemsChanged.emit()
                if self._state['selectedId'] not in rows:
                    self._state['selectedId'] = ''
            elif result['kind'] == 'carry':
                if result['carrySerial'] == self._carry_serial:
                    self._state['carried'] = result['value']
            else:
                for row in result['value']:
                    if len(self._imports) >= MAX_IMPORTS and row['id'] not in self._imports:
                        break
                    self._imports[row['id']] = row
                rows = {row['id']:row for row in self._imports.values()}
                rows.update({row['id']:row for row in self._items if row['id'] not in rows})
                self._items = list(rows.values())[:MAX_ITEMS]
                self.itemsChanged.emit()
        if self._pending_scan is not None:
            folder, generation = self._pending_scan
            self._pending_scan = None
            self._start('scan', folder, generation)
        else:
            self._state['busy'] = False
            self.changed.emit()

    @Slot()
    def refresh(self):
        self.setFolder(self._state['folder'])

    @Slot(str)
    def setFolder(self, folder):
        if self._closed:
            return
        try:
            folder = str(local_path(folder))
        except ValueError as error:
            return self._error(error)
        self._generation += 1
        if self._running:
            self._pending_scan = (folder, self._generation)
        else:
            self._start('scan', folder, self._generation)

    @Slot()
    def parentFolder(self):
        self.setFolder(str(Path(self._state['folder']).parent))

    @Slot(str)
    def select(self, ident):
        if any(row['id'] == ident for row in self._items):
            self._state['selectedId'] = ident
            self.changed.emit()

    @Slot(str)
    def carry(self, ident):
        if self._closed or self._running:
            return
        record = next((row for row in self._items if row['id'] == ident), None)
        if record:
            self._carry_serial += 1
            self._start('carry', dict(record), self._generation)

    @Slot()
    def cancelCarry(self):
        self._carry_serial += 1
        self._state['carried'] = {}
        self.changed.emit()

    @Slot()
    def insertIntoNote(self):
        item = self._state['carried']
        if not item:
            return
        payload = item['body'] if item['kind'] == 'text' else item['name'] + '\n' + item['source']
        existing = self._state['noteText']
        text = existing + ('\n\n' if existing else '') + payload
        if len(text.encode('utf-8')) > MAX_NOTE_BYTES:
            return self._error('The note has reached its 64 KiB limit')
        self.setNoteText(text)
        self._state['carried'] = {}
        self.changed.emit()

    @Slot(str)
    def setNoteText(self, text):
        if self._closed or text == self._state['noteText']:
            return
        if len(text.encode('utf-8')) > MAX_NOTE_BYTES:
            return self._error('The note has reached its 64 KiB limit')
        self._state['noteText'] = text
        self._dirty = True
        self.save_timer.start()
        self.changed.emit()

    @Slot(str)
    def setView(self, view):
        if view not in ('work', 'unfold', 'apps'):return
        self.setActive(view=='work')
        if view != self._state['view']:
            self._state['view'] = view
            self.changed.emit()

    @Slot(bool)
    def setActive(self, active):
        self._active = bool(active)
        if self._active and self._enabled and not self._scanned and not self._running:
            self.refresh()
        elif not self._active:
            self.save_timer.stop()
            self.flush()

    @Slot(str)
    def openItem(self, ident):
        record = next((row for row in self._items if row['id'] == ident), None)
        if not record:
            return
        if record['isDir']:
            self.setFolder(record['source'])
            return
        try:
            path = local_path(record['source'])
        except ValueError as error:
            return self._error(error)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self._error('Could not open the selected file')

    @Slot()
    def copyCarry(self):
        item = self._state['carried']
        if not item:
            return
        mime = QMimeData()
        if item['kind'] == 'text':
            mime.setText(item['body'])
        else:
            mime.setUrls([QUrl(item['source'])])
            mime.setText(item['source'])
            mime.setData('x-special/gnome-copied-files', ('copy\n' + item['source']).encode('utf-8'))
        self.app.clipboard().setMimeData(mime)
        self.notice.emit('Copied ' + item['name'] + '; paste into the receiving app')

    @Slot('QVariantList')
    def importUrls(self, urls):
        if self._closed or self._running:
            return
        try:
            paths = [str(local_path(value)) for value in list(urls)[:MAX_IMPORTS]]
        except ValueError as error:
            return self._error(error)
        if paths:
            self._start('import', paths, self._generation)

    @Slot()
    def flush(self):
        if not self._dirty:
            return
        staged = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, staged = tempfile.mkstemp(prefix='.fold-note-', dir=self.path.parent)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(dict(version=1, noteText=self._state['noteText']), stream, ensure_ascii=False)
            os.replace(staged, self.path)
            staged = None
            self._dirty = False
        except OSError as error:
            self._error(error)
        finally:
            if staged is not None:
                try:os.unlink(staged)
                except OSError:pass

    @Slot()
    def close(self):
        if self._closed:
            return
        self.save_timer.stop()
        self.flush()
        self._closed = True
        if self._pool is not None:
            self._pool.shutdown(wait=True, cancel_futures=True)


# The public controller name keeps the native integration self-describing.
FoldController = FoldState
