"""Mellipi's local file browser, in a normal desktop window."""
import argparse
from collections import Counter
from html import escape
import os
import sys
import weakref
from pathlib import Path

os.environ['ORBIT_QT'] = '6'
os.environ['QT_WAYLAND_SHELL_INTEGRATION'] = 'xdg-shell'
os.environ.pop('QT_WAYLAND_DISABLE_WINDOWDECORATION', None)

from PyQt6.QtCore import (
    QDateTime, QDir, QEvent, QItemSelectionModel, QLocale, QModelIndex, QMimeData,
    QPoint, QRect, QSettings, QSignalBlocker, QSize, QSortFilterProxyModel, Qt, QThread, QTimer, QUrl, pyqtSignal,
)
from PyQt6.QtGui import QAction, QFileSystemModel, QDesktopServices, QDrag, QFontMetrics, QIcon, QKeySequence, QPainter
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMenu, QProgressBar, QPushButton, QScrollArea, QStackedWidget, QTreeView, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)
from gi.repository import Gio
from qt_app import style_dialog, ThemedInput, AppIdentityBadge, BASE_STYLE, ThemeWatch, apply_titlebar, original_icon, themed_prompt, widget_palette
from qt_titlebar import TitleBar
from desktop_icons import rename_no_replace, safe_name, trash_item
from device_monitor import DeviceMonitor
from file_transfers import MAX_SOURCES, Cancelled, CancelToken, Transfer
from file_archives import archive_suffix, compress, extract_here, preview_archive
from storage_analyzer import analyze
from files_icons import ACTIONS, PLACES, file_icon, icon as phosphor_icon, place_icon


class FileJob(QThread):
    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation
        self.error = ""
        self.value = None
        self.canceled = False

    def run(self):
        try:
            self.value = self.operation()
        except Cancelled:
            self.canceled = True
        except Exception as error:
            self.error = str(error)


class TransferJob(FileJob):
    progress = pyqtSignal(object)

    def __init__(self, paths, folder, move, parent):
        self.token = CancelToken()
        super().__init__(lambda: Transfer(folder.resolve(), rename_no_replace, trash_item,
                                          self.token, self.progress.emit).run(paths, move), parent)


