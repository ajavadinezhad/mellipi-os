"""Mellipi's local file browser, in a normal desktop window."""
import argparse
import os
import sys
from pathlib import Path

os.environ['ORBIT_QT'] = '5'
os.environ['QT_WAYLAND_SHELL_INTEGRATION'] = 'xdg-shell'
os.environ.pop('QT_WAYLAND_DISABLE_WINDOWDECORATION', None)

from PyQt5.QtCore import (
    QDir, QEvent, QFileSystemWatcher, QItemSelectionModel, QModelIndex, QMimeData,
    QRect, QSignalBlocker, QSize, QSortFilterProxyModel, Qt, QThread, QTimer, QUrl,
)
from PyQt5.QtGui import QColor, QDesktopServices, QDrag, QIcon, QKeySequence, QPainter, QPalette, QPixmap
from PyQt5.QtWidgets import (
    QAction, QApplication, QFileSystemModel, QFrame, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QPushButton, QStackedWidget, QTreeView, QVBoxLayout, QWidget,
)
from gi.repository import Gio
from preferences import Preferences
from app_palette import HEADER_HEIGHTS, colors
from window_controls import glyph_svg
from desktop_icons import rename_no_replace, safe_name, trash_item
from device_monitor import DeviceMonitor
from file_transfers import MAX_SOURCES, CancelToken, Transfer


class KeepBoth(CancelToken):
    def conflict(self, path, publish):
        self.check()
        return 'keep-both'


class FileJob(QThread):
    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation
        self.error = ""
        self.value = None

    def run(self):
        try:
            self.value = self.operation()
        except Exception as error:
            self.error = str(error)


class FolderModel(QFileSystemModel):
    def set_folder_color(self, color):
        # Match the folder symbol used by the taskbar, launcher, and sidebar.
        source = Path('/usr/share/icons/Adwaita/symbolic/places/folder-symbolic.svg')
        icon = QIcon(str(source)) if source.is_file() else QIcon.fromTheme('folder-symbolic')
        pixels = icon.pixmap(32, 32)
        if pixels.isNull():
            return
        painter = QPainter(pixels)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(pixels.rect(), QColor(color))
        painter.end()
        self.folder_icon = QIcon(pixels)

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DecorationRole and index.column() == 0 and self.isDir(index):
            return getattr(self, 'folder_icon', None) or super().data(index, role)
        return super().data(index, role)


def local_paths(urls):
    return list(dict.fromkeys(
        Path(url.toLocalFile()) for url in urls
        if url.isLocalFile() and Path(url.toLocalFile()).is_absolute()
    ))


class FolderFilter(QSortFilterProxyModel):
    """Only filter the displayed folder; keep its ancestors and sort order."""
    folder = None
    query = ''

    def filterAcceptsRow(self, row, parent):
        source = self.sourceModel()
        if self.query and parent.isValid() and source.filePath(parent) == str(self.folder):
            return self.query in source.fileName(source.index(row, 0, parent)).casefold()
        return True

    def sort(self, column, order=Qt.AscendingOrder):
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
        self.setDragDropMode(QTreeView.DragDrop)

    def startDrag(self, _actions):
        paths = self.owner.selected()
        if not 1 <= len(paths) <= MAX_SOURCES:
            return
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
        drag = QDrag(self)
        drag.setMimeData(mime)
        index = self.currentIndex().sibling(self.currentIndex().row(), 0)
        icon = index.data(Qt.DecorationRole)
        if isinstance(icon, QIcon):
            drag.setPixmap(icon.pixmap(32, 32))
        # Transfer owns the move. A successful drop must never delete the
        # source from the view before the destination finishes copying it.
        drag.exec_(Qt.CopyAction | Qt.MoveAction, Qt.CopyAction)

    def drop_details(self, event):
        paths = local_paths(event.mimeData().urls())
        monitor = getattr(QApplication.instance(), 'files_device_monitor', None)
        if self.owner.job is not None or not 1 <= len(paths) <= MAX_SOURCES:
            return None
        if monitor is not None and monitor.files_active_request is not None:
            return None
        index = self.indexAt(event.pos())
        source = self.owner.proxy.mapToSource(index)
        folder = self.owner.folder
        if source.isValid() and self.owner.model.isDir(source):
            folder = Path(self.owner.model.filePath(source))
        internal = isinstance(event.source(), FolderView)
        action = Qt.MoveAction if internal and event.keyboardModifiers() & Qt.ShiftModifier else Qt.CopyAction
        if not event.possibleActions() & action:
            return None
        if internal and folder == self.owner.folder and all(path.parent == folder for path in paths):
            if action == Qt.MoveAction or not event.keyboardModifiers() & Qt.ControlModifier:
                return None
        return paths, folder, action, index if folder != self.owner.folder else QModelIndex()

    def dragEnterEvent(self, event):
        if event.possibleActions() & Qt.CopyAction and 1 <= len(local_paths(event.mimeData().urls())) <= MAX_SOURCES:
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        details = self.drop_details(event)
        y = event.pos().y()
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
        self.owner.transfer_paths(paths, folder, action == Qt.MoveAction)
        event.setDropAction(action)
        event.accept()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.drop_rect.isEmpty():
            painter = QPainter(self.viewport())
            painter.setPen(self.palette().highlight().color())
            painter.drawRect(self.drop_rect.adjusted(0, 0, -1, -1))
            painter.end()


