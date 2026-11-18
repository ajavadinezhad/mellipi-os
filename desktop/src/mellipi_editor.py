"""Mellipi Editor: themed plain text, safe saves, and private crash recovery."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from difflib import unified_diff
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from threading import Event
import uuid

from PyQt6.QtCore import QIODevice, QLockFile, QSaveFile, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QFontDatabase, QIcon, QKeySequence, QShortcut, QTextCursor, QTextOption
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSizePolicy, QTabWidget, QVBoxLayout, QWidget,
)

from file_chooser import FileChooser
from desktop_icons import rename_no_replace
from installed_launcher import user_environment
from qt_app import action_ink, AppWindow, exec_owned_dialog, style_dialog, themed_choice, symbolic_icon, themed_prompt

MAX_BYTES = 8 * 1024 * 1024
MAX_TABS = 24
MAX_DRAFT_BYTES = 6 * MAX_BYTES + 16384
MODIFIED = object()


def read_regular(path, limit=MAX_BYTES):
    """Read only regular, bounded files, without blocking on special paths."""
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NONBLOCK), 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Choose a regular text file.')
        if info.st_size > limit:
            raise ValueError('This file is too large to open in Editor.')
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('This file is too large to open in Editor.')
    return data


def decode(data):
    bom = data.startswith(b'\xef\xbb\xbf')
    text = data.decode('utf-8-sig')
    if '\0' in text:
        raise ValueError('This file looks binary. Editor opens UTF-8 plain text.')
    # Qt stores paragraph and line separator characters as line breaks on
    # conversion back to plain text. Reject such files to avoid changing them.
    if '\u2028' in text or '\u2029' in text:
        raise ValueError('This file has Unicode line separators that Editor cannot preserve.')
    lines = re.findall(r'\r\n|\r|\n', text)
    newline = lines[0] if lines else '\n'
    if any(line != newline for line in lines):
        raise ValueError('This file mixes line endings. Convert them in another editor before editing here.')
    return text.replace('\r\n', '\n').replace('\r', '\n'), newline, bom


def signature(data):
    return hashlib.sha256(data).hexdigest()


def file_identity(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('Choose a regular text file, not a folder or link.')
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def write_atomic(path, data, private=False, *, before_commit=None):
    target = QSaveFile(str(path))
    target.setDirectWriteFallback(False)
    if not target.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(target.errorString())
    if private:
        from PyQt6.QtCore import QFileDevice
        rw = QFileDevice.Permission.ReadOwner | QFileDevice.Permission.WriteOwner
        if not target.setPermissions(rw):
            target.cancelWriting()
            raise OSError(target.errorString())
    if target.write(data) != len(data):
        target.cancelWriting()
        raise OSError(target.errorString())
    if before_commit is not None:
        try:
            before_commit()
        except (OSError, ValueError):
            target.cancelWriting()
            raise
    if not target.commit():
        raise OSError(target.errorString())


def write_new_file(path, data):
    with tempfile.TemporaryDirectory(prefix='.mellipi-editor-', dir=path.parent) as private:
        staged = Path(private) / 'text'
        write_atomic(staged, data)
        rename_no_replace(staged, path)


def stage_draft(path, payload, canceled):
    """Encode and sync a private draft without holding the UI's document lock."""
    text = payload['text']
    if len(text.replace('\n', payload['newline']).encode('utf-8')) + (3 if payload['bom'] else 0) > MAX_BYTES:
        raise ValueError('This document exceeds the editor size limit.')
    if canceled.is_set():
        return None
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.pending-draft-')
    stage = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        return stage
    except BaseException:
        stage.unlink(missing_ok=True)
        raise