class TransferStrip(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName('fileTransfer')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        self.message = QLabel()
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.bar = QProgressBar()
        self.bar.setAccessibleName('Current file transfer progress')
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        layout.addWidget(self.bar)
        controls = QHBoxLayout()
        controls.addStretch()
        self.keep = QPushButton('Keep Both')
        self.skip = QPushButton('Skip')
        self.cancel = QPushButton('Cancel Transfer')
        for button in (self.keep, self.skip, self.cancel):
            controls.addWidget(button)
        self.keep.clicked.connect(lambda: self.resolve('keep-both'))
        self.skip.clicked.connect(lambda: self.resolve('skip'))
        self.cancel.clicked.connect(lambda: self.resolve('cancel'))
        layout.addLayout(controls)
        self.job = None
        self._collision_focus = None
        self.hide()

    def start(self, job, count, move):
        self.job = job
        self.state = {'count': count}
        self.cancel.setEnabled(True)
        self.update_progress({'message': 'Preparing move…' if move else 'Preparing copy…'})
        self.show()

    def update_progress(self, patch):
        if self.job is None or self.job.token.event.is_set():
            return
        had_collision = bool(self.state.get('conflict'))
        self.state.update(patch)
        collision = bool(self.state.get('conflict'))
        if had_collision and not collision:
            self.restore_collision_focus()
        self.keep.setVisible(collision)
        self.skip.setVisible(collision)
        if collision and not had_collision and self.window().isActiveWindow():
            opener = self.window().focusWidget()
            self._collision_focus = weakref.ref(opener) if opener is not None else None
            self.skip.setFocus(Qt.FocusReason.OtherFocusReason)
        self.bar.setVisible(not collision)
        current, total = self.state.get('currentBytes', 0), self.state.get('currentTotal', 0)
        self.bar.setRange(0, 100 if total else 0)
        if total:
            self.bar.setValue(min(100, current * 100 // total))
        message = self.state.get('message', '')
        if collision:
            message += '. Keep Both gives the incoming item a different name.'
        elif self.state.get('count', 0) > 1:
            message += f" · {self.state.get('completed', 0)} of {self.state['count']} transferred"
        self.message.setText(message)

    def restore_collision_focus(self):
        from PyQt6.sip import isdeleted
        previous = self._collision_focus() if self._collision_focus is not None else None
        self._collision_focus = None
        focused = self.window().focusWidget()
        if focused not in (self.skip, self.keep, self.cancel):
            return
        if previous is not None and not isdeleted(previous) and previous.isVisible() and previous.isEnabled():
            previous.setFocus(Qt.FocusReason.OtherFocusReason)

    def resolve(self, choice):
        if self.job is None or (choice != 'cancel' and not self.state.get('conflict')):
            return
        if choice != 'cancel':
            self.update_progress({'conflict': '', 'message': 'Continuing transfer…'})
        self.job.token.resolve(choice)
        if choice == 'cancel':
            self.restore_collision_focus()
            self.message.setText('Canceling transfer…')
            self.keep.hide()
            self.skip.hide()
            self.cancel.setEnabled(False)

    def finish(self):
        self.restore_collision_focus()
        self.job = None
        self.hide()


class StorageDialog(QDialog):
    def __init__(self, files, folder):
        super().__init__(files)
        self.files = files
        self.folder = folder
        self.job = None
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle('Storage Analyzer')
        self.resize(570, 420)
        self.refresh_theme()
        files.theme_watch.changed.connect(self.refresh_theme)
        layout = QVBoxLayout(self)
        title = QLabel(str(folder))
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        layout.addWidget(title)
        self.table = QTreeWidget()
        self.table.setAccessibleName('Largest items')
        self.table.setHeaderLabels(['Name', 'Size'])
        self.table.setRootIsDecorated(False)
        self.table.setUniformRowHeights(True)
        self.table.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.currentItemChanged.connect(self.update_open)
        self.table.itemActivated.connect(lambda *_: self.open_folder())
        layout.addWidget(self.table, 1)
        self.summary = QLabel('Scanning…')
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.open_button = QPushButton('Open Folder')
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_folder)
        self.stop_button = QPushButton('Cancel Scan')
        self.stop_button.clicked.connect(self.stop_or_close)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.stop_button)
        layout.addLayout(buttons)
        self.job = FileJob(lambda: analyze(folder, self.job.isInterruptionRequested), self)
        self.job.finished.connect(self.scan_finished)
        self.job.start()

    def refresh_theme(self):
        self.setStyleSheet(BASE_STYLE % self.files.theme_watch.tokens)

    def update_open(self, item, _previous):
        self.open_button.setEnabled(bool(item and item.data(0, Qt.ItemDataRole.UserRole)))

    def open_folder(self):
        item = self.table.currentItem()
        if item and (name := item.data(0, Qt.ItemDataRole.UserRole)):
            path = self.folder / name
            if path.is_symlink() or not path.is_dir():
                self.summary.setText('This folder is no longer available.')
                return
            self.files.navigate(path)
            self.close()

    def stop_or_close(self):
        if self.job is None:
            self.close()
        else:
            self.job.requestInterruption()
            self.stop_button.setEnabled(False)
            self.summary.setText('Stopping…')

    def scan_finished(self):
        job, self.job = self.job, None
        job.deleteLater()
        if self.files.close_when_idle:
            self.close()
            self.files.finish_deferred_close()
            return
        self.stop_button.setText('Close')
        self.stop_button.setEnabled(True)
        if job.error:
            self.summary.setText(f'Could not scan this folder: {job.error}')
            return
        report = job.value
        locale = QLocale()
        def size_text(size):
            return locale.formattedDataSize(size) if size < 2**63 else 'Over 8 EiB'
        for row in report.rows:
            item = QTreeWidgetItem([row.name, size_text(row.size)])
            if row.folder:
                item.setIcon(0, file_icon(row.name, True, *self.files.model.file_inks))
                item.setData(0, Qt.ItemDataRole.UserRole, row.name)
            self.table.addTopLevelItem(item)
        summary = f'{size_text(report.total)} of file data · {report.entries:,} entries scanned'
        if report.cancelled:
            summary += ' · Scan cancelled'
        elif report.incomplete:
            summary += ' · Some entries were skipped or the scan limit was reached'
        self.summary.setText(summary)

    def reject(self):
        if self.job is not None:
            self.stop_or_close()
        else:
            super().reject()

    def closeEvent(self, event):
        if self.job is not None:
            self.stop_or_close()
            event.ignore()
        else:
            super().closeEvent(event)


class FolderModel(QFileSystemModel):
    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.ToolTipRole and index.isValid() and index.column() == 0:
            stamp = super().data(index.siblingAtColumn(3), Qt.ItemDataRole.DisplayRole)
            name = escape(self.fileName(index))
            return f'<div>{name}<br>Modified: {escape(str(stamp))}</div>' if stamp else f'<div>{name}</div>'
        if (role == Qt.ItemDataRole.DecorationRole and index.isValid()
                and index.column() == 0 and hasattr(self, 'file_inks')):
            icon = file_icon(self.fileName(index), self.isDir(index), *self.file_inks)
            if not icon.isNull():
                return icon
        return super().data(index, role)


MAX_CLIPBOARD_BYTES = 512 * 1024
MAX_CLIPBOARD_URI = 4096


def local_path(url):
    if not url.isValid() or not url.isLocalFile() or url.authority().lower() not in ('', 'localhost'):
        return None
    url = QUrl(url)
    url.setHost('')
    value = url.toLocalFile()
    if not value or '\0' in value:
        return None
    path = Path(value)
    return path if path.is_absolute() else None


def local_paths(urls):
    return list(dict.fromkeys(path for url in urls if (path := local_path(url)) is not None))


def clipboard_transfer(mime):
    """A cut request must name the same local files in both advertised formats."""
    gnome = mime.data('x-special/gnome-copied-files')
    uri_data = mime.data('text/uri-list')
    if gnome.size() + uri_data.size() > MAX_CLIPBOARD_BYTES:
        raise ValueError('Clipboard file list is too large')

    def decode(lines):
        if len(lines) > MAX_SOURCES:
            raise ValueError(f'Transfer at most {MAX_SOURCES} items at a time')
        paths = []
        for line in lines:
            if not line or len(line) > MAX_CLIPBOARD_URI:
                raise ValueError('Clipboard contains an invalid file location')
            path = local_path(QUrl.fromEncoded(line, QUrl.ParsingMode.StrictMode))
            if path is None:
                raise ValueError('Clipboard must contain local files')
            paths.append(path)
        return list(dict.fromkeys(paths))

    uris = decode([line for line in bytes(uri_data).splitlines()
                   if line and not line.startswith(b'#')])
    lines = bytes(gnome).splitlines()
    if not lines:
        return uris, False
    if lines[0] not in (b'copy', b'cut') or len(lines) < 2:
        raise ValueError('Clipboard file list is invalid')
    advertised = decode(lines[1:])
    if lines[0] == b'cut' and uris and set(uris) != set(advertised):
        raise ValueError('Clipboard file lists disagree; cut the files again')
    return (advertised if lines[0] == b'cut' else uris or advertised), lines[0] == b'cut'


class FolderFilter(QSortFilterProxyModel):
    """Only filter the displayed folder; keep its ancestors and sort order."""
    folder = None
    query = ''

    def filterAcceptsRow(self, row, parent):
        source = self.sourceModel()
        if self.query and parent.isValid() and source.filePath(parent) == str(self.folder):
            return self.query in source.fileName(source.index(row, 0, parent)).casefold()
        return True

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        self.sourceModel().sort(column, order)

    def set_query(self, folder, query):
        self.folder = folder
        self.query = query.strip().casefold()
        self.invalidateFilter()


class FolderView(QTreeView):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.drop_rect = QRect()
        self.drag_scroll_direction = 0
        self.drag_scroll = QTimer(self)
        self.drag_scroll.setInterval(70)
        self.drag_scroll.timeout.connect(self.scroll_drag)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QTreeView.DragDropMode.DragDrop)

    def startDrag(self, _actions):
        paths = self.owner.selected()
        if not 1 <= len(paths) <= MAX_SOURCES:
            return
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
        drag = QDrag(self)
        drag.setMimeData(mime)
        index = self.currentIndex().sibling(self.currentIndex().row(), 0)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(icon, QIcon):
            drag.setPixmap(icon.pixmap(32, 32))
        # Transfer owns the move. A successful drop must never delete the
        # source from the view before the destination finishes copying it.
        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction, Qt.DropAction.CopyAction)

    def drop_details(self, event):
        paths = local_paths(event.mimeData().urls())
        monitor = getattr(QApplication.instance(), 'files_device_monitor', None)
        if self.owner.job is not None or not 1 <= len(paths) <= MAX_SOURCES:
            return None
        if monitor is not None and monitor.files_active_request is not None:
            return None
        index = self.indexAt(event.position().toPoint())
        source = self.owner.proxy.mapToSource(index)
        folder = self.owner.folder
        if source.isValid() and self.owner.model.isDir(source):
            folder = Path(self.owner.model.filePath(source))
        internal = isinstance(event.source(), FolderView)
        action = Qt.DropAction.MoveAction if internal and event.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier else Qt.DropAction.CopyAction
        if not event.possibleActions() & action:
            return None
        if internal and folder == self.owner.folder and all(path.parent == folder for path in paths):
            if action == Qt.DropAction.MoveAction or not event.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
                return None
        return paths, folder, action, index if folder != self.owner.folder else QModelIndex()

    def dragEnterEvent(self, event):
        if event.possibleActions() & Qt.DropAction.CopyAction and 1 <= len(local_paths(event.mimeData().urls())) <= MAX_SOURCES:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        details = self.drop_details(event)
        y = event.position().y()
        margin = self.autoScrollMargin()
        direction = -1 if y < margin else 1 if y >= self.viewport().height() - margin else 0
        bar = self.verticalScrollBar()
        self.drag_scroll_direction = direction
        if ((direction < 0 and bar.value() > bar.minimum()) or
                (direction > 0 and bar.value() < bar.maximum())):
            if not self.drag_scroll.isActive():
                self.drag_scroll.start()
        else:
            self.drag_scroll.stop()
        if details is None:
            self.drop_rect = QRect()
            event.ignore()
        else:
            _, _, action, index = details
            self.drop_rect = self.visualRect(index) if index.isValid() else self.viewport().rect()
            self.drop_rect.setLeft(0)
            self.drop_rect.setWidth(self.viewport().width())
            event.setDropAction(action)
            event.accept()
        self.viewport().update()

    def scroll_drag(self):
        bar = self.verticalScrollBar()
        old = bar.value()
        bar.setValue(old + self.drag_scroll_direction * max(1, bar.singleStep()))
        if old == bar.value():
            self.drag_scroll.stop()
        self.drop_rect = QRect()
        self.viewport().update()

    def dragLeaveEvent(self, event):
        self.drag_scroll.stop()
        self.drop_rect = QRect()
        self.viewport().update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self.drag_scroll.stop()
        details = self.drop_details(event)
        self.drop_rect = QRect()
        self.viewport().update()
        if details is None:
            event.ignore()
            return
        paths, folder, action, _ = details
        self.owner.transfer_paths(paths, folder, action == Qt.DropAction.MoveAction)
        event.setDropAction(action)
        event.accept()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.drop_rect.isEmpty():
            painter = QPainter(self.viewport())
            painter.setPen(self.palette().highlight().color())
            painter.drawRect(self.drop_rect.adjusted(0, 0, -1, -1))
            painter.end()


