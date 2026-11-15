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
import time
from contextlib import closing

os.environ['ORBIT_QT'] = '6'
os.environ['QT_WAYLAND_SHELL_INTEGRATION'] = 'xdg-shell'
os.environ.pop('QT_WAYLAND_DISABLE_WINDOWDECORATION', None)

from PyQt6.QtCore import QProcess, QProcessEnvironment, Qt, QTimer, QRectF, pyqtSignal
from PyQt6.QtGui import QShortcut, QIcon, QImage, QKeySequence, QColor, QPainter, QPen
from PyQt6.QtPrintSupport import QPrinterInfo
from PyQt6.QtWidgets import (QApplication, QBoxLayout, QDialog, QDialogButtonBox, QHBoxLayout,
                             QLineEdit, QMenu, QPlainTextEdit, QSizePolicy, QVBoxLayout)

from file_chooser import FileChooser
from mellipi_photos import Canvas, PhotoSurface, action, local_file, status_label
from qt_app import style_dialog, ThemedInput, AppWindow, themed_prompt
from installed_launcher import user_environment
from pdf_annotations import MAX_MARKS, MAX_NOTE, MAX_REQUEST, revision

MAX_PDF_BYTES = 256 * 1024 * 1024
MAX_SEARCH_PAGES = 1000
PNG_LIMIT = 20 * 1024 * 1024
TEXT_LIMIT = 8 * 1024 * 1024
MAX_READING_POSITIONS = 100


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
        self.page = 1
        self.count = 0
        self.matches = []
        self.match_index = -1
        self.positions = ReadingPositions()
        self.position_key = None
        self.pending_position = None
        self.position_timer = QTimer(self)
        self.position_timer.setSingleShot(True)
        self.position_timer.setInterval(500)
        self.position_timer.timeout.connect(self.save_position)
        self.inspector, self.renderer, self.finder, self.printer, self.annotation_reader, self.exporter = (
            Process(self) for _ in range(6))
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
        self.print_button = action('Print PDF', 'document-print-symbolic', self.print_pdf, self, QKeySequence.StandardKey.Print)
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
        for button in (self.zoom_out, self.zoom_in, self.fit, self.search, self.print_button, self.markup):
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
        self.start_stage = self.empty_stage('Open a PDF', 'Choose a PDF or drop one here.', 'Open PDF…', self.choose_file)
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
        required = self.navigation.sizeHint().width() + self.tools.sizeHint().width() + self.toolbar.spacing()
        available = self.centralWidget().contentsRect().width() - 16
        horizontal = required <= available
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
        if not self.can_leave_document():
            return False
        self.start_stage.hide()
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
        try:
            source_revision = revision(path)
            key = self.positions.key(path)
        except (OSError, RuntimeError):
            source_revision = key = None
        self.renderer.cancel()
        self.clear_matches()
        self.document = None
        self.position_key = None
        self.count = 0
        self.update_buttons()
        self.canvas.show_message('Opening PDF…')
        self.status.setText('Opening PDF…')

        def ready(output, error):
            match = re.search(rb'^Pages:\s+([0-9]{1,8})\s*$', output, re.MULTILINE)
            if error or not match or not int(match[1]):
                message = error or 'This file does not appear to be a readable PDF.'
                self.canvas.show_message(message)
                self.status.setText(message)
                return
            self.document, self.count = path, int(match[1])
            self.position_key = key
            self.annotation_revision = source_revision
            self.canvas.zoom = None
            self.setWindowTitle(f'{path.name} — PDF Viewer')
            self.title.setText(path.name)
            self.title.setToolTip(str(path))
            page = self.positions.get(key, self.count) if key else 1
            self.go(page, resumed=page > 1)

        self.inspector.run('pdfinfo', [str(path)], ready)
        return True

    def go(self, page, *, resumed=False):
        if not self.document or not 1 <= page <= self.count:
            return
        self.annotation_reader.cancel()
        self.page = page
        self.canvas.label.set_tool(self.annotation_mode)
        self.refresh_marks()
        self.canvas.show_message('Loading page…')
        self.update_buttons()
        self.status.setText(f'Page {page} of {self.count}')

        key = self.position_key
        def ready(output, error):
            image = QImage.fromData(output, 'PNG') if not error else QImage()
            if image.isNull():
                message = error or 'This page could not be rendered.'
                self.canvas.show_message(message)
                self.status.setText(message)
                return
            self.canvas.set_image(image)
            if resumed:
                self.status.setText(f'Resumed at page {page} of {self.count}')
            if key:
                self.pending_position = (key, page)
                self.position_timer.start()

        self.renderer.run('pdftoppm', ['-f', str(page), '-l', str(page), '-singlefile',
                                       '-scale-to', '2200', '-cropbox', '-png', str(self.document)],
                          ready, maximum=PNG_LIMIT)

    def can_leave_document(self):
        if self.exporting:
            self.status.setText('Wait for the annotated copy to finish saving.')
            return False
        return not self.annotation_dirty or themed_prompt(
            self, 'Discard unsaved markup?', 'Save an annotated copy if you want to keep these changes.',
            'Discard', 'Cancel')

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
        args = [str(Path(__file__).with_name('pdf_annotations.py')), operation, str(self.document)]
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
            dialog.exec()
            dialog.deleteLater()

        self.annotation_request(self.annotation_reader, 'notes', {'page': page}, ready)

    def save_annotated_copy(self):
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
        self.exporting = True
        self.set_annotation_mode('')
        self.status.setText('Saving annotated copy…')

        def ready(result, error):
            self.exporting = False
            if result:
                self.annotation_dirty = False
            self.update_annotation_actions()
            self.status.setText(error or f'Annotated copy saved to {path}')

        self.annotation_request(self.exporter, 'save', {'revision': self.annotation_revision, 'marks': self.marks},
                                ready, path)

    def save_position(self):
        self.position_timer.stop()
        if self.pending_position and self.positions.save(*self.pending_position):
            self.pending_position = None

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
                                      '-enc', 'UTF-8', str(self.document), '-'],
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
            self.printer.run('lp', ['-d', printer, '--', str(self.document)],
                             lambda _output, error: self.status.setText(error or 'PDF sent to printer.'))

    def update_buttons(self):
        self.page_button.setText(f'Page {self.page} / {self.count}' if self.count else 'Page — / —')
        self.page_button.setAccessibleName(f'Page {self.page} of {self.count} — Go to page' if self.count else 'Go to page')
        self.update_toolbar_layout()
        self.previous.setEnabled(self.page > 1 and bool(self.count))
        self.next.setEnabled(self.page < self.count)
        for button in (self.page_button, self.zoom_in, self.zoom_out, self.fit, self.search, self.print_button):
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
        if not self.can_leave_document():
            event.ignore()
            return
        self.save_position()
        for process in (self.inspector, self.renderer, self.finder, self.printer, self.annotation_reader, self.exporter):
            process.close()
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