class Document(QPlainTextEdit):
    def __init__(self, path=None, text='', newline='\n', bom=False, digest=None):
        super().__init__()
        self.path, self.newline, self.bom, self.digest = path, newline, bom, digest
        self.draft_id = uuid.uuid4().hex
        self.draft_lock = None
        self.draft_written = False
        self.draft_pending = False
        self.setAccessibleName('Document')
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setPlainText(text)
        self.document().setModified(False)

    @property
    def name(self):
        return self.path.name if self.path else 'Untitled'

    def plain_text(self):
        # Qt's toPlainText() turns nonbreaking spaces into ASCII spaces.
        return self.document().toRawText().replace('\u2029', '\n').replace('\u2028', '\n')

    def data(self):
        text = self.plain_text()
        if '\0' in text:
            raise ValueError('Remove NUL characters before saving a UTF-8 text file.')
        data = text.replace('\n', self.newline).encode('utf-8')
        if self.bom:
            data = b'\xef\xbb\xbf' + data
        if len(data) > MAX_BYTES:
            raise ValueError('This document exceeds the 8 MiB editor limit.')
        return data


class Editor(AppWindow):
    draftFinished = pyqtSignal(str, object, object)
    extra_style = '''
        QPlainTextEdit { background: %(surface)s; color: %(text)s;
                         border: 1px solid %(input_edge)s; padding: 12px; }
        QPlainTextEdit:focus { border-color: %(focus)s; }
        QTabWidget::pane { border: 0; }
        QPushButton#saveDocument:enabled { background: %(accent)s; color: %(accent_text)s; font-weight: 600; }
        QPushButton#saveDocument:enabled:hover, QPushButton#saveDocument:enabled:focus { border-color: %(accent_text)s; }
        QPushButton#editorMatchCase:checked { border-color: %(focus)s; }
    '''

    def __init__(self, paths=(), recovery=None):
        super().__init__('Text Editor')
        self.resize(860, 570)
        self.setMinimumSize(520, 340)
        self.recovery = recovery or Path(user_environment()['XDG_STATE_HOME']) / 'mellipi' / 'editor-drafts'
        self.draft_pool = None
        self.draft_jobs = {}
        self.draftFinished.connect(self.finish_draft)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(700)
        self.timer.timeout.connect(self.flush_drafts)

        self.tabs = QTabWidget(documentMode=True, movable=True)
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.setElideMode(Qt.TextElideMode.ElideMiddle)
        self.tabs.setAccessibleName('Open documents')
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.active_changed)

        actions = QHBoxLayout()
        self.content.addLayout(actions)
        self.save_button = self.button('Save', 'document-save', self.save)
        self.save_button.setObjectName('saveDocument')
        self.save_button.setProperty('mellipiPrimary', True)
        self.save_button.setIcon(symbolic_icon('document-save', self.theme['accent_text']))
        new = self.button('New', 'tab-new', self.new_tab)
        open_file = self.button('Open', 'document-open', self.choose_open)
        find = self.button('Find', 'edit-find', self.show_find)
        replace = self.button('Replace', 'edit-find-replace', self.show_replace)
        self.compact_actions = (new, open_file, find, replace)
        for button in (new, open_file, self.save_button):
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(find)
        actions.addWidget(replace)

        self.find_panel = QWidget()
        panel = QVBoxLayout(self.find_panel)
        panel.setContentsMargins(0, 0, 0, 0)
        find_row = QHBoxLayout()
        self.query = QLineEdit(placeholderText='Find text')
        self.query.setAccessibleName('Find text')
        self.query.setMaxLength(4096)
        self.query.returnPressed.connect(self.find_next)
        self.case = QPushButton('Match case', objectName='editorMatchCase', checkable=True)
        find_row.addWidget(self.query, 1)
        self.find_actions = QWidget()
        find_actions = QHBoxLayout(self.find_actions)
        find_actions.setContentsMargins(0, 0, 0, 0)
        find_actions.addStretch()
        find_actions.addWidget(self.case)
        find_actions.addWidget(self.button('Previous', 'go-previous', self.find_previous, icon_only=True))
        find_actions.addWidget(self.button('Next', 'go-next', self.find_next, icon_only=True))
        find_actions.addWidget(self.button('Close find', 'window-close', self.hide_find, icon_only=True))
        find_row.addWidget(self.find_actions)
        panel.addLayout(find_row)
        self.replace_row = QWidget()
        row = QHBoxLayout(self.replace_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.replacement = QLineEdit(placeholderText='Replace with')
        self.replacement.setAccessibleName('Replacement text')
        self.replacement.setMaxLength(4096)
        row.addWidget(self.replacement, 1)
        self.replace_actions = QWidget()
        replace_actions = QHBoxLayout(self.replace_actions)
        replace_actions.setContentsMargins(0, 0, 0, 0)
        replace_actions.addStretch()
        replace_actions.addWidget(self.button('Replace', 'edit-find-replace', self.replace_one))
        replace_actions.addWidget(self.button('Replace all', 'edit-find-replace', self.replace_all))
        row.addWidget(self.replace_actions)
        panel.addWidget(self.replace_row)
        self.find_panel.hide()
        self.line_panel = QWidget()
        line_row = QHBoxLayout(self.line_panel)
        line_row.setContentsMargins(0, 0, 0, 0)
        line_label = QLabel('Line number')
        self.line_input = QLineEdit()
        self.line_input.setAccessibleName('Line number')
        self.line_input.setInputMethodHints(Qt.InputMethodHint.ImhDigitsOnly)
        self.line_input.returnPressed.connect(self.go_to_line)
        line_label.setBuddy(self.line_input)
        line_row.addWidget(line_label)
        line_row.addWidget(self.line_input, 1)
        go = self.button('Go to line', 'check', self.go_to_line, icon_only=True)
        line_row.addWidget(go)
        line_row.addWidget(self.button('Close Go to Line', 'window-close', self.hide_navigation, icon_only=True))
        self.line_panel.hide()
        self.content.addWidget(self.tabs, 1)
        # Search and Go to Line act on the current document, underneath its
        # tab/editor so opening a tool doesn't displace the tab navigation.
        self.content.addWidget(self.find_panel)
        self.content.addWidget(self.line_panel)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setObjectName('muted')
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        footer = QHBoxLayout()
        footer.addWidget(self.status, 1)
        self.wrap_button = QPushButton('Wrap lines')
        self.wrap_button.setToolTip('Wrap long lines in this tab (F10)')
        self.wrap_button.setCheckable(True)
        self.wrap_button.clicked.connect(self.toggle_line_wrap)
        footer.addWidget(self.wrap_button)
        self.position = QPushButton()
        self.position.setToolTip('Go to Line (Ctrl+G)')
        self.position.clicked.connect(self.show_go_to_line)
        footer.addWidget(self.position)
        self.content.addLayout(footer)
        self.window_icon = QIcon.fromTheme('mellipi-editor', QIcon.fromTheme('accessories-text-editor'))
        self.setWindowIcon(self.window_icon)

        for shortcut, handler in (
            (QKeySequence.StandardKey.New, self.new_tab),
            ('Ctrl+T', self.new_tab), (QKeySequence.StandardKey.Open, self.choose_open),
            (QKeySequence.StandardKey.Save, self.save), ('Ctrl+Shift+S', self.save_as),
            (QKeySequence.StandardKey.Close, lambda: self.close_tab(self.tabs.currentIndex())),
            (QKeySequence.StandardKey.Find, self.show_find), ('Ctrl+H', self.show_replace),
            ('F3', self.find_next), ('Shift+F3', self.find_previous),
            ('F10', self.toggle_line_wrap),
            ('Ctrl+G', self.show_go_to_line), ('Escape', self.hide_navigation),
        ):
            QShortcut(QKeySequence(shortcut), self).activated.connect(handler)

        self.themeChanged.connect(self.update_document_fonts)
        self.themeChanged.connect(self.update_action_layout)
        self.update_action_layout()
        self.restore_drafts()
        for path in paths:
            self.open_path(path)
        if not self.tabs.count():
            self.new_tab()

    def button(self, name, icon, handler, icon_only=False):
        button = QPushButton('' if icon_only else name)
        button.setAccessibleName(name)
        button.setToolTip(name)
        if icon_only:
            button.setMinimumSize(32, 32)
        button.setProperty('mellipiSymbolicIcon', icon)
        button.setIcon(symbolic_icon(icon, action_ink(self.theme, icon)))
        button.clicked.connect(lambda _checked=False: handler())
        return button

    def update_action_layout(self):
        # Keep Save labelled; hide secondary labels before they crowd the editor.
        compact = self.width() < self.theme['font_size'] * 36
        glyph = max(16, min(24, self.theme['font_size'] + 2))
        for button in self.findChildren(QPushButton):
            if button.property('mellipiSymbolicIcon'):
                button.setIconSize(QSize(glyph, glyph))
        for button in self.compact_actions:
            label = '' if compact else button.accessibleName()
            if button.text() != label:
                button.setText(label)
            button.setMinimumWidth(glyph + 12)
        fields = (self.query, self.replacement, self.line_input)
        bar_height = max(glyph + 14, *(field.sizeHint().height() for field in fields))
        for field in fields:
            field.setFixedHeight(bar_height)
        for actions in (self.find_actions, self.replace_actions):
            for button in actions.findChildren(QPushButton):
                button.setFixedHeight(bar_height)
        self.align_find_columns()

    def align_find_columns(self):
        groups = (self.find_actions, self.replace_actions)
        width = max(group.layout().minimumSize().width() for group in groups)
        for group in groups:
            group.setFixedWidth(width)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'compact_actions'):
            self.update_action_layout()

    def document(self):
        return self.tabs.currentWidget()

    def add_document(self, doc):
        doc.document().modificationChanged.connect(lambda _value: self.refresh_tab(doc))
        doc.textChanged.connect(lambda: self.queue_draft(doc))
        doc.cursorPositionChanged.connect(self.update_position)
        index = self.tabs.addTab(doc, doc.name)
        self.add_tab_close_button(self.tabs, index)
        self.tabs.setCurrentIndex(index)
        self.refresh_tab(doc)
        self.update_document_fonts()
        doc.setFocus()
        return doc

    def new_tab(self):
        if self.tabs.count() >= MAX_TABS:
            self.status.setText('Close a tab before opening another.')
            return
        return self.add_document(Document())

    def choose_open(self):
        doc = self.document()
        folder = doc.path.parent if doc is not None and doc.path else Path.home()
        files, _ = FileChooser.getOpenFileNames(self, 'Open text files', str(folder))
        for file in files:
            self.open_path(file)

    def open_path(self, value):
        try:
            path = local_path(value)
            for i in range(self.tabs.count()):
                if self.tabs.widget(i).path == path:
                    self.tabs.setCurrentIndex(i)
                    return
            if self.tabs.count() >= MAX_TABS:
                self.status.setText('Close a tab before opening another.')
                return
            data = read_regular(path)
            content, newline, bom = decode(data)
        except (OSError, ValueError, UnicodeError) as error:
            themed_prompt(self, 'Could not open file', str(error), 'OK')
            return
        previous = self.document()
        self.add_document(Document(path, content, newline, bom, signature(data)))
        if previous and previous.path is None and not previous.document().isModified() and not previous.toPlainText():
            self.remove_document(previous)
        return path

    def save_as(self):
        return self.save(force_dialog=True)

    def save(self, doc=None, force_dialog=False):
        doc = doc or self.document()
        if not doc:
            return False
        path = doc.path
        try:
            if force_dialog or not path:
                start = str(path or Path.home() / 'Untitled.txt')
                value, _ = FileChooser.getSaveFileName(self, 'Save text file', start,
                    options=QFileDialog.Option.DontConfirmOverwrite)
                if not value:
                    return False
                path = local_path(value)
            for i in range(self.tabs.count()):
                other = self.tabs.widget(i)
                if other is not doc and other.path == path:
                    raise ValueError('This path is already open in another tab.')
            if path == doc.path:
                try:
                    disk_data = read_regular(path)
                    external = signature(disk_data)
                except FileNotFoundError:
                    disk_data = None
                    external = None
                except (OSError, ValueError):
                    disk_data = None
                    external = MODIFIED
                if external != doc.digest:
                    choice = themed_choice(
                        self, 'File changed on disk',
                        f'{doc.name} changed outside Editor. Reload the disk version or overwrite it. '
                        'Reload keeps any unsaved edits in a separate tab.',
                        'Overwrite', 'Cancel', 'Reload' if disk_data is not None else None,
                        secondary='Compare with Disk' if disk_data is not None else None,
                    )
                    if choice == 3:
                        self.compare_disk(doc)
                        return False
                    if choice == 2:
                        disk_data = read_regular(path)
                        content, newline, bom = decode(disk_data)
                        if doc.document().isModified():
                            if self.tabs.count() >= MAX_TABS:
                                raise ValueError('Close a tab before reloading so Editor can keep your edits.')
                            self.keep_reload_draft(doc)
                        doc.setPlainText(content)
                        doc.newline, doc.bom, doc.digest = newline, bom, signature(disk_data)
                        doc.document().setModified(False)
                        self.clear_draft(doc)
                        self.refresh_tab(doc)
                        self.status.setText(f'Reloaded {doc.name}')
                        return False
                    if choice != 1:
                        return False
                    try:
                        latest = signature(read_regular(path))
                    except FileNotFoundError:
                        latest = None
                    if latest != external:
                        raise ValueError('The file changed again during confirmation. Review the latest version.')
                if external == doc.digest and not doc.document().isModified():
                    return True
            data = doc.data()
            if path != doc.path:
                expected = file_identity(path)
                if expected is None:
                    write_new_file(path, data)
                else:
                    if not themed_prompt(self, 'Replace file?', f'{path.name} already exists.',
                                         'Replace File', 'Cancel'):
                        return False
                    def check_destination():
                        if file_identity(path) != expected:
                            raise ValueError('The destination changed. Check it before trying again.')
                    write_atomic(path, data, before_commit=check_destination)
            else:
                expected = file_identity(path)
                if expected is None:
                    write_new_file(path, data)
                else:
                    def check_source():
                        if file_identity(path) != expected or signature(read_regular(path)) != external:
                            raise ValueError('The file changed while saving. Check it before trying again.')
                    write_atomic(path, data, before_commit=check_source)
        except (OSError, ValueError, UnicodeError) as error:
            themed_prompt(self, 'Could not save file', str(error), 'OK')
            return False
        doc.path = path
        doc.digest = signature(data)
        doc.document().setModified(False)
        self.clear_draft(doc)
        self.refresh_tab(doc)
        self.status.setText(f'Saved {doc.name}')
        return True

    def compare_disk(self, doc):
        """Compare a bounded snapshot without changing the current buffer or its draft."""
        try:
            content, _, _ = decode(read_regular(doc.path))
            current = doc.plain_text()
            if max(len(content), len(current)) > 256_000:
                raise ValueError('The comparison limit is 256,000 characters.')
            previous, edited = content.splitlines(keepends=True), current.splitlines(keepends=True)
            if max(len(previous), len(edited)) > 2_000:
                raise ValueError('The comparison limit is 2,000 lines.')
            lines = unified_diff(previous, edited, 'On disk', 'Current draft', lineterm='')
            comparison = '\n'.join(line.rstrip('\n') for line in lines)
        except (OSError, ValueError, UnicodeError) as error:
            themed_prompt(self, 'Could not compare file', str(error), 'OK')
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Compare with Disk')
        style_dialog(dialog, self)
        layout = QVBoxLayout(dialog)
        preview = QPlainTextEdit()
        preview.setReadOnly(True)
        preview.setAccessibleName('Differences: on disk and current draft')
        preview.setPlainText(comparison or 'No text differences.')
        preview.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        layout.addWidget(preview)
        close = QPushButton('Close')
        close.clicked.connect(dialog.accept)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
        dialog.resize(620, 420)
        try:
            exec_owned_dialog(dialog)
        finally:
            dialog.deleteLater()

    def refresh_tab(self, doc):
        index = self.tabs.indexOf(doc)
        if index < 0:
            return
        modified = doc.document().isModified()
        self.tabs.setTabText(index, doc.name.replace('&', '&&') + (' •' if modified else ''))
        self.tabs.setTabToolTip(index, str(doc.path if doc.path else doc.name))
        if doc is self.document():
            self.setWindowTitle(f'{doc.name} — Mellipi Editor')
            self.title.setText(doc.name)
            self.title.setTextFormat(Qt.TextFormat.PlainText)

    def active_changed(self, _index):
        if not self.line_panel.isHidden():
            self.line_panel.hide()
        self.status.clear()
        doc = self.document()
        self.wrap_button.setEnabled(doc is not None)
        self.wrap_button.setChecked(bool(doc and doc.lineWrapMode() == QPlainTextEdit.LineWrapMode.WidgetWidth))
        if doc:
            self.refresh_tab(doc)
        self.update_position()

    def toggle_line_wrap(self):
        doc = self.document()
        if doc is None:
            return
        wrapped = doc.lineWrapMode() == QPlainTextEdit.LineWrapMode.WidgetWidth
        doc.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap if wrapped else QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.wrap_button.setChecked(not wrapped)
        doc.ensureCursorVisible()

    def update_position(self):
        doc = self.document()
        if doc and hasattr(self, 'status'):
            cursor = doc.textCursor()
            line = f'Line {cursor.blockNumber()+1}, column {cursor.positionInBlock()+1}'
            self.position.setText(line)
            self.position.setAccessibleName(f'Go to Line: {line}')

    def update_document_fonts(self):
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPixelSize(self.theme['font_size'])
        for i in range(self.tabs.count()):
            doc = self.tabs.widget(i)
            doc.setFont(font)
            doc.document().setDefaultFont(font)

    def show_find(self):
        self.line_panel.hide()
        self.replace_row.hide()
        self.find_panel.show()
        self.query.setFocus()
        self.query.selectAll()

    def show_replace(self):
        self.show_find()
        self.replace_row.show()
        self.align_find_columns()

    def hide_find(self):
        if not self.find_panel.isVisible():
            return
        self.find_panel.hide()
        if self.document():
            self.document().setFocus()

    def show_go_to_line(self):
        doc = self.document()
        if not doc:
            return
        self.find_panel.hide()
        self.line_panel.show()
        self.status.clear()
        self.line_input.setText(str(doc.textCursor().blockNumber() + 1))
        self.line_input.setFocus()
        self.line_input.selectAll()

    def go_to_line(self):
        doc = self.document()
        if not doc:
            return
        value = self.line_input.text().strip()
        last = doc.document().blockCount()
        line = int(value) if re.fullmatch(r'[0-9]{1,12}', value) else 0
        if not 1 <= line <= last:
            self.status.setText(f'Enter a line number from 1 to {last}.')
            self.line_input.setFocus()
            self.line_input.selectAll()
            return
        block = doc.document().findBlockByNumber(line - 1)
        if not block.isValid():
            return
        doc.setTextCursor(QTextCursor(block))
        doc.ensureCursorVisible()
        self.hide_navigation()

    def hide_navigation(self):
        if not self.line_panel.isHidden():
            self.line_panel.hide()
            self.status.clear()
            if self.document():
                self.document().setFocus()
        else:
            self.hide_find()

    def find_next(self):
        return self.find()

    def find_previous(self):
        return self.find(backward=True)

    def find(self, backward=False):
        from PyQt6.QtGui import QTextDocument
        doc = self.document()
        term = self.query.text()
        if not doc or not term:
            return False
        flags = QTextDocument.FindFlag(0)
        if self.case.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if backward:
            flags |= QTextDocument.FindFlag.FindBackward
        original = doc.textCursor()
        if doc.find(term, flags):
            return True
        doc.moveCursor(QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start)
        if doc.find(term, flags):
            self.status.setText('Search wrapped')
            return True
        doc.setTextCursor(original)
        self.status.setText('No match')
        return False

    def pattern(self):
        return re.compile(re.escape(self.query.text()), 0 if self.case.isChecked() else re.IGNORECASE)

    def replace_one(self):
        doc = self.document()
        if not doc or not self.query.text():
            return
        pattern = self.pattern()
        matched = pattern.fullmatch(doc.textCursor().selectedText())
        if not matched and not self.find_next():
            return
        cursor = doc.textCursor()
        cursor.insertText(self.replacement.text())
        self.find_next()

    def replace_all(self):
        doc = self.document()
        if not doc or not self.query.text():
            return
        pattern = self.pattern()
        old = doc.plain_text()
        replacement = self.replacement.text()
        count = 0
        new_size = len(old.encode('utf-8'))
        replacement_size = len(replacement.encode('utf-8'))
        for match in pattern.finditer(old):
            count += 1
            new_size += replacement_size - len(match.group().encode('utf-8'))
        if not count:
            self.status.setText('No match')
            return
        # Guard the projected allocation before substituting. Case-insensitive
        # Unicode matches can occupy different numbers of bytes than the query.
        if new_size > MAX_BYTES:
            self.status.setText('Replace all would exceed the editor size limit.')
            return
        updated = pattern.sub(lambda _match: replacement, old)
        cursor = doc.textCursor()
        start = cursor.position()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(updated)
        cursor.endEditBlock()
        cursor.setPosition(min(start, doc.document().characterCount() - 1))
        doc.setTextCursor(cursor)
        self.status.setText(f'Replaced {count} matches')

    def close_choice(self, doc):
        return themed_choice(self, 'Unsaved changes', f'Save changes to {doc.name}?',
                             'Save', 'Cancel', 'Discard')

    def confirm_close(self, doc):
        if not doc.document().isModified():
            return True
        self.tabs.setCurrentWidget(doc)
        choice = self.close_choice(doc)
        return choice == 2 or (choice == 1 and self.save(doc))

    def remove_document(self, doc):
        self.clear_draft(doc)
        self.tabs.removeTab(self.tabs.indexOf(doc))
        doc.deleteLater()

    def close_tab(self, index):
        doc = self.tabs.widget(index)
        if doc is not None and self.confirm_close(doc):
            self.remove_document(doc)
            if not self.tabs.count():
                self.new_tab()

    def closeEvent(self, event):
        docs = [self.tabs.widget(i) for i in range(self.tabs.count())]
        # Keep untouched/discarded drafts if a later tab cancels window closure.
        for doc in docs:
            if not self.confirm_close(doc):
                event.ignore()
                return
        self.timer.stop()
        for doc in docs:
            self.clear_draft(doc)
        if self.draft_pool is not None:
            self.draft_pool.shutdown(wait=False, cancel_futures=True)
            self.draft_pool = None
        event.accept()

    def recovery_directory(self):
        self.recovery.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.recovery.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise PermissionError('The editor recovery folder is not private.')

    def keep_reload_draft(self, doc):
        """Persist the preserved tab before replacing text or dropping its old draft."""
        copy = Document(text=doc.plain_text(), newline=doc.newline, bom=doc.bom)
        self.recovery_directory()
        path = self.draft_path(copy)
        copy.draft_lock = self.lock_draft(path)
        if not copy.draft_lock:
            raise OSError('Could not reserve a recovery file for your unsaved edits.')
        staged = None
        try:
            staged = stage_draft(path, dict(path=None, text=copy.plain_text(), newline=copy.newline,
                                            bom=copy.bom, digest=None), Event())
            os.replace(staged, path)
            copy.draft_written = True
            self.add_document(copy)
            copy.document().setModified(True)
        except (OSError, ValueError, UnicodeError):
            copy.draft_lock.unlock()
            raise
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)

    def queue_draft(self, doc):
        doc.draft_pending = True
        if not self.timer.isActive():
            self.timer.start()

    def draft_path(self, doc):
        return self.recovery / (doc.draft_id + '.json')

    def lock_draft(self, path):
        lock = QLockFile(str(path.with_suffix('.lock')))
        lock.setStaleLockTime(0)  # Only break locks when the owning process is gone.
        return lock if lock.tryLock(0) else None

    def flush_drafts(self):
        for index in range(self.tabs.count()):
            doc = self.tabs.widget(index)
            if not doc.draft_pending:
                continue
            if doc.draft_id in self.draft_jobs:
                continue
            doc.draft_pending = False
            if not doc.document().isModified():
                self.clear_draft(doc)
                continue
            try:
                self.recovery_directory()
                path = self.draft_path(doc)
                if not doc.draft_lock:
                    doc.draft_lock = self.lock_draft(path)
                if not doc.draft_lock:
                    raise OSError('The recovery file is already owned by another editor.')
                payload = dict(path=str(doc.path) if doc.path else None, text=doc.plain_text(),
                               newline=doc.newline, bom=doc.bom, digest=doc.digest)
                if self.draft_pool is None:
                    self.draft_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='editor-drafts')
                canceled = Event()
                self.draft_jobs[doc.draft_id] = (doc, path, canceled)
                future = self.draft_pool.submit(stage_draft, path, payload, canceled)

                def complete(task, token=doc.draft_id, stop=canceled):
                    try:
                        staged = task.result()
                    except Exception as error:
                        if not stop.is_set():
                            self.draftFinished.emit(token, None, error)
                        return
                    if staged is None:
                        return
                    if stop.is_set():
                        staged.unlink(missing_ok=True)
                    else:
                        self.draftFinished.emit(token, staged, None)

                future.add_done_callback(complete)
            except (OSError, ValueError, UnicodeError):
                self.status.setText('Could not write a recovery draft. Save changes to keep them.')

    def finish_draft(self, token, staged, error):
        job = self.draft_jobs.pop(token, None)
        try:
            if job is None:
                return
            doc, path, canceled = job
            if error is not None:
                raise error
            if staged is not None and not canceled.is_set():
                os.replace(staged, path)
                doc.draft_written = True
            if doc.draft_pending and not self.timer.isActive():
                self.timer.start()
        except (OSError, ValueError, UnicodeError):
            self.status.setText('Could not write a recovery draft. Save changes to keep them.')
        finally:
            if staged is not None:
                staged.unlink(missing_ok=True)

    def clear_draft(self, doc):
        doc.draft_pending = False
        job = self.draft_jobs.pop(doc.draft_id, None)
        if job is not None:
            job[-1].set()
        try:
            if doc.draft_written:
                self.draft_path(doc).unlink(missing_ok=True)
                doc.draft_written = False
        except OSError:
            self.status.setText('Could not remove an old recovery draft.')
        finally:
            if doc.draft_lock:
                doc.draft_lock.unlock()
                doc.draft_lock = None
            if job is not None:
                # A queued completion from the previous save cannot target a
                # later draft of this document.
                doc.draft_id = uuid.uuid4().hex

    def restore_drafts(self):
        try:
            self.recovery_directory()
            candidates = sorted(self.recovery.glob('*.json'))[:128]
        except OSError:
            return
        for path in candidates:
            if self.tabs.count() >= MAX_TABS or not re.fullmatch(r'[0-9a-f]{32}', path.stem):
                continue
            lock = self.lock_draft(path)
            if not lock:
                continue
            try:
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                    raise ValueError('Untrusted recovery file.')
                draft = json.loads(read_regular(path, MAX_DRAFT_BYTES))
                original = draft['path']
                digest = draft['digest']
                text = draft['text']
                if (original is not None and (not isinstance(original, str) or not Path(original).is_absolute())
                        or not isinstance(text, str) or len(text.encode('utf-8')) > MAX_BYTES
                        or draft['newline'] not in ('\r\n', '\r', '\n')
                        or not isinstance(draft['bom'], bool)
                        or digest is not None and (not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest))):
                    raise ValueError('Invalid recovery data.')
                doc = Document(Path(original) if original else None, text, draft['newline'], draft['bom'], digest)
                doc.draft_id = path.stem
                doc.draft_lock = lock
                doc.draft_written = True
                doc.document().setModified(True)
                self.add_document(doc)
                self.status.setText('Recovered unsaved changes')
            except (KeyError, OSError, TypeError, ValueError):
                lock.unlock()


def local_path(value):
    if value.startswith('file:') or '://' in value:
        url = QUrl(value)
        if not url.isLocalFile() or url.host() not in ('', 'localhost') or not url.toLocalFile():
            raise ValueError('Editor opens local files only.')
        value = url.toLocalFile()
    return Path(value).expanduser().resolve()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='*')
    args = parser.parse_args(argv)
    os.environ['QT_WAYLAND_SHELL_INTEGRATION'] = 'xdg-shell'
    os.environ.pop('QT_WAYLAND_DISABLE_WINDOWDECORATION', None)
    app = QApplication([sys.argv[0]])
    app.setApplicationName('Mellipi Editor')
    app.setDesktopFileName('mellipi-editor')
    window = Editor(args.files)
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
