"""Mellipi Software, a native browser for the system's configured app sources."""
from dataclasses import replace
import os
import sys

os.environ['ORBIT_QT'] = '6'
os.environ['QT_WAYLAND_SHELL_INTEGRATION'] = 'xdg-shell'
os.environ.pop('QT_WAYLAND_DISABLE_WINDOWDECORATION', None)

from PyQt6.QtCore import QSize, QSignalBlocker, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QShortcut, QIcon, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QBoxLayout, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QPushButton, QSizePolicy, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from qt_app import AppWindow, themed_prompt
from files_icons import icon
from software_sources import (APPSTREAM_CLI, APT_GET, BROWSE_CATEGORIES, PKEXEC, SOURCES, AuthorizationDeclined,
                              available_updates, browse_system_apps, can_manage, executable, friendly_error, install,
                              installed_software, manage, rank, refresh_apt, search)


class Job(QThread):
    sourceReady = pyqtSignal(str, object)
    phaseChanged = pyqtSignal(str)
    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation
        self.value = None
        self.error = ''
        self.authorization_declined = False

    def run(self):
        try:
            self.value = self.operation()
        except Exception as error:
            self.authorization_declined = isinstance(error, AuthorizationDeclined)
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
        self.checking_updates = False
        self.updates_only = False
        self.operation_notice = ''
        self.transaction_error = ''
        self.term = ''
        self.active_category = ''
        self.installed_only = False
        self.searching = False
        self.pending_search = False
        self.closing = False
        layout = self.content

        toolbar = self.toolbar = QGridLayout()
        toolbar.setColumnStretch(0, 1)
        self.query = QLineEdit()
        self.query.setPlaceholderText('Search software')
        self.query.setAccessibleName('Search software')
        self.query.setMaxLength(120)
        self.query.setClearButtonEnabled(True)
        self.query.returnPressed.connect(self.start_search)
        toolbar.addWidget(self.query, 0, 0)
        self.source = QComboBox()
        self.source.setAccessibleName('Software source')
        self.source.addItem('All sources', '')
        for key, name in SOURCES.items():
            self.source.addItem(name, key)
        self.source.currentIndexChanged.connect(self.change_source)
        self.search_button = QPushButton()
        self.search_button.setAccessibleName('Search software')
        self.search_button.setToolTip('Search software')
        self.search_button.setMinimumSize(32, 32)
        self.search_button.setProperty('mellipiSymbolicIcon', 'edit-find')
        self.search_button.clicked.connect(self.start_search)
        toolbar.addWidget(self.search_button, 0, 1)
        self.check_button = QPushButton('Check for updates')
        self.check_button.setObjectName('checkUpdates')
        self.check_button.setAccessibleName('Check for updates')
        self.check_button.setToolTip('Check configured sources without installing updates')
        self.check_button.setProperty('mellipiSymbolicIcon', 'view-refresh')
        self.check_button.clicked.connect(self.start_check_updates)
        toolbar.addWidget(self.check_button, 0, 2)
        layout.addLayout(toolbar)
        self.filters = QGridLayout()
        self.filters_are_stacked = None
        self.installed_button = QPushButton('Installed only')
        self.installed_button.setObjectName('installedFilter')
        self.installed_button.setCheckable(True)
        self.installed_button.setToolTip('View what is already installed on this computer')
        self.installed_button.toggled.connect(self.change_view)
        self.category = QComboBox(self)
        self.category.setAccessibleName('Browse system apps by category')
        self.category.setToolTip('Browse apps from the local system package catalog')
        self.category.addItem('Categories', '')
        for key, name in BROWSE_CATEGORIES.items():
            self.category.addItem(name, key)
        self.category_available = executable(APPSTREAM_CLI)
        self.category.setVisible(self.category_available)
        self.category.currentIndexChanged.connect(self.change_category)
        layout.addLayout(self.filters)
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
        actions = QHBoxLayout()
        actions.addWidget(self.install_button)
        self.update_button = QPushButton('Update')
        self.update_button.setObjectName('install')
        self.update_button.setProperty('mellipiSymbolicIcon', 'view-refresh')
        self.update_button.setToolTip('Install the available update from this package source')
        self.update_button.clicked.connect(lambda: self.confirm_manage('update'))
        actions.addWidget(self.update_button)
        self.remove_button = QPushButton('Remove')
        self.remove_button.setProperty('mellipiSymbolicIcon', 'edit-delete')
        self.remove_button.clicked.connect(lambda: self.confirm_manage('remove'))
        actions.addWidget(self.remove_button)
        panel.addLayout(actions)
        layout.addWidget(self.detail)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName('Software operation in progress')
        self.progress.setFixedHeight(4)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.transaction_row = QWidget()
        transaction_controls = QHBoxLayout(self.transaction_row)
        transaction_controls.setContentsMargins(0, 0, 0, 0)
        self.transaction_status = label(wrap=True)
        self.transaction_status.setAccessibleName('Package transaction status')
        transaction_controls.addWidget(self.transaction_status, 1)
        self.transaction_details = QPushButton('Details')
        self.transaction_details.clicked.connect(self.show_transaction_error)
        self.transaction_details.hide()
        transaction_controls.addWidget(self.transaction_details)
        self.transaction_hide = QPushButton('Hide')
        self.transaction_hide.setAccessibleName('Hide transaction receipt')
        self.transaction_hide.clicked.connect(self.hide_transaction_view)
        self.transaction_hide.hide()
        transaction_controls.addWidget(self.transaction_hide)
        self.transaction_row.hide()
        layout.addWidget(self.transaction_row)
        self.status = label(wrap=True)
        self.status.hide()
        self.status.setAccessibleName('Software status')
        layout.addWidget(self.status)
        self.source_status = label(wrap=True)
        self.source_status.setObjectName('muted')
        self.source_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        source_info = self.source_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        source_info.addWidget(self.source_status, 1)
        self.refresh_button = QPushButton()
        self.refresh_button.setToolTip('Refresh the system package index and check again. Administrator approval is required.')
        self.refresh_button.setMinimumSize(32, 32)
        self.refresh_button.setAccessibleName('Refresh the system package index')
        self.refresh_button.setProperty('mellipiSymbolicIcon', 'package-x-generic')
        self.refresh_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.refresh_button.clicked.connect(self.start_refresh)
        self.refresh_button.hide()
        source_info.addWidget(self.refresh_button)
        # Source maintenance and its status belong together above the results;
        # selection actions stay with the selected package in both modes.
        layout.insertLayout(layout.indexOf(self.list), source_info)

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
        _, _, control_spacing = self.layout_spacing()
        self.toolbar.setSpacing(control_spacing)
        self.filters.setSpacing(control_spacing)
        available = self.viewport_width()
        wide = available >= max(600, self.fontMetrics().horizontalAdvance('Mellipi Software') * 5)
        combo_controls = (self.source, self.category) if self.category_available else (self.source,)
        combo_widths = []
        for combo in combo_controls:
            # The themed dropdown reserves both input padding and a separate arrow column.
            label_width = max(combo.fontMetrics().horizontalAdvance(combo.itemText(i)) for i in range(combo.count()))
            width = label_width + 64
            combo.setMinimumWidth(width)
            combo_widths.append(width)
        stacked = sum(combo_widths) + self.installed_button.sizeHint().width() + control_spacing * len(combo_widths) > available
        if self.filters_are_stacked is not stacked:
            self.filters_are_stacked = stacked
            for control in (self.source, self.installed_button, self.category):
                self.filters.removeWidget(control)
            self.filters.addWidget(self.source, 0, 0)
            self.filters.addWidget(self.category, 0, 1 if stacked else 2)
            self.filters.addWidget(self.installed_button, 1 if stacked else 0, 0 if stacked else 1,
                                   alignment=Qt.AlignmentFlag.AlignLeft)
            self.filters.setColumnStretch(3, 1)
            first, last = (self.category, self.installed_button) if stacked else (self.installed_button, self.category)
            self.setTabOrder(self.source, first)
            self.setTabOrder(first, last)
        self.source.setVisible(not self.updates_only)
        self.installed_button.setVisible(not self.updates_only)
        self.category.setVisible(self.category_available and not self.updates_only)
        direction = QBoxLayout.Direction.LeftToRight if wide else QBoxLayout.Direction.TopToBottom
        self.detail_layout.setDirection(QBoxLayout.Direction.LeftToRight if self.updates_only else direction)
        glyph = max(16, min(24, self.theme['font_size'] + 2))
        control_height = max(glyph + 14, self.query.sizeHint().height(),
                             self.source.sizeHint().height(), self.installed_button.sizeHint().height(),
                             self.category.sizeHint().height(), self.check_button.sizeHint().height())
        for control in (self.query, self.source, self.installed_button, self.category, self.check_button):
            if control.minimumHeight() != control_height:
                control.setFixedHeight(control_height)
        for button in (self.search_button, self.refresh_button, self.check_button):
            button.setIconSize(QSize(glyph, glyph))
        self.search_button.setFixedSize(control_height, control_height)
        # Compact controls in place instead of moving the list down by two rows.
        field_width = self.query.fontMetrics().horizontalAdvance(self.query.placeholderText()) + 24
        check_width = self.check_button.fontMetrics().horizontalAdvance('Check for updates') + glyph + 30
        compact_tools = field_width + control_height + check_width + 2 * control_spacing > available
        self.check_button.setText('' if compact_tools else 'Check for updates')
        self.check_button.setMinimumWidth(control_height)

        # Keep source status and refresh together. The accessible name and
        # tooltip carry the action text when the label would crowd the list.
        self.refresh_button.setText('Refresh system index' if self.updates_only and wide else '')
        refresh_width = max(control_height, self.refresh_button.sizeHint().width()) if self.refresh_button.text() else control_height
        self.refresh_button.setFixedSize(refresh_width, control_height)
        self.suggestions.setVisible(wide and not self.term and not self.installed_only and not self.updates_only
                                    and not self.category.currentData())
        self.fit_result_columns()

    def set_status(self, text):
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def fit_result_columns(self):
        width = self.list.viewport().width()
        if width <= 0:
            return
        # Keep name, source and state visible without a horizontal scrollbar.
        font = self.list.fontMetrics()
        status = min(round(width * .29), font.horizontalAdvance('Update available' if self.updates_only else 'Available') + 24)
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
        info = [] if self.updates_only else [package.identifier, package.origin]
        if self.updates_only and package.update_version:
            info.append(f'{package.version} → {package.update_version}' if package.version else package.update_version)
        elif package.version:
            info.append(package.version)
        if package.branch and not self.updates_only:
            info.append(package.branch)
        self.info.setText(' · '.join(info))
        self.info.setVisible(bool(info))
        self.info.setToolTip(f'{package.identifier} · {package.origin}')
        description = package.description
        if package.classic:
            description = f'{description}\nClassic confinement is required for this package.'.lstrip()
        self.description.setText(description)
        self.description.setVisible(bool(description) and not self.updates_only)
        self.install_button.setVisible(not package.installed and not (self.installed_only or self.updates_only))
        for action, button in (('update', self.update_button), ('remove', self.remove_button)):
            allowed = self.installed_only or (self.updates_only and action == 'update')
            button.setVisible(package.installed and allowed and
                              (not self.updates_only or can_manage(package, action)))
            button.setEnabled(not self.job and can_manage(package, action))
        self.remove_button.setToolTip('Remove the selected app' if can_manage(package, 'remove')
                                      else 'This app is protected or cannot be removed from Software')
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

    def reset_category(self):
        with QSignalBlocker(self.category):
            self.category.setCurrentIndex(0)
        self.query.setPlaceholderText(
            'Filter installed software' if self.installed_only else 'Search software')
        self.query.setAccessibleName(self.query.placeholderText())

    def change_category(self, *_):
        if self.category.currentData():
            with QSignalBlocker(self.source):
                self.source.setCurrentIndex(self.source.findData('apt'))
            self.query.clear()
            self.query.setPlaceholderText('Filter this category')
            self.query.setAccessibleName(self.query.placeholderText())
        else:
            self.reset_category()
        self.list.clear()
        self.start_search()

    def change_source(self, *_):
        if self.source.currentData() != 'apt':
            self.reset_category()
        self.list.clear()
        self.start_search()

    def change_view(self, installed):
        self.installed_only = installed
        self.reset_category()
        self.category.setEnabled(not installed)
        self.list.clear()
        self.source_status.clear()
        self.source_status.hide()
        self.refresh_button.hide()
        self.set_status('Reading installed software…' if installed else 'Searching software…')
        self.start_search()

    def start_search(self, *_):
        if self.job:
            if self.searching:self.pending_search = True
            return
        self.updates_only = False
        self.list.setHeaderLabels(['Software', 'Source', 'Status'])
        self.term = self.query.text().strip()
        self.active_category = category = self.category.currentData() if not self.installed_only else ''
        source = self.source.currentData()
        sources = (source,) if source else tuple(SOURCES)
        self.fit_layout()
        if self.installed_only:
            self.set_status('Reading installed software…')
        elif category:
            self.set_status(f'Browsing {BROWSE_CATEGORIES[category]}…')
        elif self.term:
            self.set_status(f'Searching for “{self.term}”…')
        self.searching = True
        self.search_results = {}
        term = self.term
        operation = installed_software if self.installed_only else search
        def load():
            if category:
                return browse_system_apps(category, term)
            return operation(term, sources, job.sourceReady.emit)
        job = Job(load, self)
        job.sourceReady.connect(self.source_finished)
        self.job = job
        job.finished.connect(lambda: self.finish_job(self.search_finished))
        self.install_button.setEnabled(False)
        self.update_button.setEnabled(False)
        self.remove_button.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.check_button.setEnabled(False)
        self.progress.show()
        job.start()

    def source_finished(self, source, result):
        if self.closing or self.pending_search or self.query.text().strip() != self.term:
            return
        self.search_results[source] = result
        self.search_finished(self.search_results, '')
        if self.searching and not self.operation_notice:
            self.set_status('Searching remaining sources…')

    def start_job(self, operation, finished, transaction_title=''):
        if transaction_title:
            job = Job(lambda: operation(job.phaseChanged.emit), self)
            self.job = job
            job.phaseChanged.connect(lambda phase: self.show_transaction_phase(job, transaction_title, phase))
            self.transaction_error = ''
            self.transaction_details.hide()
            self.transaction_hide.setText('Minimize')
            self.transaction_hide.setAccessibleName('Minimize Software while the transaction continues')
            self.transaction_hide.show()
            self.transaction_status.setText(f'{transaction_title} · Preparing…')
            self.transaction_row.show()

            def report(value, error):
                self.finish_transaction(transaction_title, error, job.authorization_declined)
                finished(value, error)
            callback = report
        else:
            self.job = Job(operation, self)
            callback = finished
        self.job.finished.connect(lambda: self.finish_job(callback))
        self.query.setEnabled(False)
        self.search_button.setEnabled(False)
        self.source.setEnabled(False)
        self.installed_button.setEnabled(False)
        self.category.setEnabled(False)
        self.suggestions.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.check_button.setEnabled(False)
        self.list.setEnabled(False)
        self.install_button.setEnabled(False)
        self.update_button.setEnabled(False)
        self.remove_button.setEnabled(False)
        self.progress.show()
        self.job.start()

    def hide_transaction_view(self):
        if self.job is not None and self.transaction_hide.text() == 'Minimize':
            self.showMinimized()
        else:
            self.transaction_row.hide()

    def show_transaction_phase(self, job, title, phase):
        if self.job is not job:
            return
        state = {
            'authorization': 'Waiting for administrator authorization…',
            'applying': 'Applying changes…',
            'system-flatpak': 'Applying changes; administrator authorization may be requested…',
        }[phase]
        self.transaction_status.setText(f'{title} · {state}')

    def finish_transaction(self, title, error, authorization_declined):
        self.transaction_error = error
        state = ('Authorization not granted' if authorization_declined else
                 'Could not complete' if error else 'Finished')
        self.transaction_status.setText(f'{title} · {state}')
        self.transaction_details.setVisible(bool(error))
        self.transaction_hide.setText('Hide')
        self.transaction_hide.setAccessibleName('Hide transaction receipt')

    def show_transaction_error(self):
        if self.transaction_error:
            themed_prompt(self, 'Software operation details', self.transaction_error, 'OK')

    def finish_job(self, finished):
        job, self.job = self.job, None
        self.query.setEnabled(True)
        self.search_button.setEnabled(True)
        self.source.setEnabled(True)
        self.installed_button.setEnabled(True)
        self.category.setEnabled(not self.installed_only)
        self.suggestions.setEnabled(True)
        self.refresh_button.setEnabled(True)
        self.check_button.setEnabled(True)
        self.list.setEnabled(True)
        self.progress.hide()
        was_searching, self.searching = self.searching, False
        if self.closing:
            self.checking_updates = False
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
            self.set_status(error)
            return
        self.source_status.setText(' • '.join(result.status for result in results.values()))
        self.source_status.setVisible(bool(self.source_status.text()))
        apt = results.get('apt')
        needs_refresh = apt is not None and apt.needs_refresh
        refresh_available = executable(APT_GET) and executable(PKEXEC)
        self.refresh_button.setVisible(refresh_available and
                                       (needs_refresh or bool(self.active_category) or (self.installed_only and
                                        self.source.currentData() in ('', 'apt'))))
        self.list.clear()
        packages = (package for result in results.values() for package in result.packages)
        ranked = list(packages) if self.active_category else rank(packages, self.term, limit=None)
        for package in ranked[:300] if self.installed_only or self.active_category else ranked:
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
            self.set_status(f'{count} of {len(ranked)} matching installed packages{suffix}'
                                if count else 'No matching installed software.')
            if count:
                self.list.setCurrentItem(self.list.topLevelItem(0))
        elif self.active_category and not needs_refresh:
            suffix = ' · Filter to see more' if len(ranked) > count else ''
            self.set_status(f'{count} of {len(ranked)} system apps{suffix}'
                            if count else 'No matching apps in this category.')
            if count:
                self.list.setCurrentItem(self.list.topLevelItem(0))
        elif count:
            self.set_status(f'{count} result' + ('s' if count != 1 else ''))
            self.list.setCurrentItem(self.list.topLevelItem(0))
        elif needs_refresh:
            self.set_status('Connect to the internet and refresh to find system packages.')
        elif self.term:
            self.set_status('No matching software. Try a different name or source.')
        else:
            self.set_status('')
        if self.operation_notice:
            self.set_status(self.operation_notice)
            if not self.searching:
                self.operation_notice = ''

    def start_check_updates(self):
        if self.job:
            return
        with QSignalBlocker(self.installed_button):
            self.installed_button.setChecked(False)
        self.installed_only = False
        self.updates_only = True
        self.list.setHeaderLabels(['Software', 'Source', 'Version'])
        self.checking_updates = True
        self.reset_category()
        self.query.clear()
        self.list.clear()
        self.source_status.clear()
        self.source_status.hide()
        self.refresh_button.hide()
        self.set_status('Checking for updates…')
        self.fit_layout()
        self.start_job(available_updates, self.updates_finished)

    def updates_finished(self, results, error):
        self.checking_updates = False
        if error:
            self.set_status(f'Could not check for updates. {error}')
            return
        self.source_status.setText(' • '.join(results[source].status for source in SOURCES
                                            if source in results))
        self.source_status.setVisible(bool(self.source_status.text()))
        self.refresh_button.setVisible('apt' in results and bool(results['apt'].checked or
                                       results['apt'].check_failed) and
                                       executable(APT_GET) and executable(PKEXEC))
        self.list.clear()
        packages = sorted((p for result in results.values() for p in result.packages),
                          key=lambda p: (p.name.casefold(), p.origin, p.branch))
        for package in packages:
            version = package.update_version or 'Update available'
            versions = f'Installed: {package.version} · Available: {version}' if package.version and package.update_version else version
            source_label = 'APT' if package.source == 'apt' else package.origin
            item = QTreeWidgetItem([package.name, source_label, version])
            item.setToolTip(0, package.name)
            item.setToolTip(1, package.origin)
            item.setToolTip(2, versions)
            item.setData(2, Qt.ItemDataRole.AccessibleDescriptionRole, versions)
            item.setData(0, Qt.ItemDataRole.UserRole, package)
            self.decorate_source(item, package.source)
            self.list.addTopLevelItem(item)
        if packages:
            self.list.setCurrentItem(self.list.topLevelItem(0))
        incomplete = any(result.check_failed for result in results.values())
        checked = any(result.checked for result in results.values())
        if packages:
            status = f'{len(packages)} update' + ('' if len(packages) == 1 else 's') + ' available.'
        elif checked:
            status = 'No updates found in checked sources.'
        else:
            status = 'No source could be checked.' if incomplete else 'No selected sources are available.'
        if checked and incomplete:
            status += ' Check incomplete.'
        if self.operation_notice:
            status = f'{self.operation_notice} {status}'
            self.operation_notice = ''
        self.set_status(status)

    def start_refresh(self):
        if self.job:
            return
        self.refreshing = True
        self.set_status('')
        self.start_job(refresh_apt, self.refresh_finished, 'Refresh system package index')

    def refresh_finished(self, _, error):
        self.refreshing = False
        if error:
            return
        if self.updates_only:
            self.start_check_updates()
        else:
            self.start_search()

    def confirm_manage(self, action):
        package = self.selected()
        if (self.job or not (self.installed_only or (self.updates_only and action == 'update'))
                or not package or not can_manage(package, action)):
            return
        title = action.title()
        message = f'{title} {package.name}?\n\n{package.identifier} · {package.origin}'
        if action == 'remove':
            message += '\n\nClose the app before removing it. Personal files are not selected for removal.'
        elif package.source == 'apt':
            message += '\n\nSoftware uses your current package index. Refresh system packages first if needed.'
        if not themed_prompt(self, f'{title} software', message, title, 'Cancel'):
            return
        self.set_status('')
        self.start_job(lambda observe: manage(package, action, observe),
                       lambda changed, error: self.manage_finished(package, action, changed, error),
                       f'{title} {package.name}')

    def manage_finished(self, package, action, changed, error):
        if error:
            return
        if action == 'remove':
            self.operation_notice = f'{package.name} was removed.'
        elif changed is False:
            self.operation_notice = f'{package.name} is already current in the system package index.'
        elif changed is True:
            self.operation_notice = f'{package.name} was updated.'
        else:
            self.operation_notice = f'Update check completed for {package.name}.'
        if self.updates_only:
            self.start_check_updates()
        else:
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
        self.set_status('')
        self.start_job(lambda observe: install(package, observe), lambda _, error: self.install_finished(package, error),
                       f'Install {package.name}')

    def install_finished(self, package, error):
        self.installing = False
        if error:
            return
        item = self.list.currentItem()
        if item:
            item.setData(0, Qt.ItemDataRole.UserRole, replace(package, installed=True))
            item.setText(2, 'Installed')
            item.setToolTip(2, 'Installed')
        self.set_status(f'{package.name} is installed.')

    def closeEvent(self, event):
        if self.searching or self.checking_updates:
            self.closing = True
            self.hide()
            event.ignore()
        elif self.job:
            # Keep the package-manager owner and its receipt alive in the taskbar.
            event.ignore()
            self.showMinimized()
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