class FileActionsSheet(QWidget):
    """A scrollable action popup confined to its file window on every backend."""

    def __init__(self, parent, anchor, actions):
        super().__init__(parent)
        self.anchor, self.actions = anchor, actions
        self.panel = QFrame(self, objectName='fileActionsSheet')
        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(4, 4, 4, 4)
        self.scroll = QScrollArea(self.panel, widgetResizable=True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.body = QWidget(objectName='fileActionsBody')
        self.rows = QVBoxLayout(self.body)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(2)
        self.scroll.setWidget(self.body)
        layout.addWidget(self.scroll)
        self.buttons = []
        self.hide()

    def open(self):
        while self.rows.count():
            widget = self.rows.takeAt(0).widget()
            widget.hide()
            widget.deleteLater()
        self.buttons.clear()
        separator = False
        for action in self.actions:
            if action is None:
                separator = bool(self.buttons)
                continue
            if not action.isVisible():
                continue
            if separator:
                divider = QFrame(objectName='fileActionSeparator')
                divider.setFixedHeight(1)
                self.rows.addWidget(divider)
                separator = False
            button = QPushButton(action.icon(), action.text(), objectName='fileActionItem')
            shortcut = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
            if shortcut:
                button.setToolTip(f'{action.text()} ({shortcut})')
            button.setEnabled(action.isEnabled())
            button.setCheckable(action.isCheckable())
            if action.isCheckable():
                button.setChecked(action.isChecked())
            button.installEventFilter(self)
            button.clicked.connect(lambda _checked=False, action=action: self.trigger(action))
            self.rows.addWidget(button)
            self.buttons.append(button)
        self.place()
        self.show()
        self.raise_()
        self.scroll.verticalScrollBar().setValue(0)
        self.focus_row(0)

    def place(self):
        viewport = self.parentWidget()
        self.setGeometry(viewport.rect())
        self.rows.activate()
        anchor = self.anchor.mapTo(viewport, QPoint(self.anchor.width(), self.anchor.height()))
        width = max(1, min(viewport.width() - 16, max(240, self.rows.sizeHint().width() + 24)))
        top = max(0, min(anchor.y() + 4, viewport.height() - 72))
        height = max(1, min(viewport.height() - top - 8, self.rows.sizeHint().height() + 8))
        left = max(0, min(anchor.x() - width, viewport.width() - width - 8))
        self.panel.setGeometry(left, top, width, height)

    def focus_row(self, step, current=None):
        options = [row for row in self.buttons if row.isEnabled()]
        if options:
            index = (options.index(current) + step) % len(options) if current in options else 0
            button = options[index]
            button.setFocus()
            self.scroll.ensureWidgetVisible(button, 0, 2)

    def dismiss(self):
        self.hide()
        self.anchor.setFocus()

    def trigger(self, action):
        self.dismiss()
        if action.isEnabled():
            action.trigger()

    def mousePressEvent(self, event):
        if not self.panel.geometry().contains(event.position().toPoint()):
            self.dismiss()
        event.accept()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.dismiss()
                return True
            if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                forward = event.key() == Qt.Key.Key_Down or (
                    event.key() == Qt.Key.Key_Tab
                    and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
                self.focus_row(1 if forward else -1, watched)
                return True
        return super().eventFilter(watched, event)


class Files(QMainWindow):
    def __init__(self, initial):
        super().__init__()
        # Headless Qt and some Wayland setups expose only the resource search path.
        system_icons = '/usr/share/icons'
        search_paths = QIcon.themeSearchPaths()
        if system_icons not in search_paths:
            QIcon.setThemeSearchPaths([*search_paths, system_icons])
        if not QIcon.fallbackThemeName():
            QIcon.setFallbackThemeName('Adwaita')
        if not QIcon.themeName():
            QIcon.setThemeName('Adwaita')
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(800, 565)
        self.history = []
        self.position = -1
        self.job = None
        self.storage_dialog = None
        self.close_when_idle = False
        self.model = FolderModel(self)
        self.model.setReadOnly(True)
        self.model.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot | QDir.Filter.AllDirs)
        self.proxy = FolderFilter(self)
        self.proxy.setSourceModel(self.model)
        self.view = FolderView(self)
        self.view.setModel(self.proxy)
        self.search_selection = []
        self.filtering = False
        self.view.selectionModel().selectionChanged.connect(self.search_selection_changed)
        self.view.setRootIsDecorated(False)
        self.view.setItemsExpandable(False)
        self.view.setUniformRowHeights(True)
        self.view.setSelectionMode(QTreeView.SelectionMode.ExtendedSelection)
        self.view.setSortingEnabled(True)
        self.view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.view.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.view.header().setStretchLastSection(False)
        for column in (1, 2, 3):
            self.view.header().setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
        self.view.viewport().installEventFilter(self)
        self.view.doubleClicked.connect(self.open_index)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self.context_menu)
        self.location = QLineEdit()
        self.location.setAccessibleName('Folder location')
        self.location.returnPressed.connect(self.submit_location)
        self.location.installEventFilter(self)
        self.address = QStackedWidget()
        # Ancestor buttons must not set a minimum width for the whole window.
        from PyQt6.QtWidgets import QSizePolicy
        self.address.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.address.setMinimumWidth(104)
        self.breadcrumb_timer = QTimer(self)
        self.breadcrumb_timer.setSingleShot(True)
        self.breadcrumb_timer.timeout.connect(self.update_breadcrumbs)
        self.address.installEventFilter(self)
        self.breadcrumbs = QWidget()
        self.breadcrumbs.setObjectName('breadcrumbs')
        self.crumb_layout = QHBoxLayout(self.breadcrumbs)
        self.crumb_layout.setContentsMargins(4, 0, 4, 0)
        self.crumb_layout.setSpacing(3)
        self.address.addWidget(self.breadcrumbs)
        self.address.addWidget(self.location)
        self.back = self.button('‹', lambda: self.step(-1))
        self.back.setIcon(QIcon.fromTheme('go-previous-symbolic', QIcon.fromTheme('go-previous')))
        self.back.setProperty('symbolicIcon', 'go-previous')
        if not self.back.icon().isNull():
            self.back.setText('')
        self.back.setAccessibleName('Back')
        self.back.setToolTip('Back')
        self.forward = self.button('›', lambda: self.step(1))
        self.forward.setIcon(QIcon.fromTheme('go-next-symbolic', QIcon.fromTheme('go-next')))
        self.forward.setProperty('symbolicIcon', 'go-next')
        if not self.forward.icon().isNull():
            self.forward.setText('')
        self.forward.setAccessibleName('Forward')
        self.forward.setToolTip('Forward')
        up = self.button('↑', lambda: self.navigate(self.folder.parent))
        up.setIcon(QIcon.fromTheme('go-up-symbolic', QIcon.fromTheme('go-up')))
        up.setProperty('symbolicIcon', 'go-up')
        if not up.icon().isNull():
            up.setText('')
        up.setAccessibleName('Parent folder')
        up.setToolTip('Parent folder')
        top = QHBoxLayout()
        top.setSpacing(4)
        self.identity_badge = AppIdentityBadge(self)
        top.addWidget(self.identity_badge)
        for widget in (self.back, self.forward, up):
            widget.setObjectName('navigation')
            top.addWidget(widget)
        top.addWidget(self.address, 1)
        edit_location = self.button('Path', self.edit_location)
        edit_location.setIcon(QIcon.fromTheme('document-edit-symbolic', QIcon.fromTheme('document-edit')))
        edit_location.setProperty('symbolicIcon', 'document-edit')
        edit_location.setObjectName('navigation')
        edit_location.setAccessibleName('Edit location')
        if not edit_location.icon().isNull():
            edit_location.setText('')
        edit_location.setToolTip('Edit location (Ctrl+L)')
        top.addWidget(edit_location)
        find = self.button('Find', self.show_search)
        find.setProperty('symbolicIcon', 'edit-find')
        find.setObjectName('navigation')
        find.setAccessibleName('Find in this folder')
        find.setToolTip('Find in this folder (Ctrl+F)')
        top.addWidget(find)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Find in this folder')
        self.search.setAccessibleName('Find in this folder')
        self.search.setClearButtonEnabled(True)
        self.search.installEventFilter(self)
        self.search.textChanged.connect(self.filter_folder)
        self.search.returnPressed.connect(self.focus_results)
        self.search.hide()
        self.sidebar = QVBoxLayout()
        self.places = {}
        self.bookmark_settings = QSettings('Mellipi', 'Files')
        self.add_place('Home', Path.home())
        from gi.repository import GLib
        for key, label in ((GLib.UserDirectory.DIRECTORY_DESKTOP, 'Desktop'),
                           (GLib.UserDirectory.DIRECTORY_DOCUMENTS, 'Documents'),
                           (GLib.UserDirectory.DIRECTORY_DOWNLOAD, 'Downloads'),
                           (GLib.UserDirectory.DIRECTORY_PICTURES, 'Pictures')):
            path = GLib.get_user_special_dir(key)
            if path and Path(path).is_dir() and Path(path) != Path.home():
                self.add_place(label, Path(path))
        self.add_place('File system', Path('/'))
        trash = self.button('Trash', self.show_trash)
        trash.setObjectName('place')
        trash.setProperty('symbolicIcon', 'user-trash')
        self.sidebar.addWidget(trash)
        self.bookmark_menu = QMenu(self)
        self.bookmark_menu.aboutToShow.connect(self.render_bookmarks)
        bookmarks = QPushButton('Bookmarks')
        bookmarks.setObjectName('place')
        bookmarks.setProperty('symbolicIcon', 'bookmark')
        bookmarks.setMenu(self.bookmark_menu)
        self.sidebar.addWidget(bookmarks)
        self.device_menu = QMenu(self)
        self.device_menu.aboutToShow.connect(self.show_devices)
        self.device_monitor = None
        self.devices = None
        self.device_error = ''
        self.pending_mount = ''
        self.pending_detach = None
        devices = QPushButton('Devices')
        devices.setObjectName('place')
        devices.setProperty('symbolicIcon', 'drive-removable-media')
        devices.setToolTip('Mount, open, or safely remove a drive')
        devices.setMenu(self.device_menu)
        self.sidebar.addWidget(devices)
        self.sidebar.addStretch()
        body = QHBoxLayout()
        self.places_panel = QWidget()
        self.places_panel.setObjectName('places')
        self.places_panel.setLayout(self.sidebar)
        self.sidebar.setSpacing(2)
        body.setSpacing(0)
        body.addWidget(self.places_panel)
        divider = QFrame()
        divider.setObjectName('divider')
        divider.setFixedWidth(1)
        body.addWidget(divider)
        body.addWidget(self.view, 1)
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 0, 8, 8)
        layout.setSpacing(0)
        self.titlebar = TitleBar(self, top)
        layout.addWidget(self.titlebar)
        rule = QFrame()
        rule.setObjectName('divider')
        rule.setFixedHeight(1)
        layout.addWidget(rule)
        self.content_layout = QVBoxLayout()
        self.content_layout.addWidget(self.search)
        self.content_layout.addLayout(body, 1)
        layout.addLayout(self.content_layout, 1)
        self.transfer_strip = TransferStrip(self)
        layout.addWidget(self.transfer_strip)
        self.setCentralWidget(central)
        central.setMouseTracking(True)
        central.installEventFilter(self)
        self.statusBar().setSizeGripEnabled(True)
        self.item_count = QLabel()
        self.item_count.setObjectName('itemCount')
        self.statusBar().addPermanentWidget(self.item_count)
        self.proxy.rowsInserted.connect(self.update_count)
        self.proxy.rowsRemoved.connect(self.update_count)
        self.model.directoryLoaded.connect(self.update_count)
        self.actions = []
        for label, icon, shortcut, callback in (
            ('Open', 'document-open', 'Return', lambda: self.open_index(self.view.currentIndex())),
            ('New folder', 'folder-new', 'Ctrl+Shift+N', self.new_folder),
            ('Copy', 'edit-copy', 'Ctrl+C', lambda: self.copy(False)),
            ('Cut', 'edit-cut', 'Ctrl+X', lambda: self.copy(True)),
            ('Paste', 'edit-paste', 'Ctrl+V', self.paste),
            ('Rename', 'document-edit', 'F2', self.rename),
            ('Move to Trash', 'user-trash', 'Delete', self.trash),
            ('Show or hide hidden files', 'view-reveal', 'Ctrl+H', self.toggle_hidden),
        ):
            action = QAction(QIcon.fromTheme(icon + '-symbolic', QIcon.fromTheme(icon)), label, self.view)
            action.setIconVisibleInMenu(True)
            action.setProperty('symbolicIcon', icon)
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            action.triggered.connect(callback)
            self.view.addAction(action)
            self.actions.append(action)
        self.archive_actions = []
        for label, icon, callback in (
            ('Preview Archive', 'package-x-generic', self.preview_selection),
            ('Extract Here', 'folder-download', self.extract_selection),
            ('Compress…', 'package-x-generic', self.compress_selection),
        ):
            action = QAction(QIcon.fromTheme(icon + '-symbolic', QIcon.fromTheme(icon)), label, self.view)
            action.setIconVisibleInMenu(True)
            action.setProperty('symbolicIcon', icon)
            action.triggered.connect(callback)
            self.archive_actions.append(action)
        bookmark = QAction('Bookmark this folder', self)
        bookmark.setProperty('symbolicIcon', 'bookmark')
        bookmark.setIconVisibleInMenu(True)
        bookmark.setShortcut(QKeySequence('Ctrl+D'))
        bookmark.triggered.connect(lambda: self.add_bookmark(self.folder))
        self.addAction(bookmark)
        storage = self.storage_action('Analyze Storage…', self.analyze_current_folder)
        menu_icon = QIcon.fromTheme('open-menu-symbolic', QIcon.fromTheme('open-menu'))
        actions_button = QPushButton(menu_icon, '⋯' if menu_icon.isNull() else '')
        actions_button.setObjectName('navigation')
        actions_button.setProperty('symbolicIcon', 'open-menu')
        actions_button.setAccessibleName('File actions')
        actions_button.setToolTip('File actions')
        self.action_sheet = FileActionsSheet(central, actions_button,
            [*self.actions, None, *self.archive_actions, None, bookmark, storage])
        actions_button.clicked.connect(self.open_file_actions)
        top.addWidget(actions_button)
        for shortcut, callback in (('Ctrl+L', self.edit_location), ('Ctrl+F', self.show_search)):
            action = QAction(self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            self.addAction(action)
        self.theme_watch = ThemeWatch(self)
        self.theme_watch.changed.connect(self.apply_theme)
        self.apply_theme()
        if not self.navigate(initial):
            self.navigate(Path.home())

    def update_count(self, *_):
        count = self.proxy.rowCount(self.view.rootIndex())
        noun = 'match' if self.proxy.query else 'item'
        self.item_count.setText(f'{count} {noun}' + ('' if count == 1 else 'es' if noun == 'match' else 's'))

    def open_file_actions(self):
        self.archive_selection_changed()
        self.action_sheet.open()

    def show_search(self):
        self.search.show()
        self.search.setFocus()
        self.search.selectAll()

    def focus_results(self):
        if not self.view.currentIndex().isValid():
            self.view.setCurrentIndex(self.proxy.index(0, 0, self.view.rootIndex()))
        self.view.setFocus()

    def search_selection_changed(self, *_):
        if self.proxy.query and not self.filtering:
            self.search_selection = []

    def filter_folder(self, query):
        if not hasattr(self, 'folder'):
            return
        previous = self.proxy.query
        if not previous and query.strip():
            self.search_selection = self.selected()
        self.filtering = True
        try:
            root = self.proxy.mapToSource(self.view.rootIndex())
            self.proxy.set_query(self.model.filePath(root), query)
            if previous and not self.proxy.query and self.search_selection:
                selection = self.view.selectionModel()
                for path in self.search_selection:
                    index = self.proxy.mapFromSource(self.model.index(str(path)))
                    if index.isValid():
                        selection.select(index, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
                self.search_selection = []
        finally:
            self.filtering = False
        self.update_count()

    def edit_location(self):
        self.address.setCurrentWidget(self.location)
        self.location.setFocus()
        self.location.selectAll()

    def submit_location(self):
        if self.navigate(Path(self.location.text()).expanduser()):
            self.address.setCurrentWidget(self.breadcrumbs)
            self.view.setFocus()

    def update_breadcrumbs(self):
        while self.crumb_layout.count():
            item = self.crumb_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        home = Path.home()
        base = home if self.folder.is_relative_to(home) else Path('/')
        paths = [self.folder]
        while paths[-1] != base:
            paths.append(paths[-1].parent)
        current_font = self.breadcrumbs.font()
        current_font.setPixelSize(self.theme_watch.tokens['font_size'])
        metrics = QFontMetrics(current_font)
        current_font.setWeight(current_font.Weight.DemiBold)
        current_metrics = QFontMetrics(current_font)
        budget = max(40, self.address.width() - 8)
        separator_width = metrics.horizontalAdvance('›') + 6
        overflow_icon_size = 16
        overflow_button_width = 26
        overflow_width = overflow_button_width + separator_width

        def label_width(path):
            label = 'Home' if path == home else path.name or '/'
            font_metrics = current_metrics if path == self.folder else metrics
            return font_metrics.horizontalAdvance(label) + 14

        # Keep the current folder before making room for nearby ancestors.
        # Anything that doesn't fit remains reachable through the overflow menu.
        # At minimum width, the existing Up action is more useful than two
        # ellipses. Reserve space for a readable fragment of the current name.
        readable = min(label_width(paths[0]), current_metrics.horizontalAdvance('MMMM…') + 9)
        collapse_ancestors = len(paths) > 1 and budget - overflow_width < readable
        reserve = overflow_width if len(paths) > 1 and not collapse_ancestors else 0
        current_width = min(label_width(paths[0]), max(28, budget - reserve))
        used = current_width
        count = 1
        for path in ([] if collapse_ancestors else paths[1:4]):
            required = used + separator_width + label_width(path)
            reserve = overflow_width if count + 1 < len(paths) else 0
            if required + reserve > budget:
                break
            used = required
            count += 1
        visible = list(reversed(paths[:count]))
        if len(paths) > count and not collapse_ancestors:
            more = QPushButton(phosphor_icon('regular', 'dots-three', self.theme_watch.tokens['text']), '')
            more.setObjectName('crumbOverflow')
            more.setAccessibleName('Show parent folders')
            more.setToolTip('Show parent folders')
            more.setIconSize(QSize(overflow_icon_size, overflow_icon_size))
            more.setFixedWidth(overflow_button_width)
            menu = QMenu(more)
            for path in reversed(paths[count:]):
                action = menu.addAction('Home' if path == home else path.name or '/')
                action.triggered.connect(lambda checked=False, target=path: self.navigate(target))
            more.setMenu(menu)
            self.crumb_layout.addWidget(more)
            more.show()
        for path in visible:
            if self.crumb_layout.count():
                separator = QLabel('›')
                separator.setObjectName('crumbSeparator')
                self.crumb_layout.addWidget(separator)
                separator.show()
            title = 'Home' if path == home else path.name or '/'
            is_current = path == self.folder
            width = current_width if is_current else label_width(path)
            display = title
            if is_current and label_width(path) > width:
                display = current_metrics.elidedText(title, Qt.TextElideMode.ElideRight, max(12, width - 9))
            button = self.button(display.replace('&', '&&'), lambda checked=False, target=path: self.navigate(target))
            button.setAccessibleName(title)
            button.setFixedWidth(width)
            button.setObjectName('currentCrumb' if path == self.folder else 'crumb')
            button.setToolTip(str(path))
            self.crumb_layout.addWidget(button)
            button.show()
        self.crumb_layout.addStretch()

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.Resize and watched is self.centralWidget()
                and hasattr(self, 'action_sheet') and self.action_sheet.isVisible()):
            self.action_sheet.place()
        if (event.type() == QEvent.Type.Resize and hasattr(self, 'theme_watch')
                and watched is self.view.viewport()):
            self.update_list_columns()
        if watched is getattr(self, 'address', None) and event.type() == QEvent.Type.Resize and hasattr(self, 'folder'):
            self.breadcrumb_timer.start(0)
        if event.type() == QEvent.Type.KeyPress and watched is getattr(self, 'search', None):
            if event.key() == Qt.Key.Key_Escape:
                self.search.clear()
                self.search.hide()
                self.view.setFocus()
                return True
            if event.key() == Qt.Key.Key_Down:
                self.focus_results()
                return True
        if watched is self.location and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.location.setText(str(self.folder))
            self.address.setCurrentWidget(self.breadcrumbs)
            self.view.setFocus()
            return True
        if watched is self.centralWidget() and event.type() in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress):
            edges = Qt.Edge(0)
            point = event.position().toPoint()
            if not self.isMaximized():
                if point.x() < 6:
                    edges |= Qt.Edge.LeftEdge
                elif point.x() >= watched.width() - 6:
                    edges |= Qt.Edge.RightEdge
                if point.y() < 6:
                    edges |= Qt.Edge.TopEdge
                elif point.y() >= watched.height() - 6:
                    edges |= Qt.Edge.BottomEdge
            if event.type() == QEvent.Type.MouseButtonPress and edges and event.button() == Qt.MouseButton.LeftButton:
                return self.windowHandle().startSystemResize(edges)
            if event.type() == QEvent.Type.MouseMove:
                horizontal = bool(edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))
                vertical = bool(edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge))
                if horizontal and vertical:
                    diagonal = bool(edges & Qt.Edge.LeftEdge) == bool(edges & Qt.Edge.TopEdge)
                    watched.setCursor(Qt.CursorShape.SizeFDiagCursor if diagonal else Qt.CursorShape.SizeBDiagCursor)
                elif horizontal or vertical:
                    watched.setCursor(Qt.CursorShape.SizeHorCursor if horizontal else Qt.CursorShape.SizeVerCursor)
                else:
                    watched.unsetCursor()
        return super().eventFilter(watched, event)

    def add_place(self, label, path):
        button = self.button(label, lambda: self.navigate(path))
        icon = {'Home': 'user-home', 'Desktop': 'user-desktop', 'Documents': 'folder-documents',
                'Downloads': 'folder-download', 'Pictures': 'folder-pictures',
                'File system': 'drive-harddisk'}.get(label, 'folder')
        button.setProperty('symbolicIcon', icon)
        button.setObjectName('place')
        button.setCheckable(True)
        self.places[path] = button
        self.sidebar.addWidget(button)

    def read_bookmarks(self):
        self.bookmark_settings.sync()
        saved = self.bookmark_settings.value('bookmarks', {})
        if not isinstance(saved, dict):
            return {}
        return {path: label for path, label in saved.items()
                if isinstance(path, str) and Path(path).is_absolute()
                and isinstance(label, str) and label.strip()}

    def write_bookmarks(self, rows):
        self.bookmark_settings.setValue('bookmarks', rows)
        self.bookmark_settings.sync()
        return self.bookmark_settings.status() == QSettings.Status.NoError

    def add_bookmark(self, path):
        path = Path(path)
        if not path.is_dir():
            self.statusBar().showMessage('Folder is unavailable', 5000)
            return
        rows = self.read_bookmarks()
        key = str(path.absolute())
        if key in rows:
            self.statusBar().showMessage('Folder is already bookmarked', 3500)
        elif len(rows) >= 32:
            self.statusBar().showMessage('Remove a bookmark before adding another', 5000)
        else:
            rows[key] = path.name or '/'
            self.statusBar().showMessage('Folder bookmarked' if self.write_bookmarks(rows)
                                         else 'Could not save bookmarks', 3500)

    def change_bookmark(self, path, label=None):
        rows = self.read_bookmarks()
        if path not in rows:
            return
        if label is None:
            del rows[path]
        else:
            rows[path] = label
        if not self.write_bookmarks(rows):
            self.statusBar().showMessage('Could not save bookmarks', 5000)

    def rename_bookmark(self, path, label):
        new_label, accepted = ThemedInput.getText(self, 'Rename bookmark', 'Name', text=label)
        if accepted and new_label.strip():
            self.change_bookmark(path, new_label.strip()[:80])

    def render_bookmarks(self):
        menu = self.bookmark_menu
        # QMenu.clear() removes the actions, but does not own its explicit submenus.
        for submenu in menu.findChildren(QMenu, options=Qt.FindChildOption.FindDirectChildrenOnly):
            submenu.deleteLater()
        menu.clear()
        menu.addAction('Bookmark this folder', lambda: self.add_bookmark(self.folder))
        rows = self.read_bookmarks()
        if not rows:
            return
        menu.addSeparator()
        counts = Counter(rows.values())
        organize = QMenu('Organize bookmarks', menu)
        for path, label in sorted(rows.items(), key=lambda row: (row[1].casefold(), row[0])):
            title = label if counts[label] == 1 else f'{label} — {Path(path).parent}'
            title = title.replace('&', '&&')
            action = menu.addAction(title)
            action.setStatusTip(path)
            action.triggered.connect(lambda _checked=False, selected=Path(path): self.navigate(selected))
            submenu = organize.addMenu(title)
            submenu.addAction('Rename bookmark…').triggered.connect(
                lambda _checked=False, key=path, name=label: self.rename_bookmark(key, name))
            submenu.addAction('Remove bookmark').triggered.connect(
                lambda _checked=False, key=path: self.change_bookmark(key))
        menu.addSeparator()
        menu.addMenu(organize)

    def show_devices(self):
        if self.device_monitor is not None:
            if self.device_monitor.thread is None:
                self.devices = None
                self.device_error = ''
                self.device_monitor.start()
            self.render_devices()
            return
        self.render_devices()
        app = QApplication.instance()
        monitor = getattr(app, 'files_device_monitor', None)
        if monitor is None:
            monitor = DeviceMonitor(app)
            monitor.files_active_request = None
            app.files_device_monitor = monitor
            app.aboutToQuit.connect(monitor.stop)
        self.device_monitor = monitor
        monitor.result.connect(self.update_devices)
        if monitor.thread is None:
            monitor.start()
        else:
            monitor.submit(lambda _gio: monitor.refresh())

    def update_devices(self, result):
        if 'devices' in result:
            self.devices = result['devices']
            self.device_error = ''
            if self.pending_mount:
                for row in self.devices:
                    if row['id'] == self.pending_mount and row['mounted']:
                        self.pending_mount = ''
                        self.open_device(row['uri'])
                        break
        monitor = self.device_monitor
        own_request = monitor.files_active_request == id(self)
        if own_request and (result.get('operationDone') or result.get('error')):
            monitor.files_active_request = None
            if not result.get('error') and self.pending_detach:
                if self.folder.is_relative_to(self.pending_detach):
                    self.navigate(Path.home())
                self.statusBar().showMessage('Drive removed', 5000)
            self.pending_detach = None
        if result.get('error') and (own_request or not result.get('monitorAvailable', True)):
            self.pending_mount = ''
            self.device_error = result['error'].removesuffix('. Open Files if a password is required.')
            self.statusBar().showMessage(self.device_error, 8000)
        if self.device_menu.isVisible() and ('devices' in result or result.get('error')):
            self.render_devices()
        if own_request and (result.get('operationDone') or result.get('error')):
            self.finish_deferred_close(result.get('error'))

    def render_devices(self):
        submenus = [action.menu() for action in self.device_menu.actions() if action.menu()]
        self.device_menu.clear()
        for submenu in submenus:
            submenu.deleteLater()
        for row in self.devices or ():
            uri = QUrl(row['uri'])
            local = uri.isLocalFile() and Path(uri.toLocalFile()).is_absolute()
            if row['mounted'] and local and (row['canUnmount'] or row['canEject']):
                menu = self.device_menu.addMenu(row['name'])
                menu.addAction('Open', lambda checked=False, uri=row['uri']: self.open_device(uri))
                action = 'eject' if row['canEject'] else 'unmount'
                label = 'Eject' if action == 'eject' else 'Unmount'
                menu.addAction(label, lambda checked=False, ident=row['id'], kind=action: self.device_action(ident, kind))
            elif not row['mounted'] and row['canMount']:
                self.device_menu.addAction('Mount ' + row['name'],
                                           lambda checked=False, ident=row['id']: self.device_action(ident, 'mount'))
        if not self.device_menu.actions():
            label = self.device_error or ('Loading devices…' if self.devices is None else 'No drives available')
            self.device_menu.addAction(label).setEnabled(False)

    def open_device(self, uri):
        url = QUrl(uri)
        if url.isLocalFile() and Path(url.toLocalFile()).is_absolute():
            self.navigate(Path(url.toLocalFile()))
        else:
            self.statusBar().showMessage('Only local drives can be opened here', 5000)

    def device_action(self, ident, action):
        monitor = self.device_monitor
        windows = QApplication.topLevelWidgets()
        if monitor.files_active_request is not None or any(
                isinstance(window, Files) and window.job is not None for window in windows):
            self.statusBar().showMessage('Wait for the current operation to finish', 5000)
            return
        monitor.files_active_request = id(self)
        self.device_error = ''
        if action == 'mount':
            self.pending_mount = ident
        else:
            uri = next((row['uri'] for row in self.devices or () if row['id'] == ident), '')
            path = QUrl(uri).toLocalFile()
            self.pending_detach = Path(path) if path else None
        self.statusBar().showMessage({'mount': 'Mounting…', 'unmount': 'Unmounting…', 'eject': 'Ejecting…'}[action], 5000)
        monitor.action(ident, action)

    @staticmethod
    def button(label, callback):
        button = QPushButton(label)
        button.clicked.connect(callback)
        return button

    def apply_theme(self):
        palette = self.theme_watch.tokens
        preferences = self.theme_watch.preferences
        app = QApplication.instance()
        app.setPalette(widget_palette(palette))
        ink = palette['text']
        self.identity_badge.theme('Mellipi Files', palette)
        for control in [*self.findChildren(QAction), *self.findChildren(QPushButton)]:
            name = control.property('symbolicIcon')
            if not name:
                continue
            if (control.objectName() == 'place' or name == 'drive-harddisk') and name in PLACES:
                icon = place_icon(name, palette)
            else:
                icon = phosphor_icon('regular', ACTIONS.get(name, ''), ink)
            if icon.isNull():
                icon = original_icon(name, ink)
            if icon.isNull():
                continue
            control.setIcon(icon)
            if isinstance(control, QPushButton) and control.objectName() == 'navigation':
                control.setText('')
        apply_titlebar(self.titlebar, palette)
        self.model.file_inks = palette['accent_ink'], palette['accent'], palette['text']
        self.view.viewport().update()
        density = preferences.values['density']
        for button in self.titlebar.findChildren(QPushButton):
            button.setIconSize(QSize(16, 16))
            button.setMinimumHeight(30)
            if button.objectName() == 'navigation':
                button.setFixedWidth(32 if button.menu() is None else 36)
        padding = palette['padding']
        sidebar_width = {'comfortable': 148, 'compact': 132, 'extra': 116}[density]
        text_scale = preferences.values['textScale']
        self.sidebar.setContentsMargins(padding, padding, padding, padding)
        self.content_layout.setContentsMargins(0, padding, 0, 0)
        self.content_layout.setSpacing(padding)
        radius = {'square': 0, 'soft': 4, 'rounded': 8}[preferences.values['corners']]
        self.setStyleSheet('''
            QMainWindow, QStatusBar { background: %(background)s; color: %(text)s; }
            QTreeView, QMenu { background: %(surface)s; color: %(text)s; }
            QLineEdit { background: %(surface)s; }
            QPushButton, QHeaderView::section { background: %(surface)s; color: %(text)s; }
            QFrame#divider { background: %(separator)s; }
            QWidget#places { background: %(raised)s; border-radius: %(radius)spx; }
            QLabel#crumbSeparator { color: %(muted)s; }
            QLabel#itemCount { color: %(muted)s; padding-right: 4px; }
            QMenu { border: 1px solid %(border)s; padding: 3px; }
            QMenu::item { padding: %(padding)spx 20px %(padding)spx 8px; }
            QWidget#breadcrumbs { background: %(surface)s;
                border-radius: %(radius)spx; }
            QPushButton#navigation, QPushButton#crumb, QPushButton#crumbOverflow, QPushButton#currentCrumb {
                border: 0; border-bottom: 2px solid transparent; padding: 3px 5px; background: transparent; }
            QPushButton#crumbOverflow { padding: 2px; }
            QPushButton#crumbOverflow::menu-indicator { image: none; width: 0; }
            QPushButton#crumb { color: %(muted)s; }
            QPushButton#currentCrumb { font-weight: 600; padding-left: 3px; padding-right: 3px; text-align: left; }
            QFrame#fileActionsSheet, QWidget#fileActionsBody { background: %(surface)s; }
            QFrame#fileActionsSheet { border: 1px solid %(control_border)s; border-radius: %(radius)spx; }
            QFrame#fileActionSeparator { background: %(separator)s; }
            QPushButton#fileActionItem { text-align: left; padding: %(padding)spx 8px; }
            QPushButton#fileActionItem:hover, QPushButton#fileActionItem:focus { background: %(selected_surface)s; }
            QPushButton#fileActionItem:checked { border-left: 2px solid %(focus)s; }
            QPushButton#navigation:hover:enabled, QPushButton#crumb:hover, QPushButton#currentCrumb:hover { background: %(hover)s; }
            QPushButton#navigation:focus, QPushButton#crumb:focus, QPushButton#currentCrumb:focus, QPushButton#windowControl:focus { border-bottom: 2px solid %(focus)s; }
            QPushButton#windowControl { background: transparent; border: 0; padding: 2px; }
            QPushButton#windowControl:hover { background: %(hover)s; }
            QPushButton#place { text-align: left; border: 0; border-radius: %(radius)spx;
                border-left: 2px solid transparent; background: transparent; color: %(muted)s; }
            QPushButton#place:hover { background: %(hover)s; color: %(text)s; }
            QPushButton#place:checked { background: %(selected_surface)s; color: %(text)s;
                border-left: 2px solid %(focus)s; }
            QPushButton#place:focus { border-bottom: 1px solid %(focus)s; }
            QTreeView { border: %(outline_width)dpx solid %(control_border)s; border-radius: %(radius)spx; }
            QHeaderView::section { padding: 5px; border: 0; border-bottom: 1px solid %(separator)s; }
            QPushButton { border: 0; border-radius: %(radius)spx; padding: %(padding)spx; }
            QLineEdit { border: 1px solid %(control_border)s; border-radius: %(radius)spx; padding: %(padding)spx; }
            QPushButton:hover { background: %(hover)s; }
            QPushButton:disabled { color: %(muted)s; }
            QPushButton:focus, QLineEdit:focus, QTreeView:focus { border: 1px solid %(focus)s; }
            QTreeView::item { padding: %(padding)spx 4px; }
            QTreeView::item:selected, QMenu::item:selected { background: %(selected_surface)s; color: %(text)s; }
        ''' % dict(palette, padding=padding, radius=radius))
        font = app.font()
        font.setPixelSize(palette['font_size'])
        app.setFont(font)
        self.view.setIconSize(QSize(20, 20))
        for button in self.places_panel.findChildren(QPushButton):
            button.setIconSize(QSize(20, 20))
            button.setMinimumHeight(max(28, palette['font_size'] + 8))
        if hasattr(self, 'folder'):
            self.breadcrumb_timer.start(0)
        self.places_panel.setFixedWidth(max(round(sidebar_width * max(1, text_scale)), self.sidebar.minimumSize().width()))
        self.update_list_columns()

    def update_list_columns(self):
        header = self.view.header()
        metrics = header.fontMetrics()
        date = QLocale().toString(QDateTime.currentDateTime(), QLocale.FormatType.ShortFormat)
        sizes = {column: max(metrics.horizontalAdvance(value),
                             metrics.horizontalAdvance(str(self.model.headerData(column, Qt.Orientation.Horizontal)))) + 22
                 for column, value in ((1, '999.9 GiB'), (2, 'Plain Text'), (3, date))}
        reserve_name = metrics.horizontalAdvance('Document name') + 32
        available = self.view.viewport().width() - reserve_name
        for column in (1, 2, 3):
            visible = available >= sizes[column]
            if self.view.isColumnHidden(column) == visible:
                self.view.setColumnHidden(column, not visible)
            if visible:
                available -= sizes[column]
                current = header.sectionSize(column)
                if current != sizes[column]:
                    header.resizeSection(column, sizes[column])

    def navigate(self, folder, record=True):
        folder = (self.folder / folder if hasattr(self, 'folder') else folder).absolute()
        if not folder.is_dir():
            self.statusBar().showMessage('Folder is unavailable', 5000)
            return False
        if record and (self.position < 0 or self.history[self.position] != folder):
            self.history[self.position + 1:] = [folder]
            self.position += 1
        if getattr(self, 'folder', None) != folder:
            self.search_selection = []
            with QSignalBlocker(self.search):
                self.search.clear()
            self.search.hide()
            self.proxy.set_query(folder, '')
        self.folder = folder
        self.view.setRootIndex(self.proxy.mapFromSource(self.model.setRootPath(str(folder))))
        self.update_count()
        self.location.setText(str(folder))
        self.update_breadcrumbs()
        label = 'Home' if folder == Path.home() else folder.name or '/'
        self.setWindowTitle(f'{label} — Mellipi Files')
        for path, button in self.places.items():
            button.setChecked(path == folder)
        self.back.setEnabled(self.position > 0)
        self.forward.setEnabled(self.position + 1 < len(self.history))
        return True

    def step(self, delta):
        position = self.position + delta
        if 0 <= position < len(self.history):
            previous = self.position
            self.position = position
            if not self.navigate(self.history[position], record=False):
                self.position = previous

    def open_index(self, index):
        if not index.isValid():
            return
        path = Path(self.model.filePath(self.proxy.mapToSource(index)))
        if path.is_dir():
            self.navigate(path)
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.statusBar().showMessage('Could not open this file', 5000)

    def selected(self):
        return [Path(self.model.filePath(self.proxy.mapToSource(index)))
                for index in self.view.selectionModel().selectedRows()]

    def storage_action(self, label, callback, parent=None):
        action = QAction(label, parent or self)
        if hasattr(self, 'theme_watch'):
            action.setIcon(place_icon('drive-harddisk', self.theme_watch.tokens))
        action.setProperty('symbolicIcon', 'drive-harddisk')
        action.setIconVisibleInMenu(True)
        action.triggered.connect(callback)
        return action

    def analyze_current_folder(self):
        self.show_storage(self.folder)

    def show_storage(self, folder):
        if self.storage_dialog is not None:
            self.storage_dialog.raise_()
            self.storage_dialog.activateWindow()
            return
        self.storage_dialog = StorageDialog(self, folder)
        self.storage_dialog.destroyed.connect(lambda: setattr(self, 'storage_dialog', None))
        self.storage_dialog.show()

    def context_menu(self, point):
        index = self.view.indexAt(point)
        if index.isValid() and not self.view.selectionModel().isRowSelected(index.row(), index.parent()):
            self.view.setCurrentIndex(index)
        menu = QMenu(self)
        if index.isValid():
            menu.addActions(self.actions)
            self.archive_selection_changed()
            menu.addSeparator()
            menu.addActions(self.archive_actions)
            paths = self.selected()
            if len(paths) == 1 and not paths[0].is_symlink() and paths[0].is_dir():
                path = paths[0]
                menu.addAction(self.storage_action('Analyze Folder Storage…',
                                                  lambda: self.show_storage(path), menu))
                menu.addAction('Bookmark folder', lambda: self.add_bookmark(path))
        else:
            for action in self.actions:
                if action.text() in ('New folder', 'Paste', 'Show or hide hidden files'):
                    menu.addAction(action)
            menu.addAction(self.storage_action('Analyze Storage…', self.analyze_current_folder, menu))
        menu.exec(self.view.viewport().mapToGlobal(point))
        menu.deleteLater()

    def archive_selection_changed(self):
        paths = self.selected()
        archive = len(paths) == 1 and paths[0].is_file() and not paths[0].is_symlink() and bool(archive_suffix(paths[0]))
        for action in self.archive_actions[:2]:
            action.setVisible(archive)
        self.archive_actions[-1].setEnabled(bool(paths))

    def preview_selection(self):
        paths = self.selected()
        if len(paths) != 1:
            return
        path = paths[0]
        self.run_job(lambda: preview_archive(path), lambda preview: self.show_archive_preview(path.name, preview))

    def show_archive_preview(self, title, preview):
        rows, partial = preview
        dialog = style_dialog(QDialog(self), self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.setWindowTitle('Archive contents')
        dialog.resize(560, 390)
        layout = QVBoxLayout(dialog)
        title_label = QLabel(title)
        title_label.setTextFormat(Qt.TextFormat.PlainText)
        title_label.setWordWrap(True)
        layout.addWidget(title_label)
        table = QTreeWidget()
        table.setAccessibleName('Archive entries')
        table.setHeaderLabels(['Path', 'Type', 'Size'])
        table.setRootIsDecorated(False)
        table.setUniformRowHeights(True)
        table.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2):
            table.header().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        locale = QLocale()
        for path, folder, size in rows:
            size_text = '' if folder else locale.formattedDataSize(size) if size < 2**63 else 'Too large'
            table.addTopLevelItem(QTreeWidgetItem([path, 'Folder' if folder else 'File', size_text]))
        layout.addWidget(table)
        summary = ('The archive is empty.' if not rows else f'{len(rows)} entries shown.')
        if partial:
            summary = f'{len(rows)} entries shown. The archive exceeds the preview limit.'
        label = QLabel(summary)
        label.setObjectName('muted')
        layout.addWidget(label)
        close = QPushButton('Close')
        close.clicked.connect(dialog.reject)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        dialog.show()

    def extract_selection(self):
        paths = self.selected()
        if len(paths) == 1:
            self.run_job(lambda: extract_here(paths[0], rename_no_replace), self.reveal_path)

    def compress_selection(self):
        paths = self.selected()
        if not paths:
            return
        name = self.ask_name('Compress to ZIP', (paths[0].name if len(paths) == 1 else 'Archive') + '.zip')
        if name:
            target = self.folder / (name if name.lower().endswith('.zip') else name + '.zip')
            self.run_job(lambda: compress(paths, target, rename_no_replace), self.reveal_path)

    def toggle_hidden(self):
        self.model.setFilter(self.model.filter() ^ QDir.Filter.Hidden)

    def run_job(self, operation, completed=None):
        self.start_job(operation, completed)

    def start_job(self, operation, completed=None, transfer=None):
        if self.job is not None:
            self.statusBar().showMessage('A file operation is already running', 5000)
            return
        monitor = getattr(QApplication.instance(), 'files_device_monitor', None)
        if monitor is not None and monitor.files_active_request is not None:
            self.statusBar().showMessage('Wait for the drive operation to finish', 5000)
            return
        if transfer is None:
            self.job = FileJob(operation, self)
        else:
            paths, folder, move = transfer
            self.job = TransferJob(paths, folder, move, self)
            self.transfer_strip.start(self.job, len(paths), move)
            self.job.progress.connect(self.transfer_strip.update_progress)
        self.statusBar().showMessage('Working…')
        self.job.finished.connect(lambda: self.job_finished(completed))
        self.job.start()

    def job_finished(self, completed):
        job, self.job = self.job, None
        status = job.error or 'Done'
        if isinstance(job, TransferJob):
            self.transfer_strip.finish()
            if job.canceled:
                status = 'Transfer canceled. Items already transferred were kept.'
            elif not job.error:
                count, skipped = len(job.value['paths']), len(job.value['skipped'])
                status = f'Transferred: {count} · Skipped: {skipped}' if skipped else f'Transferred: {count}'
        self.statusBar().showMessage(status, 8000)
        job.deleteLater()
        if not job.error and not job.canceled and completed:
            completed(job.value)
        self.finish_deferred_close(job.error)

    def finish_deferred_close(self, error=None):
        if not self.close_when_idle:
            return
        if error:
            self.close_when_idle = False
            return
        QTimer.singleShot(0, self.close)

    def closeEvent(self, event):
        monitor = self.device_monitor
        if self.storage_dialog is not None and self.storage_dialog.job is not None:
            self.close_when_idle = True
            self.storage_dialog.stop_or_close()
            event.ignore()
            self.statusBar().showMessage('Stopping the storage scan…', 5000)
        elif self.job is not None or (monitor is not None and monitor.files_active_request == id(self)):
            self.close_when_idle = True
            event.ignore()
            self.statusBar().showMessage('Files will close when the operation finishes.')
        else:
            self.close_when_idle = False
            super().closeEvent(event)

    @staticmethod
    def trash_contents():
        root = Gio.File.new_for_uri('trash:///')
        entries = root.enumerate_children(
            'standard::name,standard::display-name,trash::orig-path',
            Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, None)
        items = []
        try:
            while (info := entries.next_file(None)) is not None:
                original = info.get_attribute_byte_string('trash::orig-path')
                if original and Path(os.fsdecode(original)).is_absolute():
                    items.append((info.get_display_name(), entries.get_child(info).get_uri(),
                                  os.fsdecode(original)))
        finally:
            entries.close(None)
        return sorted(items, key=lambda item: item[0].casefold())

    def show_trash(self):
        self.run_job(self.trash_contents, self.choose_restore)

    def choose_restore(self, items):
        if not items:
            self.statusBar().showMessage('Trash is empty', 5000)
            return
        labels = []
        for name, _, original in items:
            base = f'{name} · {original}'
            label = base
            duplicate = 2
            while label in labels:
                label = f'{base} ({duplicate})'
                duplicate += 1
            labels.append(label)
        choice, accepted = ThemedInput.getItem(self, 'Trash', 'Restore an item', labels, 0, False)
        if accepted:
            _, uri, original = items[labels.index(choice)]
            source = Gio.File.new_for_uri(uri)
            target = Gio.File.new_for_path(original)
            self.run_job(lambda: source.move(target, Gio.FileCopyFlags.NOFOLLOW_SYMLINKS,
                                             None, None))

    def reveal_path(self, path):
        if not self.navigate(path.parent):
            return
        def select(folder):
            if Path(folder) != path.parent:
                return
            self.model.directoryLoaded.disconnect(select)
            index = self.proxy.mapFromSource(self.model.index(str(path)))
            if index.isValid():
                self.view.setCurrentIndex(index)
                self.view.scrollTo(index)
        index = self.proxy.mapFromSource(self.model.index(str(path)))
        if index.isValid():
            self.view.setCurrentIndex(index)
            self.view.scrollTo(index)
        else:
            self.model.directoryLoaded.connect(select)

    def ask_name(self, title, initial=''):
        name, accepted = ThemedInput.getText(self, title, 'Name', text=initial)
        if accepted:
            try:
                return safe_name(name)
            except ValueError as error:
                self.statusBar().showMessage(str(error), 5000)
        return None

    def new_folder(self):
        name = self.ask_name('New folder')
        if name:
            target = self.folder / name
            self.run_job(target.mkdir)

    def rename(self):
        selected = self.selected()
        if len(selected) != 1:
            return
        source = selected[0]
        name = self.ask_name('Rename', source.name)
        if name and name != source.name:
            target = source.with_name(name)
            self.run_job(lambda: rename_no_replace(source, target))

    def trash(self):
        selected = self.selected()
        if not selected or not themed_prompt(self, 'Move to Trash', f'Move {len(selected)} item(s) to Trash?', 'Move to Trash', 'Cancel'):
            return

        def operation():
            for path in selected:
                Gio.File.new_for_path(str(path)).trash(None)
        self.run_job(operation)

    def copy(self, cut):
        selected = self.selected()
        if not selected:
            return
        mime = QMimeData()
        urls = [QUrl.fromLocalFile(str(path)) for path in selected]
        mime.setUrls(urls)
        mime.setData('x-special/gnome-copied-files',
                     ('cut' if cut else 'copy').encode() + b'\n' + b'\n'.join(bytes(url.toEncoded()) for url in urls))
        QApplication.clipboard().setMimeData(mime)

    def paste(self):
        mime = QApplication.clipboard().mimeData()
        if mime is None:
            return
        try:
            paths, cut = clipboard_transfer(mime)
        except ValueError as error:
            self.statusBar().showMessage(str(error), 5000)
            return
        self.transfer_paths(paths, self.folder, cut)

    def transfer_paths(self, paths, folder, move=False):
        if paths:
            self.start_job(None, transfer=(tuple(paths), folder, move))


def main():
    app = QApplication([sys.argv[0]])
    app.setStyle('Fusion')
    app.setApplicationName('Mellipi Files')
    app.setDesktopFileName('mellipi-files')
    app.setWindowIcon(QIcon.fromTheme('mellipi-files', QIcon.fromTheme('system-file-manager')))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--select', type=Path)
    parser.add_argument('locations', nargs='*')
    args = parser.parse_args()
    if args.select:
        path = args.select.expanduser().absolute()
        window = Files(path.parent)
        window.reveal_path(path)
        window.show()
        return app.exec()
    requested = args.locations or [str(Path.home())]
    windows = []
    for argument in requested:
        url = QUrl(argument)
        if url.scheme() == 'trash':
            window = Files(Path.home())
            window.show()
            QTimer.singleShot(0, window.show_trash)
            windows.append(window)
            continue
        if url.scheme() and not url.isLocalFile():
            continue
        path = Path(url.toLocalFile() if url.isLocalFile() else argument).expanduser()
        window = Files(path)
        window.show()
        windows.append(window)
    return app.exec() if windows else 1


if __name__ == '__main__':
    sys.exit(main())
