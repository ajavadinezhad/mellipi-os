"""Mellipi Software, a native browser for the system's configured app sources."""
from dataclasses import replace
import os
import sys

os.environ['ORBIT_QT'] = '6'
os.environ['QT_WAYLAND_SHELL_INTEGRATION'] = 'xdg-shell'
os.environ.pop('QT_WAYLAND_DISABLE_WINDOWDECORATION', None)

from PyQt6.QtCore import QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QShortcut, QIcon, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QBoxLayout, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QPushButton, QSizePolicy, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from qt_app import AppWindow, themed_prompt
from files_icons import icon
from software_sources import SOURCES, friendly_error, install, installed_software, rank, refresh_apt, search


class Job(QThread):
    sourceReady = pyqtSignal(str, object)
    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation
        self.value = None
        self.error = ''

    def run(self):
        try:
            self.value = self.operation()
        except Exception as error:
            self.error = friendly_error(error)


def label(text='', wrap=False):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    return widget


class SoftwareWindow(AppWindow):
    extra_style = """
        QLabel#selectionTitle { font-weight: 600; }
        QFrame#detail { background: %(surface)s; border-radius: %(radius)dpx; }
        QPushButton#install:enabled { background: %(accent)s; color: %(accent_text)s; }
        QPushButton#install:focus { border-color: %(focus)s; }
        QPushButton#installedFilter:checked { background: %(selected_surface)s; border-color: %(focus)s; }
        QPushButton#installedFilter:focus { border-color: %(focus)s; }
        QTreeWidget::item { padding: 5px 4px; }
    """
    def __init__(self):
        super().__init__('Mellipi Software')
        self.setWindowIcon(QIcon.fromTheme('mellipi-software', QIcon.fromTheme('system-software-install')))
        self.resize(790, 560)
        self.setMinimumSize(480, 420)
        self.job = None
        self.installing = False
        self.refreshing = False
        self.term = ''
        self.installed_only = False
        self.searching = False
        self.pending_search = False
        self.closing = False
        layout = self.content

        toolbar = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText('Search software')
        self.query.setAccessibleName('Search software')
        self.query.setMaxLength(120)
        self.query.setClearButtonEnabled(True)
        self.query.returnPressed.connect(self.start_search)
        toolbar.addWidget(self.query, 1)
        self.source = QComboBox()
        self.source.setAccessibleName('Software source')
        self.source.addItem('All sources', '')
        for key, name in SOURCES.items():
            self.source.addItem(name, key)
        self.source.currentIndexChanged.connect(self.start_search)
        self.search_button = QPushButton()
        self.search_button.setAccessibleName('Search software')
        self.search_button.setToolTip('Search software')
        self.search_button.setMinimumSize(32, 32)
        self.search_button.setProperty('mellipiSymbolicIcon', 'edit-find')
        self.search_button.clicked.connect(self.start_search)
        toolbar.addWidget(self.search_button)
        layout.addLayout(toolbar)
        filters = QHBoxLayout()
        filters.addWidget(self.source)
        self.installed_button = QPushButton('Installed only')
        self.installed_button.setObjectName('installedFilter')
        self.installed_button.setCheckable(True)
        self.installed_button.setToolTip('View what is already installed on this computer')
        self.installed_button.toggled.connect(self.change_view)
        filters.addWidget(self.installed_button)
        filters.addStretch(1)
        layout.addLayout(filters)
        self.search_shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        self.search_shortcut.activated.connect(self.query.setFocus)

        self.suggestions = QWidget()
        shortcuts = QHBoxLayout(self.suggestions)
        shortcuts.setContentsMargins(0, 0, 0, 0)
        shortcuts.addWidget(label('Try'))
        for title in ('VLC', 'GIMP', 'Firefox', 'LibreOffice'):
            button = QPushButton(title)
            button.clicked.connect(lambda _, term=title: self.search_for(term))
            shortcuts.addWidget(button)
        shortcuts.addStretch(1)
        layout.addWidget(self.suggestions)

        self.list = QTreeWidget()
        self.list.setAccessibleName('Software search results')
        self.list.setHeaderLabels(['Software', 'Source', 'Status'])
        self.list.setRootIsDecorated(False)
        self.list.setUniformRowHeights(True)
        self.list.setIconSize(QSize(16, 16))
        self.themeChanged.connect(self.refresh_source_glyphs)
        self.list.setAlternatingRowColors(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.header().setStretchLastSection(False)
        self.list.currentItemChanged.connect(self.show_selection)
        layout.addWidget(self.list, 1)

        self.detail = QFrame()
        self.detail.setObjectName('detail')
        panel = self.detail_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self.detail)
        panel.setContentsMargins(14, 12, 14, 12)
        description = QVBoxLayout()
        self.name = label(wrap=True)
        self.name.setObjectName('selectionTitle')
        self.info = label(wrap=True)
        self.description = label(wrap=True)
        self.info.setObjectName('muted')
        for row in (self.name, self.info, self.description):
            row.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            description.addWidget(row)
        panel.addLayout(description, 1)
        self.install_button = QPushButton('Install')
        self.install_button.setObjectName('install')
        self.install_button.setProperty('mellipiSymbolicIcon', 'system-software-install')
        self.install_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.install_button.clicked.connect(self.confirm_install)
        panel.addWidget(self.install_button)
        layout.addWidget(self.detail)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName('Software operation in progress')
        self.progress.setFixedHeight(4)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.status = label('Search for an app or package.', wrap=True)
        self.status.setAccessibleName('Software status')
        layout.addWidget(self.status)
        self.source_status = label(wrap=True)
        self.source_status.setObjectName('muted')
        self.source_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        source_info = self.source_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        source_info.addWidget(self.source_status, 1)
        self.refresh_button = QPushButton()
        self.refresh_button.setToolTip('Refresh system packages')
        self.refresh_button.setMinimumSize(32, 32)
        self.refresh_button.setAccessibleName('Refresh system packages')
        self.refresh_button.setProperty('mellipiSymbolicIcon', 'view-refresh')
        self.refresh_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.refresh_button.clicked.connect(self.start_refresh)
        self.refresh_button.hide()
        source_info.addWidget(self.refresh_button)
        layout.addLayout(source_info)

        self.list.header().geometriesChanged.connect(self.fit_result_columns)
        self.themeChanged.connect(self.fit_layout)
        self.refresh_icons()
        self.fit_layout()
        self.query.setFocus()
        self.show_selection()
        QTimer.singleShot(0, self.start_search)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'source_layout'):
            self.fit_layout()

    def fit_layout(self):
        # Use actual font metrics, so large text gets the narrower layout
        # earlier without guessing from the physical screen resolution.
        wide = self.width() >= max(600, self.fontMetrics().horizontalAdvance('Mellipi Software') * 5)
        direction = QBoxLayout.Direction.LeftToRight if wide else QBoxLayout.Direction.TopToBottom
        self.detail_layout.setDirection(direction)
        self.source_layout.setDirection(direction)
        glyph = max(16, min(24, self.theme['font_size'] + 2))
        for button in (self.search_button, self.refresh_button):
            button.setIconSize(QSize(glyph, glyph))
            button.setMinimumSize(glyph + 18, glyph + 14)
        self.suggestions.setVisible(wide and not self.term and not self.installed_only)
        self.fit_result_columns()

    def fit_result_columns(self):
        width = self.list.viewport().width()
        if width <= 0:
            return
        # Keep name, source and state visible without a horizontal scrollbar.
        font = self.list.fontMetrics()
        status = min(round(width * .29), font.horizontalAdvance('Available') + 24)
        source = min(round(width * .32), font.horizontalAdvance('Flatpak (system)') + 24)
        for column, size in enumerate((width - source - status, source, status)):
            if self.list.columnWidth(column) != size:
                self.list.setColumnWidth(column, size)

    def selected(self):
        item = self.list.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def show_selection(self, *_):
        package = self.selected()
        self.detail.setVisible(package is not None)
        if not package:
            return
        self.name.setText(package.name)
        info = [package.identifier, package.origin]
        if package.version:
            info.append(package.version)
        if package.branch:
            info.append(package.branch)
        self.info.setText(' · '.join(info))
        description = package.description
        if package.classic:
            description = f'{description}\nClassic confinement is required for this package.'.lstrip()
        self.description.setText(description)
        self.description.setVisible(bool(description))
        self.install_button.setVisible(not self.installed_only)
        self.install_button.setEnabled(not package.installed and not package.classic and not self.job)
        if package.installed:
            self.install_button.setText('Installed')
        elif package.classic:
            self.install_button.setText('Unavailable')
        else:
            self.install_button.setText('Install')

    def search_for(self, term):
        self.query.setText(term)
        self.start_search()

    def change_view(self, installed):
        self.installed_only = installed
        self.query.setPlaceholderText('Filter installed software' if installed else 'Search software')
        self.query.setAccessibleName(self.query.placeholderText())
        self.list.clear()
        self.source_status.clear()
        self.refresh_button.hide()
        self.status.setText('Reading installed software…' if installed else 'Searching software…')
        self.start_search()

    def start_search(self, *_):
        if self.job:
            if self.searching:self.pending_search = True
            return
        self.term = self.query.text().strip()
        source = self.source.currentData()
        sources = (source,) if source else tuple(SOURCES)
        self.fit_layout()
        if self.installed_only:
            self.status.setText('Reading installed software…')
        elif self.term:
            self.status.setText(f'Searching for “{self.term}”…')
        self.searching = True
        self.search_results = {}
        term = self.term
        operation = installed_software if self.installed_only else search
        job = Job(lambda: operation(term, sources, job.sourceReady.emit), self)
        job.sourceReady.connect(self.source_finished)
        self.job = job
        job.finished.connect(lambda: self.finish_job(self.search_finished))
        self.install_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.progress.show()
        job.start()

    def source_finished(self, source, result):
        if self.closing or self.pending_search or self.query.text().strip() != self.term:
            return
        self.search_results[source] = result
        self.search_finished(self.search_results, '')
        self.status.setText('Searching remaining sources…')

    def start_job(self, operation, finished):
        self.job = Job(operation, self)
        self.job.finished.connect(lambda: self.finish_job(finished))
        self.query.setEnabled(False)
        self.search_button.setEnabled(False)
        self.source.setEnabled(False)
        self.installed_button.setEnabled(False)
        self.suggestions.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.list.setEnabled(False)
        self.install_button.setEnabled(False)
        self.progress.show()
        self.job.start()

    def finish_job(self, finished):
        job, self.job = self.job, None
        self.query.setEnabled(True)
        self.search_button.setEnabled(True)
        self.source.setEnabled(True)
        self.installed_button.setEnabled(True)
        self.suggestions.setEnabled(True)
        self.refresh_button.setEnabled(True)
        self.list.setEnabled(True)
        self.progress.hide()
        was_searching, self.searching = self.searching, False
        if self.closing:
            job.deleteLater()
            self.close()
            return
        if was_searching and self.pending_search:
            self.pending_search = False
            job.deleteLater()
            self.start_search()
            return
        if not was_searching or self.query.text().strip() == self.term:
            finished(job.value, job.error)
        job.deleteLater()
        self.show_selection()

    def decorate_source(self, item, source):
        glyph, tint = {
            'apt': ('archive', '#80b2fa'),
            'flatpak': ('folder-open', '#a897f0'),
            'snap': ('tray-arrow-down', '#e9a981'),
        }.get(source, ('archive', '#a3adbd'))
        item.setIcon(1, icon('regular', glyph, self.theme['text'], tint, self.theme['text']))

    def refresh_source_glyphs(self):
        for index in range(self.list.topLevelItemCount()):
            item = self.list.topLevelItem(index)
            self.decorate_source(item, item.data(0, Qt.ItemDataRole.UserRole).source)

    def search_finished(self, results, error):
        if error:
            self.status.setText(error)
            return
        self.source_status.setText(' • '.join(result.status for result in results.values()))
        apt = results.get('apt')
        needs_refresh = apt is not None and apt.needs_refresh
        self.refresh_button.setVisible(needs_refresh)
        self.list.clear()
        packages = (package for result in results.values() for package in result.packages)
        ranked = rank(packages, self.term, limit=None)
        for package in ranked[:300] if self.installed_only else ranked:
            item = QTreeWidgetItem([package.name, package.origin,
                                    'Installed' if package.installed else 'Available'])
            for column in range(3):
                item.setToolTip(column, item.text(column))
            item.setData(0, Qt.ItemDataRole.UserRole, package)
            self.decorate_source(item, package.source)
            self.list.addTopLevelItem(item)
        count = self.list.topLevelItemCount()
        if self.installed_only:
            suffix = ' · Refine the filter to see more' if len(ranked) > count else ''
            self.status.setText(f'{count} of {len(ranked)} matching installed packages{suffix}'
                                if count else 'No matching installed software.')
            if count:
                self.list.setCurrentItem(self.list.topLevelItem(0))
        elif count:
            self.status.setText(f'{count} result' + ('s' if count != 1 else ''))
            self.list.setCurrentItem(self.list.topLevelItem(0))
        elif needs_refresh:
            self.status.setText('Connect to the internet and refresh to find system packages.')
        elif self.term:
            self.status.setText('No matching software. Try a different name or source.')
        else:
            self.status.setText('Search for an app or package.')

    def start_refresh(self):
        if self.job:
            return
        self.refreshing = True
        self.status.setText('Refreshing system packages…')
        self.start_job(refresh_apt, self.refresh_finished)

    def refresh_finished(self, _, error):
        self.refreshing = False
        if error:
            self.status.setText(f'Could not refresh system packages. {error}')
            return
        self.start_search()

    def confirm_install(self):
        package = self.selected()
        if self.job or not package or package.installed or package.classic:
            return
        scope = package.origin if package.source == 'flatpak' else f'{package.origin} · System-wide'
        if not themed_prompt(self, 'Install software',
                             f'Install {package.name}?\n\n{package.identifier}\n{scope}',
                             'Install', 'Cancel'):
            return
        self.installing = True
        self.status.setText(f'Installing {package.name}…')
        self.start_job(lambda: install(package), lambda _, error: self.install_finished(package, error))

    def install_finished(self, package, error):
        self.installing = False
        if error:
            self.status.setText(f'Could not install {package.name}.')
            themed_prompt(self, 'Installation failed', error, 'OK')
            return
        item = self.list.currentItem()
        if item:
            item.setData(0, Qt.ItemDataRole.UserRole, replace(package, installed=True))
            item.setText(2, 'Installed')
            item.setToolTip(2, 'Installed')
        self.status.setText(f'{package.name} is installed.')

    def closeEvent(self, event):
        if self.searching:
            self.closing = True
            self.hide()
            event.ignore()
        elif self.job:
            if self.refreshing:
                self.status.setText('Package refresh is still running.')
            else:
                self.status.setText('Installation is still running.' if self.installing else 'Search is still running.')
            event.ignore()
        else:
            super().closeEvent(event)


def main():
    app = QApplication(sys.argv[:1])
    app.setStyle('Fusion')
    app.setApplicationName('Mellipi Software')
    app.setDesktopFileName('mellipi-software')
    window = SoftwareWindow()
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
