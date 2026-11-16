"""Mellipi's shared file and folder chooser for Qt applications."""
from pathlib import Path

from PyQt6.QtCore import QEvent, QIdentityProxyModel, QSize, QStandardPaths, QTimer, Qt, QUrl
from PyQt6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHeaderView, QLineEdit, QListView, QStyledItemDelegate, QToolButton, QTreeView

from files_icons import file_icon, icon, place_icon
from qt_app import BASE_STYLE, ThemeWatch, exec_owned_dialog, widget_palette


class ChooserIcons(QIdentityProxyModel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_dialog = parent

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DecorationRole and index.isValid() and index.column() == 0:
            source = self.sourceModel()
            item = self.mapToSource(index)
            tokens = self.parent_dialog.theme_watch.tokens
            art = file_icon(source.fileName(item), source.isDir(item), tokens['accent_ink'], tokens['accent'], tokens['text'])
            if not art.isNull():
                return art
        return super().data(index, role)


class PlaceIcons(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        dialog = self.parent()
        urls = dialog.sidebarUrls()
        if not 0 <= index.row() < len(urls):
            return
        path = urls[index.row()].toLocalFile()
        role = dialog.place_roles.get(path, 'folder')
        art = place_icon(role, dialog.theme_watch.tokens)
        if not art.isNull():
            option.icon = art
            option.decorationSize = QSize(18, 18)


class FileChooser(QFileDialog):
    def __init__(self, parent=None, caption='', directory='', filters='', *, mode=QFileDialog.FileMode.ExistingFile,
                 save=False, options=QFileDialog.Option(0)):
        super().__init__(parent)
        self.setOptions(options | self.Option.DontUseNativeDialog)
        self.setObjectName('mellipiFileChooser')
        self.setWindowTitle(caption or ('Save file' if save else 'Choose a file'))
        self.setAcceptMode(self.AcceptMode.AcceptSave if save else self.AcceptMode.AcceptOpen)
        self.setFileMode(mode)
        self.setViewMode(self.ViewMode.Detail)
        if mode == self.FileMode.Directory:
            self.setOption(self.Option.ShowDirsOnly)
            self.setLabelText(self.DialogLabel.Accept, 'Choose folder')
        elif filters:
            self.setNameFilter(filters)
        if directory:
            path = Path(directory).expanduser()
            if path.is_dir() or mode == self.FileMode.Directory:
                self.setDirectory(str(path))
            else:
                self.setDirectory(str(path.parent))
                self.selectFile(path.name)
        else:
            self.setDirectory(str(Path.home()))
        self.place_roles = {str(Path.home()): 'user-home'}
        for name, role in (('DesktopLocation','user-desktop'),('DocumentsLocation','folder-documents'),
                           ('DownloadLocation','folder-download'),('PicturesLocation','folder-pictures')):
            path = QStandardPaths.writableLocation(getattr(QStandardPaths.StandardLocation, name))
            if path and Path(path).is_dir():
                self.place_roles.setdefault(path, role)
        self.place_roles['/'] = 'drive-harddisk'
        self.setSidebarUrls([QUrl.fromLocalFile(path) for path in self.place_roles])
        self.theme_watch = ThemeWatch(self)
        self.icons = ChooserIcons(self)
        self.setProxyModel(self.icons)
        sidebar = self.findChild(QListView, 'sidebar')
        if sidebar is not None:
            sidebar.setItemDelegate(PlaceIcons(self))
        for box in self.findChildren(QDialogButtonBox):
            for button in box.buttons():
                if box.buttonRole(button) == QDialogButtonBox.ButtonRole.AcceptRole:
                    button.setProperty('mellipiPrimary', True)
        self._columns_timer = QTimer(self)
        self._columns_timer.setSingleShot(True)
        self._columns_timer.timeout.connect(self.fit_detail_columns)
        view = self.findChild(QTreeView, 'treeView')
        self._detail_viewport = view.viewport() if view is not None else None
        if self._detail_viewport is not None:
            self._detail_viewport.installEventFilter(self)
        self.apply_theme()
        self.theme_watch.changed.connect(self.apply_theme)
        self.resize(730, 480)

    def apply_theme(self):
        tokens = self.theme_watch.tokens
        self.setPalette(widget_palette(tokens))
        gap = max(4, tokens['padding'])
        self.layout().setContentsMargins(gap + 2, gap + 2, gap + 2, gap + 2)
        self.layout().setSpacing(gap)
        self.setStyleSheet((BASE_STYLE + """
            QTreeView, QListView { background: %(surface)s; color: %(text)s; border: %(outline_width)dpx solid %(control_border)s; }
            QTreeView::item, QListView::item { padding: 4px 3px; }
            QTreeView::item:selected, QListView::item:selected {
                background: %(selected_surface)s; color: %(text)s;
            }
            QHeaderView::section { background: %(raised)s; color: %(text)s; border: 0; padding: 5px; }
        """) % tokens)
        # The stock chooser gives its filename editor a different height than
        # its paired file-type field. Keep label baselines and controls lined up.
        filename = self.findChild(QLineEdit, 'fileNameEdit')
        filetype = self.findChild(QComboBox, 'fileTypeCombo')
        if filename is not None and filetype is not None:
            height = max(filename.sizeHint().height(), filetype.sizeHint().height())
            filename.setMinimumHeight(height)
            filetype.setMinimumHeight(height)
        for button_name, glyph in (('backButton', 'arrow-left'), ('forwardButton', 'arrow-right'),
                                   ('toParentButton', 'arrow-up'), ('newFolderButton', 'folder-plus')):
            button = self.findChild(QToolButton, button_name)
            if button is not None:
                button.setIcon(icon('regular', glyph, tokens['text']))
        # Match Files' row artwork without changing the sidebar's compact size.
        for name, kind in (('treeView', QTreeView), ('listView', QListView), ('sidebar', QListView)):
            view = self.findChild(kind, name)
            if view is not None:
                view.setIconSize(QSize(18, 18) if name == 'sidebar' else QSize(20, 20))
                view.viewport().update()
        self._columns_timer.start(0)

    def eventFilter(self, watched, event):
        if watched is getattr(self, '_detail_viewport', None) and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._columns_timer.start(0)
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_columns_timer'):
            self._columns_timer.start(0)

    def fit_detail_columns(self):
        view = self.findChild(QTreeView, 'treeView')
        if view is None:
            return
        header = view.header()
        metrics = header.fontMetrics()
        # Keep the name usable first; show metadata when it has breathing room.
        widths = [metrics.horizontalAdvance(text) + 24 for text in
                  ('Document name', '32.0 MiB', 'Document', '2026-12-31 12:00')]
        spare = view.viewport().width() - widths[0]
        useful = set()
        # Modification time is the most useful clue when similarly named
        # files are visible; keep it before spending space on type or size.
        for column in (3, 1, 2):
            if column < header.count() and widths[column] <= spare:
                useful.add(column)
                spare -= widths[column]
        for column in range(1, header.count()):
            view.setColumnHidden(column, column not in useful)
            if column in useful:
                view.setColumnWidth(column, widths[column])
        header.setStretchLastSection(False)
        if header.count():
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

    @classmethod
    def _choose(cls, parent, caption, directory, filters, mode, save, options):
        dialog = cls(parent, caption, directory, filters, mode=mode, save=save, options=options)
        try:
            if exec_owned_dialog(dialog) != QDialog.DialogCode.Accepted:
                return [], ''
            return dialog.selectedFiles(), dialog.selectedNameFilter()
        finally:
            dialog.deleteLater()

    @classmethod
    def getOpenFileName(cls, parent=None, caption='', directory='', filter='', *, options=QFileDialog.Option(0)):
        paths, chosen = cls._choose(parent, caption, directory, filter, cls.FileMode.ExistingFile, False, options)
        return (paths[0] if paths else ''), chosen

    @classmethod
    def getOpenFileNames(cls, parent=None, caption='', directory='', filter='', *, options=QFileDialog.Option(0)):
        return cls._choose(parent, caption, directory, filter, cls.FileMode.ExistingFiles, False, options)

    @classmethod
    def getSaveFileName(cls, parent=None, caption='', directory='', filter='', *, options=QFileDialog.Option(0)):
        paths, chosen = cls._choose(parent, caption, directory, filter, cls.FileMode.AnyFile, True, options)
        return (paths[0] if paths else ''), chosen

    @classmethod
    def getExistingDirectory(cls, parent=None, caption='', directory='', *, options=QFileDialog.Option(0)):
        paths, _ = cls._choose(parent, caption, directory, '', cls.FileMode.Directory, False, options)
        return paths[0] if paths else ''