class TitleBar(QFrame):
    def __init__(self, window, navigation):
        super().__init__()
        self.owner = window
        self.setObjectName('titlebar')
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(navigation, 1)
        layout.addSpacing(18)
        self.controls = {}
        self.control_ink = '#ffffff'
        for glyph, action in (('minimize', window.showMinimized),
                              ('maximize', self.toggle_maximized),
                              ('close', window.close)):
            button = window.button('', action)
            button.setObjectName('windowControl')
            button.setFixedSize(32, 28)
            self.controls[glyph] = button
            layout.addWidget(button)
        window.installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched is self.owner and event.type() == QEvent.WindowStateChange:
            self.update_controls(self.control_ink)
        return super().eventFilter(watched, event)

    def update_controls(self, ink):
        self.control_ink = ink
        for name, button in self.controls.items():
            glyph = 'restore' if name == 'maximize' and self.owner.isMaximized() else name
            pixmap = QPixmap()
            pixmap.loadFromData(glyph_svg(glyph, ink), 'SVG')
            button.setIcon(QIcon(pixmap))
            button.setAccessibleName(glyph.capitalize())
            button.setToolTip(glyph.capitalize())

    def toggle_maximized(self):
        if self.owner.isMaximized():
            self.owner.showNormal()
        else:
            self.owner.showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.owner.windowHandle().startSystemMove():
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.toggle_maximized()
        else:
            super().mouseDoubleClickEvent(event)


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
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.resize(800, 565)
        self.history = []
        self.position = -1
        self.job = None
        self.model = FolderModel(self)
        self.model.setReadOnly(True)
        self.model.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot | QDir.AllDirs)
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
        self.view.setSelectionMode(QTreeView.ExtendedSelection)
        self.view.setSortingEnabled(True)
        self.view.sortByColumn(0, Qt.AscendingOrder)
        self.view.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.view.header().setStretchLastSection(False)
        for column, width in ((1, 84), (2, 112), (3, 145)):
            self.view.setColumnWidth(column, width)
        self.view.doubleClicked.connect(self.open_index)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self.context_menu)
        self.location = QLineEdit()
        self.location.setAccessibleName('Folder location')
        self.location.returnPressed.connect(self.submit_location)
        self.location.installEventFilter(self)
        self.address = QStackedWidget()
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
        for widget in (self.back, self.forward, up):
            widget.setObjectName('navigation')
            widget.setFixedWidth(28)
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
        sidebar = QWidget()
        sidebar.setObjectName('places')
        sidebar.setFixedWidth(160)
        sidebar.setLayout(self.sidebar)
        self.sidebar.setContentsMargins(8, 8, 8, 8)
        self.sidebar.setSpacing(2)
        body.setSpacing(0)
        body.addWidget(sidebar)
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
        content = QVBoxLayout()
        content.setContentsMargins(0, 8, 0, 0)
        content.setSpacing(8)
        content.addWidget(self.search)
        content.addLayout(body, 1)
        layout.addLayout(content, 1)
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
            action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            action.triggered.connect(callback)
            self.view.addAction(action)
            self.actions.append(action)
        menu = QMenu(self)
        menu.addActions(self.actions)
        menu_icon = QIcon.fromTheme('open-menu-symbolic', QIcon.fromTheme('open-menu'))
        actions_button = QPushButton(menu_icon, '⋯' if menu_icon.isNull() else '')
        actions_button.setObjectName('navigation')
        actions_button.setProperty('symbolicIcon', 'open-menu')
        actions_button.setAccessibleName('File actions')
        actions_button.setToolTip('File actions')
        actions_button.setMenu(menu)
        top.addWidget(actions_button)
        for shortcut, callback in (('Ctrl+L', self.edit_location), ('Ctrl+F', self.show_search)):
            action = QAction(self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            self.addAction(action)
        self.settings = Path(os.environ.get('ORBIT_SETTINGS_FILE') or
                             Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'abstract/settings.json')
        self.last_appearance = None
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self.apply_theme)
        self.watcher.directoryChanged.connect(self.apply_theme)
        if self.settings.parent.is_dir():
            self.watcher.addPath(str(self.settings.parent))
        self.apply_theme()
        if not self.navigate(initial):
            self.navigate(Path.home())

    def update_count(self, *_):
        count = self.proxy.rowCount(self.view.rootIndex())
        noun = 'match' if self.proxy.query else 'item'
        self.item_count.setText(f'{count} {noun}' + ('' if count == 1 else 'es' if noun == 'match' else 's'))

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
                        selection.select(index, QItemSelectionModel.Select | QItemSelectionModel.Rows)
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
                item.widget().deleteLater()
        home = Path.home()
        base = home if self.folder.is_relative_to(home) else Path('/')
        paths = [self.folder]
        while paths[-1] != base:
            paths.append(paths[-1].parent)
        visible = list(reversed(paths[:4]))
        if len(paths) > len(visible):
            more = QPushButton('…')
            more.setObjectName('crumb')
            menu = QMenu(more)
            for path in reversed(paths[4:]):
                action = menu.addAction('Home' if path == home else path.name or '/')
                action.triggered.connect(lambda checked=False, target=path: self.navigate(target))
            more.setMenu(menu)
            self.crumb_layout.addWidget(more)
        for path in visible:
            if self.crumb_layout.count():
                separator = QLabel('›')
                separator.setObjectName('crumbSeparator')
                self.crumb_layout.addWidget(separator)
            title = 'Home' if path == home else path.name or '/'
            if len(title) > 22:
                title = title[:20] + '…'
            button = self.button(title, lambda checked=False, target=path: self.navigate(target))
            button.setObjectName('currentCrumb' if path == self.folder else 'crumb')
            button.setToolTip(str(path))
            self.crumb_layout.addWidget(button)
        self.crumb_layout.addStretch()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.KeyPress and watched is getattr(self, 'search', None):
            if event.key() == Qt.Key_Escape:
                self.search.clear()
                self.search.hide()
                self.view.setFocus()
                return True
            if event.key() == Qt.Key_Down:
                self.focus_results()
                return True
        if watched is self.location and event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.location.setText(str(self.folder))
            self.address.setCurrentWidget(self.breadcrumbs)
            self.view.setFocus()
            return True
        if watched is self.centralWidget() and event.type() in (QEvent.MouseMove, QEvent.MouseButtonPress):
            edges = Qt.Edges()
            point = event.pos()
            if not self.isMaximized():
                if point.x() < 6:
                    edges |= Qt.LeftEdge
                elif point.x() >= watched.width() - 6:
                    edges |= Qt.RightEdge
                if point.y() < 6:
                    edges |= Qt.TopEdge
                elif point.y() >= watched.height() - 6:
                    edges |= Qt.BottomEdge
            if event.type() == QEvent.MouseButtonPress and edges and event.button() == Qt.LeftButton:
                return self.windowHandle().startSystemResize(edges)
            if event.type() == QEvent.MouseMove:
                horizontal = bool(edges & (Qt.LeftEdge | Qt.RightEdge))
                vertical = bool(edges & (Qt.TopEdge | Qt.BottomEdge))
                if horizontal and vertical:
                    diagonal = bool(edges & Qt.LeftEdge) == bool(edges & Qt.TopEdge)
                    watched.setCursor(Qt.SizeFDiagCursor if diagonal else Qt.SizeBDiagCursor)
                elif horizontal or vertical:
                    watched.setCursor(Qt.SizeHorCursor if horizontal else Qt.SizeVerCursor)
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

    @staticmethod
    def symbolic_icon(name):
        base = Path('/usr/share/icons/Adwaita/symbolic')
        for category in ('actions', 'places', 'status', 'devices'):
            asset = base / category / f'{name}-symbolic.svg'
            if asset.is_file():
                return QIcon(str(asset))
        return QIcon.fromTheme(name + '-symbolic', QIcon.fromTheme(name))

    def apply_theme(self):
        # Preferences saves by replacing the file. Watch its directory as well.
        if self.settings.is_file() and str(self.settings) not in self.watcher.files():
            self.watcher.addPath(str(self.settings))
        preferences = Preferences(self.settings)
        palette = colors(preferences)
        appearance = (palette, preferences.values['density'], preferences.values['corners'],
                      preferences.values['textScale'])
        if appearance == self.last_appearance:
            return
        self.last_appearance = appearance
        app = QApplication.instance()
        qt_palette = QPalette()
        for role, key in ((QPalette.Window, 'background'), (QPalette.Base, 'surface'),
                          (QPalette.AlternateBase, 'raised'), (QPalette.Button, 'raised'),
                          (QPalette.WindowText, 'text'), (QPalette.Text, 'text'),
                          (QPalette.ButtonText, 'text'), (QPalette.Highlight, 'accent'),
                          (QPalette.HighlightedText, 'accent_text'), (QPalette.Link, 'accent')):
            qt_palette.setColor(role, QColor(palette[key]))
        app.setPalette(qt_palette)
        focus = palette['text'] if preferences.values['highContrast'] else palette['accent']
        ink = QColor(focus)
        for control in [*self.actions, *self.findChildren(QPushButton)]:
            name = control.property('symbolicIcon')
            if not name:
                continue
            icon = self.symbolic_icon(name)
            if icon.isNull() and control.objectName() == 'place':
                icon = self.symbolic_icon('folder')
            if icon.isNull():
                continue
            pixmap = icon.pixmap(32, 32)
            if pixmap.isNull():
                continue
            painter = QPainter(pixmap)
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.fillRect(pixmap.rect(), ink)
            painter.end()
            control.setIcon(QIcon(pixmap))
            if isinstance(control, QPushButton) and control.objectName() == 'navigation':
                control.setText('')
        self.titlebar.update_controls(focus)
        self.model.set_folder_color(palette['accent'])
        self.view.viewport().update()
        density = preferences.values['density']
        self.titlebar.setMinimumHeight(HEADER_HEIGHTS[density])
        for button in self.titlebar.findChildren(QPushButton):
            button.setIconSize(QSize(16, 16))
            button.setMinimumHeight(28)
        padding = {'comfortable': 8, 'compact': 5, 'extra': 3}[density]
        radius = {'square': 0, 'soft': 4, 'rounded': 8}[preferences.values['corners']]
        self.setStyleSheet('''
            QMainWindow, QStatusBar { background: %(background)s; color: %(text)s; }
            QTreeView, QLineEdit, QMenu { background: %(surface)s; color: %(text)s; }
            QPushButton, QHeaderView::section { background: %(surface)s; color: %(text)s; }
            QFrame#divider { background: %(separator)s; }
            QWidget#places { background: %(raised)s; border-radius: %(radius)spx; }
            QLabel#crumbSeparator { color: %(muted)s; }
            QLabel#itemCount { color: %(muted)s; padding-right: 4px; }
            QMenu { border: 1px solid %(border)s; padding: 3px; }
            QMenu::item { padding: %(padding)spx 20px %(padding)spx 8px; }
            QWidget#breadcrumbs { background: %(surface)s;
                border-radius: %(radius)spx; }
            QPushButton#navigation, QPushButton#crumb, QPushButton#currentCrumb {
                border: 0; padding: 3px 5px; background: transparent; }
            QPushButton#crumb { color: %(muted)s; }
            QPushButton#currentCrumb { font-weight: 600; }
            QPushButton#navigation:hover, QPushButton#crumb:hover { background: %(hover)s; }
            QPushButton#navigation:focus, QPushButton#crumb:focus, QPushButton#currentCrumb:focus, QPushButton#windowControl:focus { border-bottom: 2px solid %(focus)s; }
            QPushButton#windowControl { background: transparent; border: 0; padding: 2px; }
            QPushButton#windowControl:hover { background: %(hover)s; }
            QPushButton#place { text-align: left; border: 0; border-radius: %(radius)spx;
                border-left: 2px solid transparent; background: transparent; color: %(muted)s; }
            QPushButton#place:hover { background: %(hover)s; color: %(text)s; }
            QPushButton#place:checked { background: %(selected_surface)s; color: %(text)s;
                border-left: 2px solid %(accent)s; }
            QPushButton#place:focus { border-bottom: 1px solid %(accent)s; }
            QTreeView { border: 0; border-radius: %(radius)spx; }
            QHeaderView::section { padding: 5px; border: 0; border-bottom: 1px solid %(separator)s; }
            QPushButton { border: 0; border-radius: %(radius)spx; padding: %(padding)spx; }
            QLineEdit { border: 1px solid %(border)s; border-radius: %(radius)spx; padding: %(padding)spx; }
            QPushButton:hover { background: %(hover)s; }
            QPushButton:disabled { color: %(muted)s; }
            QPushButton:focus, QLineEdit:focus, QTreeView:focus { border: 1px solid %(accent)s; }
            QTreeView::item { padding: %(padding)spx 4px; }
            QTreeView::item:selected, QMenu::item:selected { background: %(accent)s; color: %(accent_text)s; }
        ''' % dict(palette, padding=padding, radius=radius, focus=focus))
        font = app.font()
        font.setPixelSize(max(8, round((11 if density == 'extra' else 12) * preferences.values['textScale'])))
        app.setFont(font)

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

    def context_menu(self, point):
        index = self.view.indexAt(point)
        if index.isValid() and not self.view.selectionModel().isRowSelected(index.row(), index.parent()):
            self.view.setCurrentIndex(index)
        menu = QMenu(self)
        if index.isValid():
            menu.addActions(self.actions)
        else:
            for action in self.actions:
                if action.text() in ('New folder', 'Paste', 'Show or hide hidden files'):
                    menu.addAction(action)
        menu.exec_(self.view.viewport().mapToGlobal(point))
        menu.deleteLater()

    def toggle_hidden(self):
        self.model.setFilter(self.model.filter() ^ QDir.Hidden)

    def run_job(self, operation, completed=None):
        if self.job is not None:
            self.statusBar().showMessage('A file operation is already running', 5000)
            return
        monitor = getattr(QApplication.instance(), 'files_device_monitor', None)
        if monitor is not None and monitor.files_active_request is not None:
            self.statusBar().showMessage('Wait for the drive operation to finish', 5000)
            return
        self.job = FileJob(operation, self)
        self.statusBar().showMessage('Working…')
        self.job.finished.connect(lambda: self.job_finished(completed))
        self.job.start()

    def job_finished(self, completed):
        job, self.job = self.job, None
        self.statusBar().showMessage(job.error or 'Done', 8000)
        job.deleteLater()
        if not job.error and completed:
            completed(job.value)

    def closeEvent(self, event):
        monitor = self.device_monitor
        if self.job is not None or (monitor is not None and monitor.files_active_request == id(self)):
            event.ignore()
            self.statusBar().showMessage('Wait for the file operation to finish', 5000)
        else:
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
        choice, accepted = QInputDialog.getItem(self, 'Trash', 'Restore an item', labels, 0, False)
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
        name, accepted = QInputDialog.getText(self, title, 'Name', text=initial)
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
        if not selected or QMessageBox.question(self, 'Move to Trash', f'Move {len(selected)} item(s) to Trash?') != QMessageBox.Yes:
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
        urls = mime.urls()
        payload = bytes(mime.data('x-special/gnome-copied-files')).splitlines()
        cut = bool(payload and payload[0] == b'cut')
        if not urls and payload:
            urls = [QUrl.fromEncoded(line) for line in payload[1:]]
        self.transfer_paths(local_paths(urls), self.folder, cut)

    def transfer_paths(self, paths, folder, move=False):
        if paths:
            self.run_job(lambda: Transfer(folder.resolve(), rename_no_replace, trash_item, KeepBoth()).run(paths, move))


def main():
    app = QApplication([sys.argv[0]])
    app.setStyle('Fusion')
    app.setApplicationName('Mellipi Files')
    app.setDesktopFileName('mellipi-files')
    app.setWindowIcon(QIcon.fromTheme('system-file-manager'))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--select', type=Path)
    parser.add_argument('locations', nargs='*')
    args = parser.parse_args()
    if args.select:
        path = args.select.expanduser().absolute()
        window = Files(path.parent)
        window.reveal_path(path)
        window.show()
        return app.exec_()
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
    return app.exec_() if windows else 1


if __name__ == '__main__':
    sys.exit(main())
