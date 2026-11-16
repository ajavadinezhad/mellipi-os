"""Mellipi's shared file and folder chooser for Qt applications."""
from pathlib import Path

from PyQt6.QtCore import QIdentityProxyModel, QSize, QStandardPaths, Qt, QUrl
from PyQt6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFileDialog, QLineEdit, QListView, QStyledItemDelegate, QToolButton, QTreeView

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
        self.apply_theme()
        self.theme_watch.changed.connect(self.apply_theme)
        self.resize(730, 480)

    def apply_theme(self):
        tokens = self.theme_watch.tokens
        self.setPalette(widget_palette(tokens))
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
