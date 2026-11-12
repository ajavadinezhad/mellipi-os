"""Mellipi Software, a native browser for the system's configured app sources."""
from dataclasses import replace
import os
import sys

os.environ['ORBIT_QT'] = '5'
os.environ['QT_WAYLAND_SHELL_INTEGRATION'] = 'xdg-shell'
os.environ.pop('QT_WAYLAND_DISABLE_WINDOWDECORATION', None)

from PyQt5.QtCore import Qt, QThread, QTimer
from PyQt5.QtGui import QIcon, QKeySequence
from PyQt5.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QShortcut, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from app_palette import colors
from installed_launcher import user_environment
from preferences import Preferences
from software_sources import SOURCES, friendly_error, install, rank, search


class Job(QThread):
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
    widget.setTextFormat(Qt.PlainText)
    widget.setWordWrap(wrap)
    return widget


class SoftwareWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Software — Mellipi')
        self.setWindowIcon(QIcon.fromTheme('system-software-install'))
        self.resize(790, 560)
        self.setMinimumSize(480, 420)
        self.job = None
        self.installing = False
        self.term = ''
        self.setCentralWidget(QWidget())
        layout = QVBoxLayout(self.centralWidget())
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        title = label('Software')
        title.setObjectName('heading')
        layout.addWidget(title)

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
        toolbar.addWidget(self.source)
        self.search_button = QPushButton('Search')
        self.search_button.clicked.connect(self.start_search)
        toolbar.addWidget(self.search_button)
        layout.addLayout(toolbar)
        self.search_shortcut = QShortcut(QKeySequence.Find, self)
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
        self.list.setAlternatingRowColors(True)
        self.list.setColumnWidth(0, 300)
        self.list.setColumnWidth(1, 160)
        self.list.currentItemChanged.connect(self.show_selection)
        layout.addWidget(self.list, 1)

        self.detail = QFrame()
        self.detail.setObjectName('detail')
        panel = QHBoxLayout(self.detail)
        panel.setContentsMargins(14, 12, 14, 12)
        description = QVBoxLayout()
        self.name = label()
        self.name.setObjectName('selectionTitle')
        self.info = label(wrap=True)
        self.description = label(wrap=True)
        self.info.setObjectName('muted')
        for row in (self.name, self.info, self.description):
            row.setTextInteractionFlags(Qt.TextSelectableByMouse)
            description.addWidget(row)
        panel.addLayout(description, 1)
        self.install_button = QPushButton('Install')
        self.install_button.setObjectName('install')
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
        self.source_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.source_status)

        self.apply_palette()
        self.query.setFocus()
        self.show_selection()
        QTimer.singleShot(0, self.start_search)

    def apply_palette(self):
        palette = colors(Preferences(user_environment()['ORBIT_SETTINGS_FILE']))
        self.setStyleSheet('''
            QMainWindow, QDialog { background: %(background)s; color: %(text)s; }
            QLabel { color: %(text)s; }
            QLabel#heading { font-size: 24px; font-weight: 600; }
            QLabel#selectionTitle { font-size: 15px; font-weight: 600; }
            QLabel#muted { color: %(muted)s; }
            QFrame#detail { background: %(surface)s; border: 1px solid %(border)s; border-radius: 8px; }
            QLineEdit, QPushButton, QComboBox {
                color: %(text)s; background: %(surface)s; border: 1px solid %(border)s;
                border-radius: 6px; padding: 7px 10px; min-height: 19px;
            }
            QLineEdit:focus, QPushButton:focus, QComboBox:focus { border-color: %(accent)s; }
            QPushButton:hover { background: %(hover)s; }
            QPushButton#install:enabled { background: %(accent)s; color: %(accent_text)s; }
            QPushButton:disabled, QLineEdit:disabled, QComboBox:disabled { color: %(faint)s; }
            QAbstractItemView {
                color: %(text)s; background: %(surface)s; alternate-background-color: %(raised)s;
                border: 1px solid %(border)s; selection-background-color: %(selected_surface)s;
                selection-color: %(text)s;
            }
            QTreeWidget::item { padding: 5px 4px; }
            QHeaderView::section { background: %(raised)s; color: %(text)s; padding: 6px; border: 0; }
            QProgressBar { background: %(surface)s; border: 0; }
            QProgressBar::chunk { background: %(accent)s; }
        ''' % palette)

    def selected(self):
        item = self.list.currentItem()
        return item.data(0, Qt.UserRole) if item else None

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
        self.description.setText(package.description)
        self.install_button.setEnabled(not package.installed and not package.classic and not self.job)
        if package.installed:
            self.install_button.setText('Installed')
        elif package.classic:
            self.install_button.setText('Classic confinement required')
        else:
            self.install_button.setText('Install')

    def search_for(self, term):
        self.query.setText(term)
        self.start_search()

    def start_search(self, *_):
        if self.job:
            return
        self.term = self.query.text().strip()
        source = self.source.currentData()
        sources = (source,) if source else tuple(SOURCES)
        self.suggestions.setVisible(not self.term)
        if self.term:
            self.status.setText(f'Searching for “{self.term}”…')
        self.start_job(lambda: search(self.term, sources), self.search_finished)

    def start_job(self, operation, finished):
        self.job = Job(operation, self)
        self.job.finished.connect(lambda: self.finish_job(finished))
        self.query.setEnabled(False)
        self.search_button.setEnabled(False)
        self.source.setEnabled(False)
        self.suggestions.setEnabled(False)
        self.list.setEnabled(False)
        self.install_button.setEnabled(False)
        self.progress.show()
        self.job.start()

    def finish_job(self, finished):
        job, self.job = self.job, None
        self.query.setEnabled(True)
        self.search_button.setEnabled(True)
        self.source.setEnabled(True)
        self.suggestions.setEnabled(True)
        self.list.setEnabled(True)
        self.progress.hide()
        finished(job.value, job.error)
        job.deleteLater()
        self.show_selection()

    def search_finished(self, results, error):
        if error:
            self.status.setText(error)
            return
        self.source_status.setText(' • '.join(result.status for result in results.values()))
        self.list.clear()
        packages = (package for result in results.values() for package in result.packages)
        for package in rank(packages, self.term, limit=None):
            item = QTreeWidgetItem([package.name, package.origin,
                                    'Installed' if package.installed else 'Available'])
            item.setData(0, Qt.UserRole, package)
            self.list.addTopLevelItem(item)
        count = self.list.topLevelItemCount()
        if count:
            self.status.setText(f'{count} result' + ('s' if count != 1 else ''))
            self.list.setCurrentItem(self.list.topLevelItem(0))
        elif self.term:
            self.status.setText('No matching software. Try a different name or source.')
        else:
            self.status.setText('Search for an app or package.')

    def confirm_install(self):
        package = self.selected()
        if self.job or not package or package.installed or package.classic:
            return
        scope = package.origin if package.source == 'flatpak' else f'{package.origin} · System-wide'
        box = QMessageBox(QMessageBox.Question, 'Install software',
                          f'Install {package.name}?\n\n{package.identifier}\n{scope}',
                          QMessageBox.Yes | QMessageBox.Cancel, self)
        box.setTextFormat(Qt.PlainText)
        box.setDefaultButton(QMessageBox.Cancel)
        if box.exec_() != QMessageBox.Yes:
            return
        self.installing = True
        self.status.setText(f'Installing {package.name}…')
        self.start_job(lambda: install(package), lambda _, error: self.install_finished(package, error))

    def install_finished(self, package, error):
        self.installing = False
        if error:
            self.status.setText(f'Could not install {package.name}.')
            box = QMessageBox(QMessageBox.Warning, 'Installation failed', error, QMessageBox.Ok, self)
            box.setTextFormat(Qt.PlainText)
            box.exec_()
            return
        item = self.list.currentItem()
        if item:
            item.setData(0, Qt.UserRole, replace(package, installed=True))
            item.setText(2, 'Installed')
        self.status.setText(f'{package.name} is installed.')

    def closeEvent(self, event):
        if self.job:
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
    return app.exec_()


if __name__ == '__main__':
    raise SystemExit(main())
