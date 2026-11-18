"""A lightweight PDF reader using Poppler in short-lived helper processes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import tempfile
import time
from contextlib import closing
from collections import OrderedDict

os.environ['ORBIT_QT'] = '6'
os.environ['QT_WAYLAND_SHELL_INTEGRATION'] = 'xdg-shell'
os.environ.pop('QT_WAYLAND_DISABLE_WINDOWDECORATION', None)

from PyQt6.QtCore import QProcess, QProcessEnvironment, QRegularExpression, Qt, QTimer, QRectF, QSize, pyqtSignal
from PyQt6.QtGui import QShortcut, QIcon, QImage, QKeySequence, QColor, QPainter, QPen
from PyQt6.QtPrintSupport import QPrinterInfo
from PyQt6.QtWidgets import (QApplication, QBoxLayout, QDialog, QDialogButtonBox, QHBoxLayout,
                             QLineEdit, QMenu, QPlainTextEdit, QPushButton, QSizePolicy, QVBoxLayout)

from file_chooser import FileChooser
from mellipi_photos import Canvas, PhotoSurface, action, local_file, status_label
from qt_app import exec_owned_dialog, style_dialog, ThemedInput, AppWindow, themed_choice
from installed_launcher import user_environment
from pdf_annotations import MAX_MARKS, MAX_NOTE, MAX_PDF_BYTES, MAX_REQUEST, parse_pages, revision

MAX_SEARCH_PAGES = 1000
PNG_LIMIT = 20 * 1024 * 1024
TEXT_LIMIT = 8 * 1024 * 1024
PAGE_CACHE_BYTES = 40 * 1024 * 1024
PAGE_CACHE_COUNT = 4
MAX_READING_POSITIONS = 100
MAX_BOOKMARKS_PER_PDF = 64
MAX_BOOKMARKS = 4096


class ReadingPositions:
    """Private, best-effort reading history with no filenames or PDF content."""
    def __init__(self):
        self.directory = Path(user_environment()['XDG_STATE_HOME']) / 'mellipi' / 'pdf'
        self.path = self.directory / 'positions.sqlite3'

    @staticmethod
    def key(path):
        info = path.stat()
        revision = f'{info.st_dev}:{info.st_ino}:{info.st_size}:{info.st_mtime_ns}'.encode('ascii')
        return hashlib.sha256(os.fsencode(path.resolve()) + b'\0' + revision).hexdigest()

    def connect(self):
        self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        info = self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise PermissionError('Reading-position directory is not private')
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        info = self.path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise PermissionError('Reading-position database is not private')
        return sqlite3.connect(self.path, timeout=0.05)

    def get(self, key, pages):
        try:
            with closing(self.connect()) as connection:
                row = connection.execute('SELECT page FROM positions WHERE document = ?', (key,)).fetchone()
                if row and isinstance(row[0], int) and 1 <= row[0] <= pages:
                    return row[0]
        except (OSError, sqlite3.Error):
            pass
        return 1

    def save(self, key, page):
        try:
            with closing(self.connect()) as connection, connection:
                connection.execute('CREATE TABLE IF NOT EXISTS positions '
                                   '(document TEXT PRIMARY KEY, page INTEGER NOT NULL, updated INTEGER NOT NULL)')
                connection.execute('INSERT OR REPLACE INTO positions VALUES (?, ?, ?)', (key, page, time.time_ns()))
                connection.execute('DELETE FROM positions WHERE document IN '
                                   '(SELECT document FROM positions ORDER BY updated DESC, document LIMIT -1 OFFSET ?)',
                                   (MAX_READING_POSITIONS,))
            return True
        except (OSError, sqlite3.Error):
            return False

    def bookmarks(self, key, pages):
        try:
            with closing(self.connect()) as connection:
                return tuple(row[0] for row in connection.execute(
                    'SELECT page FROM bookmarks WHERE document = ? AND page BETWEEN 1 AND ? ORDER BY page',
                    (key, pages)))
        except (OSError, sqlite3.Error):
            return ()

    def set_bookmark(self, key, page, enabled):
        try:
            with closing(self.connect()) as connection, connection:
                connection.execute('BEGIN IMMEDIATE')
                connection.execute('CREATE TABLE IF NOT EXISTS bookmarks '
                                   '(document TEXT NOT NULL, page INTEGER NOT NULL, PRIMARY KEY (document, page))')
                if not enabled:
                    connection.execute('DELETE FROM bookmarks WHERE document = ? AND page = ?', (key, page))
                elif not connection.execute('SELECT 1 FROM bookmarks WHERE document = ? AND page = ?', (key, page)).fetchone():
                    if (connection.execute('SELECT COUNT(*) FROM bookmarks WHERE document = ?', (key,)).fetchone()[0]
                            >= MAX_BOOKMARKS_PER_PDF or
                            connection.execute('SELECT COUNT(*) FROM bookmarks').fetchone()[0] >= MAX_BOOKMARKS):
                        return False
                    connection.execute('INSERT INTO bookmarks VALUES (?, ?)', (key, page))
            return True
        except (OSError, sqlite3.Error):
            return False


class Process:
    """Cancel stale work and cap helper output without blocking the Qt thread."""
    def __init__(self, owner):
        self.owner = owner
        self.process = None
        self.running = set()

    def cancel(self):
        old, self.process = self.process, None
        if old and old.state() != QProcess.ProcessState.NotRunning:
            old.kill()

    def close(self):
        self.cancel()
        for process in tuple(self.running):
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                process.waitForFinished(250)

    def run(self, executable, args, callback, *, maximum=16_384, timeout=20, payload=None):
        self.cancel()
        process = QProcess(self.owner)
        self.process = process
        self.running.add(process)
        timer = QTimer(process)
        timer.setSingleShot(True)
        output, errors = bytearray(), bytearray()
        completed = False

        def finish(error=''):
            nonlocal completed
            if completed:
                return
            completed = True
            timer.stop()
            active = self.process is process
            if active:
                self.process = None
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
            else:
                self.running.discard(process)
                process.deleteLater()
            if active:
                callback(bytes(output), error)

        def read_output():
            output.extend(bytes(process.readAllStandardOutput()))
            if len(output) > maximum:
                output.clear()
                finish('The PDF exceeds the reader’s output limit.')

        def read_error():
            errors.extend(bytes(process.readAllStandardError())[:max(0, 1024 - len(errors))])

        def exited(code, _status):
            if completed:
                self.running.discard(process)
                process.deleteLater()
                return
            if self.process is not process:
                finish()
                return
            read_output()
            read_error()
            if code:
                diagnostic = errors.decode('utf-8', 'replace').lower()
                if 'password' in diagnostic or 'encrypted' in diagnostic:
                    finish('This PDF requires a password.')
                else:
                    finish('The operation failed. The file may be damaged or unsupported.')
            else:
                finish()

        def process_error(error):
            if error == QProcess.ProcessError.FailedToStart:
                finish(f'{executable} is not installed.')

        timer.timeout.connect(lambda: finish('The operation timed out.'))
        process.readyReadStandardOutput.connect(read_output)
        process.readyReadStandardError.connect(read_error)
        process.finished.connect(exited)
        process.errorOccurred.connect(process_error)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert('LC_ALL', 'C')
        process.setProcessEnvironment(environment)
        if payload is not None:
            def send_input():
                process.write(payload)
                process.closeWriteChannel()
            process.started.connect(send_input)
        process.start(executable, args)
        timer.start(timeout * 1000)


class MarkupSurface(PhotoSurface):
    placed = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.tool = ''
        self.start = self.finish = None
        self.marks = []

    def set_tool(self, tool):
        self.tool = tool
        self.start = self.finish = None
        self.setCursor(Qt.CursorShape.CrossCursor if tool else Qt.CursorShape.ArrowCursor)
        self.update()

    def position(self, event, clamp=False):
        point = self.to_pixel(event.position(), clamp)
        if point is not None:
            return point.x() / self.image_size.width(), point.y() / self.image_size.height()
        return None

    def mousePressEvent(self, event):
        if not self.tool or event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        self.start = self.finish = self.position(event)
        if self.start is not None:
            event.accept()

    def mouseMoveEvent(self, event):
        if self.start is None:
            return super().mouseMoveEvent(event)
        self.finish = self.position(event, True)
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event):
        if self.start is None or event.button() != Qt.MouseButton.LeftButton:
            return super().mouseReleaseEvent(event)
        start, end, tool = self.start, self.position(event, True), self.tool
        self.start = self.finish = None
        self.update()
        if end is not None:
            if tool == 'note':
                self.placed.emit(start)
            elif abs(start[0]-end[0]) >= .002 and abs(start[1]-end[1]) >= .002:
                self.placed.emit(self.selection(start, end))
        event.accept()

    @staticmethod
    def selection(a, b):
        return min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])

    def paintEvent(self, event):
        super().paintEvent(event)
        picture = self.picture_rect()
        if picture.isEmpty():
            return
        painter = QPainter(self)
        painter.setClipRect(picture)

        def box(x1, y1, x2, y2):
            return QRectF(picture.x() + x1 * picture.width(), picture.y() + y1 * picture.height(),
                          (x2-x1) * picture.width(), (y2-y1) * picture.height())

        for kind, _, points, _ in self.marks:
            if kind == 'highlight':
                painter.fillRect(box(*points), QColor(255, 207, 0, 95))
            else:
                x, y = points
                marker = box(x, y, x, y)
                marker.setWidth(14)
                marker.setHeight(14)
                marker.moveLeft(min(marker.left(), picture.right() - marker.width()))
                marker.moveTop(min(marker.top(), picture.bottom() - marker.height()))
                painter.fillRect(marker, QColor('#ffd65b'))
                painter.setPen(QColor('#292419'))
                painter.drawRect(marker)
                painter.drawText(marker, Qt.AlignmentFlag.AlignCenter, '≡')
        if self.tool == 'highlight' and self.start and self.finish:
            selection = box(*self.selection(self.start, self.finish))
            painter.fillRect(selection, QColor(255, 207, 0, 62))
            painter.setPen(QPen(QColor('#a57b1b'), 1, Qt.PenStyle.DashLine))
            painter.drawRect(selection)
        painter.end()


class PdfWindow(AppWindow):
    extra_style = """
        QPushButton#pdfPageButton {
            background: %(surface)s; color: %(text)s;
            border-color: %(separator)s; font-weight: 600;
        }
        QPushButton#pdfPageButton:hover { background: %(hover)s; }
        QPushButton#pdfPageButton:focus { border-color: %(focus)s; }
        QPushButton#pdfPageButton:disabled { color: %(faint)s; }
    """

    def __init__(self, value=None):
        super().__init__('PDF Viewer')
        self.setWindowIcon(QIcon.fromTheme('mellipi-pdf', QIcon.fromTheme('application-pdf')))
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.resize(860, 680)
        self.setMinimumSize(430, 320)
        self.document = None
        self.snapshot_file = None
        self.snapshot_path = None
        self.source_revision = None
        self.page = 1
        self.count = 0
        self.matches = []
        self.match_index = -1
        self.positions = ReadingPositions()
        self.position_key = None
        self.bookmarked_pages = ()
        self.pending_position = None
        self.position_timer = QTimer(self)
        self.position_timer.setSingleShot(True)
        self.position_timer.setInterval(500)
        self.position_timer.timeout.connect(self.save_position)
        self.inspector, self.renderer, self.finder, self.printer, self.annotation_reader, self.exporter = (
            Process(self) for _ in range(6))
        self.snapshotter = Process(self)
        self.prefetcher, self.text_reader = Process(self), Process(self)
        self.page_cache = OrderedDict()
        self.cache_revision = None
        self.prefetch_timer = QTimer(self, interval=220, singleShot=True)
        self.prefetch_timer.timeout.connect(self.prefetch_page)
        self.marks = []
        self.annotation_mode = ''
        self.annotation_revision = None
        self.annotation_dirty = False
        self.exporting = False
        self.setAcceptDrops(True)
        self.toolbar = QBoxLayout(QBoxLayout.Direction.TopToBottom)
        self.navigation = QHBoxLayout()
        self.tools = QHBoxLayout()
        self.toolbar.setSpacing(8)
        self.navigation.setSpacing(4)
        self.tools.setSpacing(4)
        self.toolbar.addLayout(self.navigation)
        self.toolbar.addLayout(self.tools)
        self.open_button = action('Open PDF', 'document-open-symbolic', self.choose_file, self, QKeySequence.StandardKey.Open)
        self.navigation.addWidget(self.open_button)
        self.open_button.hide()
        self.previous = action('Previous page', 'go-previous-symbolic', lambda: self.go(self.page - 1), self, Qt.Key.Key_PageUp)
        self.next = action('Next page', 'go-next-symbolic', lambda: self.go(self.page + 1), self, Qt.Key.Key_PageDown)
        self.navigation.addWidget(self.previous)
        self.page_button = action('Go to page', 'go-jump-symbolic', self.choose_page, self, 'Ctrl+L', caption='Page — / —')
        self.page_button.setObjectName('pdfPageButton')
        self.page_button.setIcon(QIcon())
        self.page_button.setProperty('mellipiSymbolicIcon', None)
        self.navigation.addWidget(self.page_button)
        self.navigation.addWidget(self.next)
        self.navigation.setAlignment(Qt.AlignmentFlag.AlignLeading)
        self.zoom_out = action('Zoom out', 'zoom-out-symbolic', lambda: self.canvas.zoom_by(.8), self, QKeySequence.StandardKey.ZoomOut)
        self.zoom_in = action('Zoom in', 'zoom-in-symbolic', lambda: self.canvas.zoom_by(1.25), self, QKeySequence.StandardKey.ZoomIn)
        self.fit = action('Fit page', 'zoom-fit-best-symbolic', lambda: self.canvas.set_zoom(None), self, 'Ctrl+0')
        self.search = action('Find in PDF', 'edit-find-symbolic', self.show_search, self, QKeySequence.StandardKey.Find)
        self.bookmark_button = action('Bookmarks', 'bookmark', lambda: None, self)
        self.bookmark_menu = QMenu(self.bookmark_button)
        self.bookmark_menu.aboutToShow.connect(self.show_bookmarks)
        self.bookmark_button.setMenu(self.bookmark_menu)
        self.bookmark_shortcut = QShortcut(QKeySequence('Ctrl+B'), self)
        self.bookmark_shortcut.activated.connect(self.toggle_bookmark)
        self.markup = action('PDF markup', 'document-edit-symbolic', lambda: None, self)
        self.markup_menu = QMenu(self.markup)
        self.highlight_mark = self.markup_menu.addAction('Highlight area')
        self.highlight_mark.triggered.connect(lambda: self.set_annotation_mode('highlight'))
        self.note_mark = self.markup_menu.addAction('Add note')
        self.note_mark.triggered.connect(lambda: self.set_annotation_mode('note'))
        self.read_notes = self.markup_menu.addAction('Read notes on this page…', self.show_annotations)
        self.markup_menu.addSeparator()
        self.undo_mark = self.markup_menu.addAction('Undo last mark', self.undo_annotation)
        self.save_marks = self.markup_menu.addAction('Save annotated copy…', self.save_annotated_copy)
        self.cancel_mark = self.markup_menu.addAction('Exit markup mode', lambda: self.set_annotation_mode(''))
        self.markup.setMenu(self.markup_menu)
        self.markup.setCheckable(True)
        self.zoom_controls = (self.zoom_out, self.zoom_in, self.fit)
        self.print_button = action('Print PDF', 'document-print-symbolic', self.print_pdf, self)
        self.more = action('More PDF actions', 'open-menu', lambda: None, self)
        more_menu = QMenu(self.more)
        self.overflow_zoom = [more_menu.addAction(caption, widget.click)
                              for caption, widget in zip(('Zoom out', 'Zoom in', 'Fit page'), self.zoom_controls)]
        self.overflow_separator = more_menu.addSeparator()
        self.print_action = more_menu.addAction('Print PDF…', self.print_pdf)
        self.page_text_action = more_menu.addAction('Read or copy page text…', self.show_page_text)
        self.extract_action = more_menu.addAction('Save selected pages…', self.extract_pages)
        self.page_text_shortcut = QShortcut(QKeySequence('Ctrl+Shift+T'), self)
        self.page_text_shortcut.activated.connect(self.show_page_text)
        self.print_shortcut = QShortcut(QKeySequence.StandardKey.Print, self)
        self.print_shortcut.activated.connect(self.print_pdf)
        self.more.setMenu(more_menu)
        for button in (*self.zoom_controls, self.search, self.bookmark_button, self.markup,
                       self.print_button, self.more):
            self.tools.addWidget(button)
        self.tools.setAlignment(Qt.AlignmentFlag.AlignTrailing)
        self.content.addLayout(self.toolbar)
        self.themeChanged.connect(lambda: QTimer.singleShot(0, self.update_toolbar_layout))

        find = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText('Find text')
        self.query.setAccessibleName('Find text in PDF')
        self.query.setMaxLength(120)
        self.query.returnPressed.connect(self.find_text)
        self.query.textChanged.connect(self.clear_matches)
        find.addWidget(self.query, 1)
        self.find_previous = action('Previous matching page', 'go-up-symbolic', lambda: self.advance_match(-1), self)
        self.find_next = action('Next matching page', 'go-down-symbolic', lambda: self.advance_match(1), self)
        self.find_close = action('Close search', 'window-close-symbolic', self.hide_search, self)
        self.find_bar = [self.query, self.find_previous, self.find_next, self.find_close]
        for button in self.find_bar[1:]:
            find.addWidget(button)
        self.content.addLayout(find)

        self.canvas = Canvas('Open a PDF or drop one here.')
        self.canvas.setAccessibleName('PDF page')
        self.canvas.label = MarkupSurface()
        self.canvas.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.canvas.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.canvas.label.setTextFormat(Qt.TextFormat.PlainText)
        self.canvas.label.setWordWrap(True)
        self.canvas.setWidget(self.canvas.label)
        self.canvas.show_message('Open a PDF or drop one here.')
        self.canvas.label.placed.connect(self.place_annotation)
        self.status = status_label()
        self.status.setAccessibleName('PDF status')
        self.start_stage = self.empty_stage('PDF Viewer', 'Drop a PDF here to read it.', 'Open PDF…', self.choose_file)
        self.content.addWidget(self.start_stage, 1)
        self.canvas.hide()
        self.content.addWidget(self.canvas, 1)
        self.content.addWidget(self.status)
        self.escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.escape.activated.connect(lambda: self.set_annotation_mode('') if self.annotation_mode else self.hide_search())
        self.first_page = QShortcut(QKeySequence('Ctrl+Home'), self)
        self.first_page.activated.connect(lambda: self.go(1))
        self.last_page = QShortcut(QKeySequence('Ctrl+End'), self)
        self.last_page.activated.connect(lambda: self.go(self.count))
        self.hide_search()
        self.update_buttons()
        self.update_toolbar_layout()
        if value:
            self.open_path(value)

    def update_toolbar_layout(self):
        icon_size = max(16, min(24, round(16 * self.theme['text_scale'])))
        for button in self.findChildren(QPushButton, 'photoAction'):
            button.setIconSize(QSize(icon_size, icon_size))
        _, section, control = self.layout_spacing()
        self.toolbar.setSpacing(section)
        for group in (self.navigation, self.tools):
            group.setSpacing(control)
        navigation_width = self.navigation.sizeHint().width()
        common = (self.search, self.bookmark_button, self.markup)

        def combined_width(buttons):
            return (navigation_width + self.toolbar.spacing() + sum(b.sizeHint().width() for b in buttons)
                    + (len(buttons) - 1) * control)

        available = self.viewport_width()
        compact = available < combined_width((*self.zoom_controls, *common, self.print_button, self.more))
        for widget in (*self.zoom_controls, self.print_button):
            widget.setVisible(not compact)
        for action in (*self.overflow_zoom, self.overflow_separator, self.print_action):
            action.setVisible(compact)
        horizontal = not compact or available >= combined_width((*common, self.more))
        direction = QBoxLayout.Direction.LeftToRight if horizontal else QBoxLayout.Direction.TopToBottom
        if self.toolbar.direction() != direction:
            self.toolbar.setDirection(direction)
        self.tools.setAlignment(Qt.AlignmentFlag.AlignTrailing if horizontal else Qt.AlignmentFlag.AlignLeading)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'toolbar'):
            self.update_toolbar_layout()

    def choose_file(self):
        value, _ = FileChooser.getOpenFileName(self, 'Open PDF', '', 'PDF documents (*.pdf);;All files (*)')
        if value:
            self.open_path(value)

    def open_path(self, value):
        try:
            path = local_file(value)
            if path.stat().st_size > MAX_PDF_BYTES:
                raise ValueError('This PDF is too large to open.')
        except (OSError, ValueError) as error:
            self.status.setText(str(error))
            return False
        if not self.can_leave_document(lambda: self.open_path(value)):
            return False
        try:
            source_revision = revision(path)
            source_path = path.resolve(strict=True)
            snapshot_file = tempfile.TemporaryFile(prefix='mellipi-pdf-reader-')
        except (OSError, ValueError) as error:
            self.status.setText(str(error))
            return False
        try:
            key = self.positions.key(path)
        except (OSError, RuntimeError):
            key = None
        self.start_stage.hide()
        self.open_button.show()
        self.canvas.show()
        self.save_position()
        self.annotation_reader.cancel()
        self.marks.clear()
        self.annotation_dirty = False
        self.annotation_revision = None
        self.set_annotation_mode('')
        self.refresh_marks()
        self.setWindowTitle('PDF Viewer')
        self.title.setText('PDF Viewer')
        self.title.setToolTip('')
        for process in (self.snapshotter, self.inspector, self.renderer, self.prefetcher,
                        self.text_reader, self.finder, self.printer):
            process.cancel()
        self.clear_snapshot()
        self.snapshot_file = snapshot_file
        descriptor = snapshot_file.fileno()
        self.snapshot_path = pinned = Path('/proc') / str(os.getpid()) / 'fd' / str(descriptor)
        info = os.fstat(descriptor)
        self.source_revision = source_revision
        self.prefetch_timer.stop()
        self.page_cache.clear()
        self.cache_revision = None
        self.clear_matches()
        self.document = None
        self.position_key = None
        self.bookmarked_pages = ()
        self.count = 0
        self.update_buttons()
        self.canvas.show_message('Opening PDF…')
        self.status.setText('Opening PDF…')

        def failed(message):
            self.canvas.show_message(message)
            self.status.setText(message)
            self.clear_snapshot()

        def ready(output, error):
            match = re.search(rb'^Pages:\s+([0-9]{1,8})\s*$', output, re.MULTILINE)
            if error or not match or not int(match[1]):
                message = error or 'This file does not appear to be a readable PDF.'
                failed(message)
                return
            self.document, self.count = path, int(match[1])
            self.position_key = key
            self.bookmarked_pages = self.positions.bookmarks(key, self.count) if key else ()
            try:
                self.annotation_revision = self.cache_revision = revision(pinned)
            except OSError:
                self.document = None
                self.count = 0
                self.update_buttons()
                failed('Could not read the private PDF copy.')
                return
            self.canvas.zoom = None
            self.setWindowTitle(f'{path.name} — PDF Viewer')
            self.title.setText(path.name)
            self.title.setToolTip(str(path))
            page = self.positions.get(key, self.count) if key else 1
            self.go(page, resumed=page > 1)

        def copied(output, error):
            try:
                result = json.loads(output) if not error else {}
            except (ValueError, UnicodeError):
                result = {}
            if not result.get('result'):
                failed(error or result.get('error') or 'Could not copy the PDF for reading.')
                return
            self.inspector.run('pdfinfo', [str(pinned)], ready)

        helper = Path(__file__).with_name('pdf_annotations.py')
        self.snapshotter.run(sys.executable, [str(helper), 'snapshot', str(source_path), str(pinned)],
                             copied, payload=json.dumps({'revision': source_revision,
                                                         'destination': [info.st_dev, info.st_ino]}).encode('utf-8'))
        return True

    def clear_snapshot(self):
        self.snapshot_path = None
        self.source_revision = None
        snapshot_file, self.snapshot_file = self.snapshot_file, None
        if snapshot_file is not None:
            snapshot_file.close()

    def reader_path(self):
        return self.snapshot_path or self.document

    def source_notice(self):
        if self.snapshot_path and self.document:
            try:
                if revision(self.document) == self.source_revision:
                    return ''
            except OSError:
                pass
            return ' · Original changed; viewing the opened copy'
        return ''

    def render_args(self, page):
        return ['-f', str(page), '-l', str(page), '-singlefile', '-scale-to', '2200',
                '-cropbox', '-png', str(self.reader_path())]

    def remember_page(self, page, image):
        if not self.cache_revision or image.sizeInBytes() > PAGE_CACHE_BYTES:
            return
        self.page_cache[page] = image
        self.page_cache.move_to_end(page)
        while len(self.page_cache) > PAGE_CACHE_COUNT or sum(
                image.sizeInBytes() for image in self.page_cache.values()) > PAGE_CACHE_BYTES:
            self.page_cache.popitem(last=False)

    def current_cache_revision(self):
        try:
            value = revision(self.reader_path())
        except OSError:
            value = None
        if self.cache_revision != value:
            self.cache_revision = value
            self.page_cache.clear()
        return value

    def prefetch_page(self):
        if not self.document or not self.current_cache_revision():
            return
        page = next((page for page in (self.page + 1, self.page - 1)
                     if 1 <= page <= self.count and page not in self.page_cache), None)
        if page is not None:
            before = self.cache_revision

            def ready(output, error):
                if error or before != self.current_cache_revision():
                    return
                image = QImage.fromData(output, 'PNG')
                if not image.isNull():
                    self.remember_page(page, image)

            self.prefetcher.run('pdftoppm', self.render_args(page), ready, maximum=PNG_LIMIT)

    def go(self, page, *, resumed=False):
        if not self.document or not 1 <= page <= self.count:
            return
        self.annotation_reader.cancel()
        self.renderer.cancel()
        self.prefetcher.cancel()
        self.prefetch_timer.stop()
        before = self.current_cache_revision()
        self.page = page
        self.canvas.label.set_tool(self.annotation_mode)
        self.refresh_marks()
        self.update_buttons()
        self.status.setText(f'Page {page} of {self.count}' + self.source_notice())

        key = self.position_key
        def display(image):
            self.canvas.set_image(image)
            if resumed:
                self.status.setText(f'Resumed at page {page} of {self.count}' + self.source_notice())
            if key:
                self.pending_position = (key, page)
                self.position_timer.start()
            self.prefetch_timer.start()

        if page in self.page_cache:
            self.page_cache.move_to_end(page)
            display(self.page_cache[page])
            return

        self.canvas.show_message('Loading page…')

        def ready(output, error):
            image = QImage.fromData(output, 'PNG') if not error else QImage()
            if image.isNull():
                message = error or 'This page could not be rendered.'
                self.canvas.show_message(message)
                self.status.setText(message)
                return
            if before == self.current_cache_revision():
                self.remember_page(page, image)
            display(image)

        self.renderer.run('pdftoppm', self.render_args(page), ready, maximum=PNG_LIMIT)

    def show_page_text(self):
        if not self.document:
            return
        page = self.page
        dialog = style_dialog(QDialog(self), self)
        dialog.setWindowTitle(f'Page {page} text')
        dialog.resize(620, 500)
        layout = QVBoxLayout(dialog)
        viewer = QPlainTextEdit()
        viewer.setReadOnly(True)
        viewer.setAccessibleName(f'Selectable text on PDF page {page}')
        viewer.setPlaceholderText('Reading text…')
        layout.addWidget(viewer)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        controls.rejected.connect(dialog.reject)
        layout.addWidget(controls)
        query = self.query.text().strip()

        def ready(output, error):
            value = output.decode('utf-8', 'replace').strip()
            viewer.setPlainText(value)
            viewer.setPlaceholderText(error or 'This page has no selectable text.')
            if query and not error:
                pattern = r'\s+'.join(QRegularExpression.escape(word) for word in query.split())
                matches = QRegularExpression(pattern, QRegularExpression.PatternOption.CaseInsensitiveOption)
                viewer.find(matches)

        self.text_reader.run('pdftotext', ['-f', str(page), '-l', str(page), '-enc', 'UTF-8',
                                           str(self.reader_path()), '-'], ready, maximum=TEXT_LIMIT)
        try:
            exec_owned_dialog(dialog)
        finally:
            self.text_reader.cancel()
            dialog.deleteLater()

    def can_leave_document(self, after_save):
        if self.exporting:
            self.status.setText('Wait for the annotated copy to finish saving.')
            return False
        if not self.annotation_dirty:
            return True
        choice = themed_choice(
            self, 'Unsaved PDF markup', 'Save your markup to a new PDF before leaving?',
            'Save Copy…', 'Keep Editing', 'Discard')
        if choice == QDialog.DialogCode.Accepted:
            self.save_annotated_copy(after_save=after_save)
        return choice == 2

    def refresh_marks(self):
        self.canvas.label.marks = [mark for mark in self.marks if mark[1] == self.page]
        self.canvas.label.update()
        self.update_annotation_actions()

    def update_annotation_actions(self):
        enabled = bool(self.count and self.annotation_revision and not self.exporting)
        self.markup.setEnabled(enabled)
        self.markup.setChecked(bool(self.annotation_mode))
        self.highlight_mark.setEnabled(enabled and len(self.marks) < MAX_MARKS)
        self.note_mark.setEnabled(enabled and len(self.marks) < MAX_MARKS)
        self.undo_mark.setEnabled(enabled and bool(self.marks))
        self.save_marks.setEnabled(enabled and bool(self.marks))
        self.cancel_mark.setEnabled(bool(self.annotation_mode))

    def set_annotation_mode(self, mode):
        self.annotation_mode = mode
        self.canvas.label.set_tool(mode)
        self.update_annotation_actions()
        if mode:
            self.status.setText('Drag over the area to highlight.' if mode == 'highlight'
                                else 'Click the page where you want to add a note.')

    def place_annotation(self, points):
        tool = self.annotation_mode
        if not tool or self.canvas.image.isNull() or self.exporting or len(self.marks) >= MAX_MARKS:
            return
        contents = ''
        if tool == 'note':
            value, ok = ThemedInput.getMultiLineText(self, 'Add note', 'Note')
            if not ok or not value.strip():
                return
            contents = value.strip().replace(chr(0), '')
            if len(contents) > MAX_NOTE:
                self.status.setText(f'Notes can contain up to {MAX_NOTE} characters.')
                return
        self.marks.append((tool, self.page, points, contents))
        self.annotation_dirty = True
        self.set_annotation_mode('')
        self.refresh_marks()
        self.status.setText(f'Markup added on page {self.page}. Save an annotated copy to keep it.')

    def undo_annotation(self):
        if self.marks and not self.exporting:
            self.marks.pop()
            self.annotation_dirty = bool(self.marks)
            self.refresh_marks()
            self.status.setText('Last mark removed.')

    def annotation_request(self, worker, operation, request, callback, destination=None):
        args = [str(Path(__file__).with_name('pdf_annotations.py')), operation, str(self.reader_path())]
        if destination:
            args.append(str(destination))
        payload = json.dumps(request, ensure_ascii=False).encode('utf-8')
        if len(payload) > MAX_REQUEST:
            callback(None, 'This document has too much markup to export in one copy.')
            return

        def ready(output, error):
            if error:
                callback(None, error)
                return
            try:
                result = json.loads(output)
            except (ValueError, UnicodeError):
                callback(None, 'No response from the PDF annotation helper.')
                return
            callback(result.get('result'), result.get('error', ''))

        worker.run(sys.executable, args, ready, maximum=MAX_REQUEST, timeout=90, payload=payload)

    def show_annotations(self):
        if not self.document:
            return
        page = self.page

        def ready(result, error):
            if error:
                self.status.setText(error)
                return
            pending = [text for _, number, _, text in self.marks if number == page and text]
            notes = (result or []) + pending
            if not notes:
                self.status.setText(f'No notes on page {page}.')
                return
            dialog = style_dialog(QDialog(self), self)
            dialog.setWindowTitle(f'Notes on page {page}')
            dialog.resize(420, 280)
            layout = QVBoxLayout(dialog)
            content = QPlainTextEdit(dialog)
            content.setAccessibleName(f'Notes on page {page}')
            content.setReadOnly(True)
            content.setPlainText('\n\n'.join(f'{i}. {note}' for i, note in enumerate(notes, 1)))
            layout.addWidget(content)
            close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=dialog)
            close.rejected.connect(dialog.reject)
            layout.addWidget(close)
            content.setFocus()
            try:
                exec_owned_dialog(dialog)
            finally:
                dialog.deleteLater()

        self.annotation_request(self.annotation_reader, 'notes', {'page': page}, ready)

    def save_annotated_copy(self, *, after_save=None):
        if not self.document or not self.marks or self.exporting:
            return
        proposed = self.document.with_name(self.document.stem + ' — annotated.pdf')
        value, _ = FileChooser.getSaveFileName(self, 'Save annotated copy', str(proposed),
                                               'PDF documents (*.pdf)',
                                               options=FileChooser.Option.DontConfirmOverwrite)
        if not value:
            return
        path = Path(value)
        if path.suffix.lower() != '.pdf':
            path = path.with_name(path.name + '.pdf')
        if path.resolve() == self.document.resolve():
            self.status.setText('Choose a new filename for the annotated copy.')
            return
        self.exporting = True
        self.set_annotation_mode('')
        self.status.setText('Saving annotated copy…')

        def ready(result, error):
            self.exporting = False
            saved = bool(result) and not error
            if saved:
                self.annotation_dirty = False
            self.update_annotation_actions()
            self.status.setText(f'Annotated copy saved to {path}' if saved else error or 'Could not save annotated copy.')
            if saved and after_save is not None:
                QTimer.singleShot(0, after_save)

        self.annotation_request(self.exporter, 'save', {'revision': self.annotation_revision, 'marks': self.marks},
                                ready, path)

    def save_position(self):
        self.position_timer.stop()
        if self.pending_position and self.positions.save(*self.pending_position):
            self.pending_position = None

    def toggle_bookmark(self):
        if not self.document or not self.position_key or not 1 <= self.page <= self.count:
            return
        pages = self.positions.bookmarks(self.position_key, self.count)
        enabled = self.page not in pages
        if not self.positions.set_bookmark(self.position_key, self.page, enabled):
            self.status.setText('Could not save bookmark change. The bookmark limit or a storage error may be preventing it.')
            return
        self.bookmarked_pages = self.positions.bookmarks(self.position_key, self.count)
        self.status.setText(f'Bookmark added for page {self.page}.' if enabled else f'Bookmark removed from page {self.page}.')

    def show_bookmarks(self):
        self.bookmark_menu.clear()
        if self.position_key:
            self.bookmarked_pages = self.positions.bookmarks(self.position_key, self.count)
        label = 'Remove bookmark' if self.page in self.bookmarked_pages else 'Bookmark this page'
        self.bookmark_menu.addAction(label, self.toggle_bookmark)
        self.bookmark_menu.addSeparator()
        if not self.bookmarked_pages:
            self.bookmark_menu.addAction('No bookmarked pages').setEnabled(False)
        for page in self.bookmarked_pages:
            item = self.bookmark_menu.addAction(f'Page {page}', lambda _checked=False, page=page: self.go(page))
            item.setEnabled(page != self.page)

    def choose_page(self):
        value, ok = ThemedInput.getInt(self, 'Go to page', 'Page', self.page, 1, self.count)
        if ok:
            self.go(value)

    def show_search(self):
        for widget in self.find_bar:
            widget.show()
        self.query.setFocus()
        self.query.selectAll()

    def hide_search(self):
        for widget in self.find_bar:
            widget.hide()

    def clear_matches(self):
        self.finder.cancel()
        self.matches = []
        self.match_index = -1
        self.find_previous.setEnabled(False)
        self.find_next.setEnabled(False)

    def find_text(self):
        query = ' '.join(self.query.text().casefold().split())
        if not self.document or not query:
            return
        if self.matches:
            self.advance_match(1)
            return
        self.status.setText('Searching PDF…')

        def ready(output, error):
            if error:
                self.status.setText(error)
                return
            self.matches = [
                number for number, page in enumerate(output.decode('utf-8', 'replace').split('\f'), 1)
                if query in ' '.join(page.casefold().split())
            ]
            if not self.matches:
                self.status.setText('No matching text.' if self.count <= MAX_SEARCH_PAGES else
                                    f'No matches in the first {MAX_SEARCH_PAGES} pages.')
                return
            for widget in (self.find_previous, self.find_next):
                widget.setEnabled(len(self.matches) > 1)
            self.advance_match(1)

        self.finder.run('pdftotext', ['-f', '1', '-l', str(min(self.count, MAX_SEARCH_PAGES)),
                                      '-enc', 'UTF-8', str(self.reader_path()), '-'],
                        ready, maximum=TEXT_LIMIT)

    def advance_match(self, step):
        if self.matches:
            if self.match_index < 0:
                self.match_index = next((i for i, page in enumerate(self.matches) if page >= self.page), 0)
            else:
                self.match_index = (self.match_index + step) % len(self.matches)
            self.go(self.matches[self.match_index])
            self.status.setText(f'Page {self.page}  ·  Match {self.match_index + 1} of {len(self.matches)}')
            if self.count > MAX_SEARCH_PAGES:
                self.status.setText(self.status.text() + f' (first {MAX_SEARCH_PAGES} pages)')

    def print_pdf(self):
        printers = QPrinterInfo.availablePrinterNames()
        if not printers:
            self.status.setText('No printer is configured.')
            return
        printer, ok = ThemedInput.getItem(self, 'Print PDF', 'Printer', printers, 0, False)
        if ok and self.document:
            self.printer.run('lp', ['-d', printer, '-t', self.document.name, '--', str(self.reader_path())],
                             lambda _output, error: self.status.setText(error or 'PDF sent to printer.'))

    def extract_pages(self):
        if not self.document or self.exporting:
            return
        value, ok = ThemedInput.getText(self, 'Save selected pages', 'Pages, e.g. 1–3, 6', text=str(self.page))
        if not ok:
            return
        try:
            pages = parse_pages(value, self.count)
        except ValueError as error:
            self.status.setText(str(error))
            return
        proposed = self.document.with_name(self.document.stem + ' — pages.pdf')
        value, _ = FileChooser.getSaveFileName(self, 'Save selected pages', str(proposed), 'PDF documents (*.pdf)',
                                               options=FileChooser.Option.DontConfirmOverwrite)
        if not value:
            return
        path = Path(value)
        if path.suffix.lower() != '.pdf':
            path = path.with_name(path.name + '.pdf')
        self.exporting = True
        self.extract_action.setEnabled(False)
        self.set_annotation_mode('')
        self.update_annotation_actions()
        self.status.setText('Saving selected pages…')

        def ready(result, error):
            self.exporting = False
            self.extract_action.setEnabled(True)
            self.update_annotation_actions()
            self.status.setText(f'Saved {len(pages)} selected pages to {path.name}.' if result and not error
                                else error or 'Could not save selected pages.')
        selected = set(pages)
        self.annotation_request(self.exporter, 'extract',
                                {'revision': self.annotation_revision, 'pages': pages,
                                 'marks': [mark for mark in self.marks if mark[1] in selected]}, ready, path)

    def update_buttons(self):
        self.extract_action.setEnabled(bool(self.count) and not self.exporting)
        self.page_button.setText(f'Page {self.page} / {self.count}' if self.count else 'Page — / —')
        self.page_button.setAccessibleName(f'Page {self.page} of {self.count} — Go to page' if self.count else 'Go to page')
        self.update_toolbar_layout()
        self.previous.setEnabled(self.page > 1 and bool(self.count))
        self.next.setEnabled(self.page < self.count)
        self.bookmark_button.setEnabled(bool(self.count and self.position_key))
        self.bookmark_shortcut.setEnabled(self.bookmark_button.isEnabled())
        for button in (self.page_button, *self.zoom_controls, self.search, self.more, self.print_button, self.print_action,
                       self.print_shortcut, self.page_text_action, self.page_text_shortcut):
            button.setEnabled(bool(self.count))
        self.update_annotation_actions()

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and self.open_path(urls[0].toString()):
            event.acceptProposedAction()

    def closeEvent(self, event):
        if not self.can_leave_document(self.close):
            event.ignore()
            return
        self.save_position()
        self.prefetch_timer.stop()
        for process in (self.snapshotter, self.inspector, self.renderer, self.finder, self.printer, self.annotation_reader, self.exporter,
                        self.prefetcher, self.text_reader):
            process.close()
        self.clear_snapshot()
        super().closeEvent(event)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', nargs='?')
    args = parser.parse_args()
    app = QApplication([sys.argv[0]])
    app.setApplicationName('Mellipi PDF Viewer')
    app.setDesktopFileName('mellipi-pdf')
    window = PdfWindow(args.path)
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
