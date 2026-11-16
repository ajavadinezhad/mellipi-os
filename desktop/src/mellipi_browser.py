"""Mellipi's Qt 6 browser chrome, running on the system Qt WebEngine."""
import argparse
from collections import deque
import fcntl
import json
import os
import re
import shutil
import stat
import sys
import weakref
import tempfile
from pathlib import Path
from urllib.parse import urlencode

from PyQt6.QtCore import QLocale, QMimeDatabase, QProcess, QSize, QUrl, Qt
from PyQt6.QtGui import QColor, QDesktopServices, QKeySequence, QShortcut
from PyQt6.sip import isdeleted
from PyQt6.QtWidgets import (
    QApplication, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)

from file_chooser import FileChooser
from installed_launcher import user_environment
from qt_app import AppWindow, symbolic_icon, themed_prompt


def web_url(url):
    """Accept only HTTP(S) with a host and no address-bar credentials."""
    return (
        url.isValid() and url.scheme().lower() in ('http', 'https')
        and bool(url.host()) and not url.userInfo()
    )


def address_url(value):
    """Interpret explicit URLs, host names and search terms without file access."""
    value = value.strip()
    if not value or len(value) > 4096 or any(ord(c) < 32 for c in value):
        return None
    if re.match(r'^https?://', value, re.I):
        url = QUrl(value)
        return url if web_url(url) else None
    if value.startswith(('/', '\\')):
        return None
    first = value.split('/', 1)[0]
    # Distinguish localhost:3000 and example.com:8443 from arbitrary schemes.
    host = re.match(r'^(?:localhost|(?:[^\.\s:/]+\.)+[^\.\s:/]+|\[[0-9a-f:]+\])(?::\d+)?$', first, re.I)
    if host and not any(c.isspace() for c in first):
        url = QUrl('https://' + value)
        return url if web_url(url) else None
    if re.match(r'^[A-Za-z][\w+.-]*:', value):
        return None
    return QUrl('https://duckduckgo.com/?' + urlencode({'q': value}))


class Bookmarks:
    """Small, local bookmark store shared by ordinary Browser windows."""

    MAX_ITEMS = 100
    MAX_BYTES = 500_000

    def __init__(self, path):
        self.path = path

    @staticmethod
    def clean_url(url):
        if not web_url(url):
            return None
        value = url.toString(QUrl.ComponentFormattingOption.FullyEncoded)
        return value if 0 < len(value) <= 4096 else None

    def read(self):
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        except FileNotFoundError:
            return {}
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > self.MAX_BYTES:
                raise ValueError('Bookmark file is not a supported local file.')
            raw = stream.read(self.MAX_BYTES + 1)
        if len(raw) > self.MAX_BYTES:
            raise ValueError('Bookmark file is too large.')
        stored = json.loads(raw)
        if not isinstance(stored, dict) or len(stored) > self.MAX_ITEMS:
            raise ValueError('Invalid bookmark file.')
        return {self.clean_url(QUrl(url)): title[:180] for url, title in stored.items()
                if len(url) <= 4096 and isinstance(title, str) and self.clean_url(QUrl(url))}

    def toggle(self, url, title):
        key = self.clean_url(url)
        if not key:
            raise ValueError('Only HTTP and HTTPS pages can be bookmarked.')
        title = ''.join(c for c in title if c.isprintable())[:180] or url.host()
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        lock = self.path.with_suffix('.lock')
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NONBLOCK | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'rb+') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                raise ValueError('Bookmark lock is not a regular local file.')
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            rows = self.read()
            added = key not in rows
            if added:
                if len(rows) >= self.MAX_ITEMS:
                    raise ValueError('Remove a bookmark before saving another.')
                rows[key] = title
            else:
                del rows[key]
            data = json.dumps(rows, ensure_ascii=False).encode()
            if len(data) > self.MAX_BYTES:
                raise ValueError('Bookmark storage limit reached.')
            fd_tmp, tmp = tempfile.mkstemp(prefix='.bookmarks-', dir=self.path.parent)
            try:
                with os.fdopen(fd_tmp, 'wb') as output:
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(tmp, self.path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        return added


class DownloadRow(QWidget):
    def __init__(self, browser, request, target):
        super().__init__(browser)
        self.request = request
        self.target = target
        self.finished = False
        layout = QHBoxLayout(self)
        details = QVBoxLayout()
        self.name = QLabel(target.name)
        self.name.setTextFormat(Qt.TextFormat.PlainText)
        self.name.setToolTip(str(target))
        self.name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        details.addWidget(self.name)
        self.status = QLabel(objectName='muted')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        details.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setAccessibleName(f'Download progress: {target.name}')
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        details.addWidget(self.progress)
        layout.addLayout(details, 1)
        self.cancel_button = browser.button(layout, 'window-close', 'Cancel download', self.cancel, toolbar=False)
        self.folder_button = browser.button(
            layout, 'folder-open', 'Show in folder', self.show_folder, toolbar=False)
        request.stateChanged.connect(self.update_state)
        request.receivedBytesChanged.connect(self.update_state)
        request.totalBytesChanged.connect(self.update_state)
        request.destroyed.connect(self.request_lost)
        self.update_state()

    def cancel(self):
        if self.request is not None and not self.finished:
            self.request.cancel()

    def show_folder(self):
        if not self.folder_button.isEnabled():
            return
        files = shutil.which('mellipi-files')
        if files and self.target.is_file():
            launched, _pid = QProcess.startDetached(files, ['--select', str(self.target)])
            if launched:
                return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.target.parent))):
            self.status.setText('Could not open the download folder.')

    def request_lost(self, *_):
        self.request = None
        if not self.finished:
            self.apply_state('Download stopped', finished=True)

    def update_state(self, *_):
        request = self.request
        if request is None:
            return
        state = request.state()
        states = request.DownloadState
        if state == states.DownloadCompleted:
            self.apply_state('Saved', finished=True, saved=True)
        elif state == states.DownloadCancelled:
            self.apply_state('Canceled', finished=True)
        elif state == states.DownloadInterrupted:
            reason = request.interruptReasonString().strip()[:180]
            self.apply_state(f'Interrupted: {reason}' if reason else 'Interrupted', finished=True)
        else:
            received, total = request.receivedBytes(), request.totalBytes()
            label = QLocale().formattedDataSize(received)
            if total > 0:
                self.progress.setRange(0, 100)
                self.progress.setValue(max(0, min(100, received * 100 // total)))
                label = f'{label} of {QLocale().formattedDataSize(total)}'
            else:
                self.progress.setRange(0, 0)
            self.apply_state(label if received else 'Starting…')

    def apply_state(self, label, *, finished=False, saved=False):
        self.finished = finished
        self.status.setText(label)
        self.progress.setVisible(not finished)
        self.cancel_button.setVisible(not finished)
        self.folder_button.setVisible(saved)
        self.folder_button.setEnabled(saved)


class Browser(AppWindow):
    MAX_CLOSED_TABS = 16
    MAX_DOWNLOADS = 8
    MAX_DOWNLOAD_ROWS = 48
    DOWNLOAD_NOTICE = 'Download started · Ctrl+J for progress'
    extra_style = """
        QTabWidget::pane { border: 0; background: %(surface)s; }
        QPushButton#browserAction { padding: 4px; }
        QLineEdit#browserAddress { padding: 4px 8px; }
    """

    def __init__(self, engine, private=False):
        super().__init__('Private Browser' if private else 'Mellipi Browser')
        self.setMinimumSize(470, 300)
        self.resize(990, 690)
        self.private = private
        # Keep only page addresses, scoped to this window and never written to
        # disk. In particular, private tabs cannot leak into ordinary windows.
        self.closed_tabs = deque(maxlen=self.MAX_CLOSED_TABS)
        self.bookmarks = None
        self.profile_class, self.Page, self.Request, self.View = engine
        self.profile = self.profile_class(QApplication.instance()) if private else self.profile_class(
            'Mellipi', QApplication.instance())
        if not private:
            env = user_environment()
            storage = Path(env['XDG_DATA_HOME']) / 'mellipi' / 'browser'
            cache = Path(env['XDG_CACHE_HOME']) / 'mellipi' / 'browser'
            storage.mkdir(parents=True, mode=0o700, exist_ok=True)
            cache.mkdir(parents=True, mode=0o700, exist_ok=True)
            self.bookmarks = Bookmarks(storage / 'bookmarks.json')
            self.profile.setPersistentStoragePath(str(storage))
            self.profile.setCachePath(str(cache))
            self.profile.setHttpCacheMaximumSize(96 * 1024 * 1024)
        self.profile.downloadRequested.connect(self.download)
        attrs = self.profile.settings().WebAttribute
        for attr in ('LocalContentCanAccessRemoteUrls', 'LocalContentCanAccessFileUrls',
                     'AllowRunningInsecureContent', 'AllowGeolocationOnInsecureOrigins',
                     'JavascriptCanAccessClipboard', 'JavascriptCanPaste', 'ScreenCaptureEnabled'):
            self.profile.settings().setAttribute(getattr(attrs, attr), False)

        self.toolbar = QGridLayout()
        self.toolbar.setSpacing(6)
        self.navigation = QHBoxLayout()
        self.navigation.setSpacing(4)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(4)
        self.toolbar_buttons = []
        self.narrow_toolbar = None
        self.back = self.button(self.navigation, 'go-previous', 'Back (Alt+Left)', lambda: self.current_action('Back'))
        self.forward = self.button(self.navigation, 'go-next', 'Forward (Alt+Right)', lambda: self.current_action('Forward'))
        self.reload = self.button(self.navigation, 'view-refresh', 'Reload (Ctrl+R)', self.toggle_loading)
        self.address = QLineEdit(objectName="browserAddress")
        self.address.setPlaceholderText('Search or enter an address')
        self.address.setAccessibleName('Address and search')
        self.address.returnPressed.connect(self.navigate)
        self.button(self.actions, 'tab-new', 'New tab (Ctrl+T)', self.add_tab)
        self.button(self.actions, 'edit-find', 'Find in page (Ctrl+F)', self.show_find)
        self.download_button = self.button(self.actions, 'document-save', 'Downloads (Ctrl+J)', self.toggle_downloads)
        if not private:
            self.bookmark_button = self.button(self.actions, 'bookmark-new', 'Bookmarks (Ctrl+D to save or remove)', self.show_bookmarks)
            shortcut = QShortcut(QKeySequence('Ctrl+D'), self)
            shortcut.activated.connect(self.toggle_bookmark)
            self.button(self.actions, 'system-lock-screen', 'New private window (Ctrl+Shift+N)', self.open_private)

        self.content.addLayout(self.toolbar)
        self.update_toolbar_layout()
        self.find_bar = QWidget()
        find_layout = QHBoxLayout(self.find_bar)
        find_layout.setContentsMargins(0, 0, 0, 0)
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText('Find in page')
        self.find_input.setAccessibleName('Find in page')
        self.find_input.setMaxLength(512)
        self.find_input.textChanged.connect(self.find_in_page)
        self.find_input.returnPressed.connect(lambda: self.find_in_page())
        find_layout.addWidget(self.find_input, 1)
        self.find_result = QLabel(objectName='muted')
        find_layout.addWidget(self.find_result)
        self.find_previous = self.button(
            find_layout, 'go-up', 'Previous match', lambda: self.find_in_page(backward=True), toolbar=False)
        self.find_next = self.button(
            find_layout, 'go-down', 'Next match (Enter)', self.find_in_page, toolbar=False)
        self.button(find_layout, 'window-close', 'Close find (Esc)', self.hide_find, toolbar=False)
        self.find_view = None
        self.find_generation = 0
        self.find_bar.hide()
        self.content.addWidget(self.find_bar)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.tab_switched)
        bar = self.tabs.tabBar()
        bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        bar.customContextMenuRequested.connect(self.show_tab_menu)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.tabs)
        self.download_rows = []
        self.download_page = QWidget()
        downloads = QVBoxLayout(self.download_page)
        header = QHBoxLayout()
        header.addWidget(QLabel('Downloads', objectName='windowTitle'), 1)
        self.download_close = self.button(header, 'window-close', 'Close downloads (Esc)', self.show_tabs, toolbar=False)
        self.download_opener = None
        downloads.addLayout(header)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        download_list = QWidget()
        self.download_list = QVBoxLayout(download_list)
        self.download_list.setContentsMargins(0, 0, 0, 0)
        self.download_empty = QLabel('No downloads in this window.', objectName='muted')
        self.download_list.addWidget(self.download_empty)
        self.download_list.addStretch()
        scroll.setWidget(download_list)
        downloads.addWidget(scroll, 1)
        self.pages.addWidget(self.download_page)
        self.content.addWidget(self.pages, 1)
        self.status = QLabel(objectName='muted')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.hide()
        self.content.addWidget(self.status)
        for sequence, action in (
            ('Ctrl+L', self.focus_address), ('Ctrl+T', self.add_tab),
            ('Ctrl+W', lambda: self.close_tab(self.tabs.currentIndex())),
            ('Ctrl+Shift+T', self.reopen_tab),
            ('Ctrl+Tab', lambda: self.step_tab(1)),
            ('Ctrl+Shift+Tab', lambda: self.step_tab(-1)),
            ('Ctrl+Shift+N', self.open_private),

            ('Alt+Left', lambda: self.current_action('Back')),
            ('Alt+Right', lambda: self.current_action('Forward')),
            ('Ctrl+R', lambda: self.current_action('Reload')),
            ('Ctrl+F', self.show_find),
            ('Ctrl+J', self.toggle_downloads),
            ('Escape', self.escape),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(action)
        self.themeChanged.connect(self.update_toolbar_layout)
        self.themeChanged.connect(self.apply_page_theme)
        self.add_tab()
        self.refresh_icons()

    def button(self, layout, icon, title, callback, *, toolbar=True):
        button = QPushButton()
        button.setObjectName('browserAction')
        button.setProperty('mellipiSymbolicIcon', icon)
        if toolbar:
            self.toolbar_buttons.append(button)
        elif self.toolbar_buttons:
            sample = self.toolbar_buttons[0]
            self.size_chrome_button(button, sample.minimumWidth(), sample.iconSize().width())
        button.setToolTip(title)
        button.setAccessibleName(title)
        button.clicked.connect(lambda _checked: callback())
        layout.addWidget(button)
        return button

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'toolbar'):
            self.update_toolbar_layout()

    def update_toolbar_layout(self):
        scale = self.theme['text_scale']
        side = max(32, round(30 * scale), self.address.sizeHint().height())
        icon = round(16 * scale)
        if self.toolbar_buttons[0].minimumWidth() != side or self.toolbar_buttons[0].iconSize().width() != icon:
            for button in self.findChildren(QPushButton, 'browserAction'):
                self.size_chrome_button(button, side, icon)
            self.address.setFixedHeight(side)
        if hasattr(self, 'find_input'):
            if self.find_input.minimumHeight() != side:
                self.find_input.setFixedHeight(side)
            width = self.find_result.fontMetrics().horizontalAdvance('No match')
            if self.find_result.minimumWidth() != width:
                self.find_result.setMinimumWidth(width)
        required = (self.navigation.sizeHint().width() + self.actions.sizeHint().width()
                    + 2 * self.toolbar.horizontalSpacing() + round(280 * scale))
        narrow = max(0, self.centralWidget().contentsRect().width() - 16) < required
        if narrow == self.narrow_toolbar:
            return
        self.narrow_toolbar = narrow
        self.toolbar.removeItem(self.navigation)
        self.toolbar.removeWidget(self.address)
        self.toolbar.removeItem(self.actions)
        self.toolbar.setColumnStretch(1, 1)
        if narrow:
            self.toolbar.addWidget(self.address, 0, 0, 1, 3)
            self.toolbar.addLayout(self.navigation, 1, 0)
            self.toolbar.addLayout(self.actions, 1, 2)
        else:
            self.toolbar.addLayout(self.navigation, 0, 0)
            self.toolbar.addWidget(self.address, 0, 1)
            self.toolbar.addLayout(self.actions, 0, 2)

    @staticmethod
    def size_chrome_button(button, side, icon):
        button.setFixedSize(side, side)
        button.setIconSize(QSize(icon, icon))

    def bookmark_page(self):
        tab = self.tabs.currentWidget()
        return tab.view if tab is not None else None

    def toggle_bookmark(self):
        if self.bookmarks is None:
            return
        page = self.bookmark_page()
        if page is None or not web_url(page.url()):
            self.message('Open a web page before saving a bookmark.')
            return
        try:
            added = self.bookmarks.toggle(page.url(), page.title())
        except (OSError, ValueError):
            self.message('Could not update bookmarks. Check storage or remove some bookmarks.')
            return
        self.message('Bookmark saved' if added else 'Bookmark removed')

    def show_bookmarks(self):
        if self.bookmarks is None:
            return
        try:
            rows = self.bookmarks.read()
        except (OSError, ValueError):
            self.message('Could not read your bookmarks.')
            return
        menu = QMenu(self)
        page = self.bookmark_page()
        current = self.bookmarks.clean_url(page.url()) if page is not None else None
        marked = current in rows
        toggle = menu.addAction(
            symbolic_icon('edit-delete' if marked else 'bookmark-new', self.theme['accent_ink']),
            'Remove this bookmark' if marked else 'Bookmark this page')

        toggle.setEnabled(bool(current))
        toggle.triggered.connect(self.toggle_bookmark)
        menu.addSeparator()
        if not rows:
            menu.addAction('No bookmarks yet').setEnabled(False)
        for url, title in reversed(list(rows.items())):
            label = ''.join(c for c in title if c.isprintable())[:64] or QUrl(url).host()
            action = menu.addAction(symbolic_icon('bookmark-new', self.theme['accent_ink']), label.replace('&', '&&'))
            action.setToolTip(url)
            action.triggered.connect(lambda _checked=False, saved=url: self.open_url(self.tabs.currentWidget(), QUrl(saved)))
        menu.setToolTipsVisible(True)
        button = self.bookmark_button
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
        menu.deleteLater()

    def step_tab(self, step):
        if self.tabs.count() > 1:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + step) % self.tabs.count())

    def open_private(self):
        ok, _pid = QProcess.startDetached(sys.executable, [str(Path(__file__).resolve()), '--private'])
        if not ok:
            self.message('Could not open a private window')

    def focus_address(self):
        self.address.setFocus()
        self.address.selectAll()

    def message(self, text):
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def tab_switched(self, _index):
        self.update_toolbar(update_address=True)
        if not self.find_bar.isHidden():
            self.reset_find()
            self.find_in_page()

    def show_find(self):
        self.show_tabs()
        self.find_bar.show()
        self.find_in_page()
        self.find_input.setFocus()
        self.find_input.selectAll()

    def reset_find(self):
        self.find_generation += 1
        if self.find_view is not None:
            self.find_view.findText('')
            self.find_view = None
        self.find_result.clear()

    def hide_find(self):
        self.reset_find()
        self.find_bar.hide()
        view = self.bookmark_page()
        if view is not None:
            view.setFocus()
        else:
            self.focus_address()

    def escape(self):
        if self.pages.currentWidget() is self.download_page:
            self.show_tabs()
        elif not self.find_bar.isHidden():
            self.hide_find()
        else:
            self.current_action('Stop')

    def find_in_page(self, _changed=None, *, backward=False):
        if self.find_bar.isHidden():
            return
        view = self.bookmark_page()
        term = self.find_input.text()
        self.find_generation += 1
        generation = self.find_generation
        self.find_previous.setEnabled(bool(view and term))
        self.find_next.setEnabled(bool(view and term))
        self.find_result.clear()
        if view is None:
            self.find_result.setText('No page')
            return
        self.find_view = view
        flags = self.Page.FindFlag.FindBackward if backward else self.Page.FindFlag(0)

        def completed(found):
            if not isdeleted(self.find_result) and generation == self.find_generation and term:
                self.find_result.setText('' if found else 'No match')

        view.findText(term, flags, completed)

    def add_tab(self, url=None, foreground=True):
        # Allocate the renderer only once the tab actually loads an address.
        tab = QWidget()
        tab.layout_ = QVBoxLayout(tab)
        tab.layout_.setContentsMargins(0, 0, 0, 0)
        tab.view = None
        caption = QLabel('Private tab' if self.private else 'New tab')
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption.setObjectName('muted')
        tab.layout_.addWidget(caption, 1)
        index = self.tabs.addTab(tab, caption.text())
        if foreground:
            self.show_tabs()
            self.tabs.setCurrentIndex(index)
        if url is not None:
            self.open_url(tab, url)
        elif foreground:
            self.focus_address()
        return tab

    def remove_placeholder(self, tab):
        item = tab.layout_.takeAt(0)
        if item is not None:
            item.widget().deleteLater()

    def make_view(self, tab):
        base = self.Page

        class RestrictedPage(base):
            def chooseFiles(self, mode, old_files, accepted_types):
                # Qt's page belongs to the embedded web view. Anchor a
                # chooser to the owning app, never a background tab.
                view = self.parent()
                owner = view.window() if view is not None else None
                if not isinstance(owner, Browser) or owner.bookmark_page() is not view:
                    return []
                kind = self.FileSelectionMode
                initial = old_files[0] if old_files and old_files[0] else ''
                start = str(Path(initial).parent) if initial else ''
                if mode == kind.FileSelectUploadFolder:
                    folder = FileChooser.getExistingDirectory(owner, 'Choose a folder to upload', start)
                    return [folder] if folder else []
                db = QMimeDatabase()
                patterns = set()
                for value in list(accepted_types)[:64]:
                    if not value:
                        continue
                    if re.fullmatch(r'\.[A-Za-z0-9._+-]+', value):
                        patterns.add('*' + value)
                    else:
                        mime = db.mimeTypeForName(value)
                        if mime.isValid():
                            patterns.update(pattern for pattern in mime.globPatterns()
                                            if re.fullmatch(r'\*\.[A-Za-z0-9._+-]+', pattern))
                filters = ('Accepted files (' + ' '.join(sorted(patterns)) +
                           ');;All files (*)') if patterns else 'All files (*)'
                if mode == kind.FileSelectOpenMultiple:
                    return FileChooser.getOpenFileNames(owner, 'Choose files to upload', start, filters)[0]
                if mode == kind.FileSelectSave:
                    path = FileChooser.getSaveFileName(owner, 'Save file', initial, filters)[0]
                else:
                    path = FileChooser.getOpenFileName(owner, 'Choose a file to upload', start, filters)[0]
                return [path] if path else []

            def acceptNavigationRequest(self, url, kind, is_main_frame):
                if not is_main_frame:
                    return url.scheme() in ('https', 'http', 'about', 'data', 'blob')
                if url == QUrl('about:blank'):
                    return True
                return web_url(url)

        view = self.View(tab)
        page = RestrictedPage(self.profile, view)
        view.setPage(page)
        page.settings().setUnknownUrlSchemePolicy(
            page.settings().UnknownUrlSchemePolicy.DisallowUnknownUrlSchemes)
        page.certificateError.connect(lambda error: error.rejectCertificate())
        page.featurePermissionRequested.connect(lambda origin, feature: page.setFeaturePermission(
            origin, feature, page.PermissionPolicy.PermissionDeniedByUser))
        # Only open validated links from a user gesture, never unsolicited popups.
        page.newWindowRequested.connect(self.open_new_window)
        view.titleChanged.connect(lambda title: self.tab_title(tab, title))
        view.urlChanged.connect(lambda _url: self.address_changed(tab))
        view.loadStarted.connect(lambda: self.update_toolbar())
        view.loadFinished.connect(lambda ok: self.loaded(tab, ok))
        page.renderProcessTerminated.connect(lambda *_: self.page_stopped(tab))
        self.remove_placeholder(tab)
        tab.view = view
        tab.layout_.addWidget(view, 1)
        page.setBackgroundColor(QColor(self.theme['surface']))
        return view

    def open_new_window(self, request):
        url = request.requestedUrl()
        if request.isUserInitiated() and web_url(url):
            tab = self.add_tab(foreground=request.destination() != self.Request.DestinationType.InNewBackgroundTab)
            view = self.make_view(tab)
            request.openIn(view.page())

    def open_url(self, tab, url):
        if tab is None or not web_url(url):
            return
        view = tab.view or self.make_view(tab)
        view.setUrl(url)
        if tab is self.tabs.currentWidget():
            self.show_tabs()
            view.setFocus()

    def navigate(self):
        url = address_url(self.address.text())
        if url is None:
            self.message('Use an HTTP or HTTPS address, or enter a search term.')
            return
        self.message('')
        self.open_url(self.tabs.currentWidget(), url)

    def tab_title(self, tab, title):
        index = self.tabs.indexOf(tab)
        if index >= 0:
            clean = ''.join(c for c in title if c.isprintable())[:180]
            label = (clean or tab.view.url().host() or 'New tab').replace('&', '&&')
            self.tabs.setTabText(index, label)

    def address_changed(self, tab):
        if tab is self.tabs.currentWidget():
            self.update_toolbar(update_address=not self.address.hasFocus())

    def update_toolbar(self, update_address=False):
        tab = self.tabs.currentWidget()
        view = tab.view if tab is not None else None
        url = view.url() if view else QUrl()
        if update_address:
            self.address.setText(url.toString() if web_url(url) else '')
        self.back.setEnabled(bool(view and view.history().canGoBack()))
        self.forward.setEnabled(bool(view and view.history().canGoForward()))
        self.reload.setEnabled(bool(view))
        loading = bool(view and view.page().isLoading())
        icon = 'window-close' if loading else 'view-refresh'
        self.reload.setProperty('mellipiSymbolicIcon', icon)
        self.reload.setIcon(symbolic_icon(icon, self.theme['accent_ink']))
        label = 'Stop loading (Esc)' if loading else 'Reload (Ctrl+R)'
        self.reload.setToolTip(label)
        self.reload.setAccessibleName(label)

    def loaded(self, tab, ok):
        if tab is self.tabs.currentWidget():
            self.update_toolbar(update_address=not self.address.hasFocus())
            self.message('' if ok else 'This page did not load. Check the address or try again.')
            if ok and not self.find_bar.isHidden():
                self.find_in_page()

    def page_stopped(self, tab):
        if tab is self.tabs.currentWidget():
            self.message('The web page stopped responding. Reload to try again.')

    def current_action(self, action):
        tab = self.tabs.currentWidget()
        if tab and tab.view:
            tab.view.page().triggerAction(getattr(self.Page.WebAction, action))

    def toggle_loading(self):
        tab = self.tabs.currentWidget()
        if tab and tab.view:
            self.current_action('Stop' if tab.view.page().isLoading() else 'Reload')

    def close_tab(self, index):
        tab = self.tabs.widget(index)
        if tab is None:
            return
        if tab.view is not None:
            address = Bookmarks.clean_url(tab.view.url())
            if address:
                self.closed_tabs.append((address, index))
        if self.tabs.count() == 1:
            self.add_tab()
        self.tabs.removeTab(index)
        tab.deleteLater()
        self.message('')

    def reopen_tab(self):
        if not self.closed_tabs:
            self.message('No closed tabs to reopen.')
            return
        address, previous_index = self.closed_tabs.pop()
        self.message('')
        tab = self.tabs.currentWidget()
        # Reuse the idle placeholder created when the last page was closed.
        if self.tabs.count() == 1 and tab.view is None and not self.address.text():
            self.open_url(tab, QUrl(address))
        else:
            tab = self.add_tab(QUrl(address))
            index = self.tabs.indexOf(tab)
            self.tabs.tabBar().moveTab(index, min(previous_index, index))

    def show_tab_menu(self, position):
        bar = self.tabs.tabBar()
        menu = QMenu(self)
        reopen = menu.addAction(symbolic_icon('edit-undo', self.theme['accent_ink']), 'Reopen closed tab')
        reopen.setShortcut(QKeySequence('Ctrl+Shift+T'))
        reopen.setEnabled(bool(self.closed_tabs))
        reopen.triggered.connect(self.reopen_tab)
        menu.exec(bar.mapToGlobal(position))
        menu.deleteLater()

    def apply_page_theme(self):
        for index in range(self.tabs.count()):
            tab = self.tabs.widget(index)
            if tab.view:
                tab.view.page().setBackgroundColor(QColor(self.theme['surface']))

    def show_tabs(self):
        returning = self.pages.currentWidget() is self.download_page
        self.pages.setCurrentWidget(self.tabs)
        if returning:
            opener = self.download_opener() if self.download_opener else None
            self.download_opener = None
            if opener is not None and not isdeleted(opener) and opener.isVisible() and opener.isEnabled():
                opener.setFocus(Qt.FocusReason.ShortcutFocusReason)
            else:
                self.download_button.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def toggle_downloads(self):
        if self.pages.currentWidget() is self.download_page:
            self.show_tabs()
            return
        opener = QApplication.focusWidget()
        self.download_opener = weakref.ref(opener) if opener is not None and opener.window() is self else None
        if not self.find_bar.isHidden():
            self.hide_find()
        if self.status.text() == self.DOWNLOAD_NOTICE:
            self.message('')
        self.pages.setCurrentWidget(self.download_page)
        self.download_close.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def downloads_at_capacity(self):
        return sum(not row.finished for row in self.download_rows) >= self.MAX_DOWNLOADS

    def download(self, request):
        if self.downloads_at_capacity():
            request.cancel()
            self.message('Too many active downloads. Open Downloads to check their progress.')
            return
        filename = Path(request.downloadFileName()).name or 'download'
        suggested = Path(request.downloadDirectory()) / filename
        location, _ = FileChooser.getSaveFileName(self, 'Save download', str(suggested))
        if not location:
            request.cancel()
            return
        target = Path(os.path.abspath(location))
        # The chooser can run a nested event loop. Recheck before accepting.
        if self.downloads_at_capacity() or any(
                row.target == target and not row.finished for row in self.download_rows):
            request.cancel()
            self.message('Another download is using this destination or the download list is full.')
            return
        request.setDownloadDirectory(str(target.parent))
        request.setDownloadFileName(target.name)
        row = DownloadRow(self, request, target)
        self.download_rows.insert(0, row)
        self.download_list.insertWidget(0, row)
        self.download_empty.hide()
        if len(self.download_rows) > self.MAX_DOWNLOAD_ROWS:
            oldest_finished = next(old for old in reversed(self.download_rows) if old.finished)
            self.download_rows.remove(oldest_finished)
            self.download_list.removeWidget(oldest_finished)
            oldest_finished.deleteLater()
        self.refresh_icons()
        if self.pages.currentWidget() is not self.download_page:
            self.message(self.DOWNLOAD_NOTICE)
        request.accept()

    def closeEvent(self, event):
        active = [row for row in self.download_rows if not row.finished]
        if active and not themed_prompt(
                self, 'Close Browser?', 'Closing Browser cancels downloads that are still running.',
                'Cancel downloads and close', 'Keep Browser open'):
            event.ignore()
            return
        for row in active:
            row.cancel()
        super().closeEvent(event)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private', action='store_true', help='Use an in-memory profile without persistent cookies or cache')
    parser.add_argument('urls', nargs='*')
    args = parser.parse_args(argv)
    # Import before QApplication, as required by Qt WebEngine on some Qt builds.
    try:
        from PyQt6.QtWebEngineCore import QWebEngineNewWindowRequest, QWebEnginePage, QWebEngineProfile
        from PyQt6.QtWebEngineWidgets import QWebEngineView
    except ImportError as error:
        print(f'Mellipi Browser needs python3-pyqt6.qtwebengine: {error}', file=sys.stderr)
        return 1
    os.environ['QT_WAYLAND_SHELL_INTEGRATION'] = 'xdg-shell'
    os.environ.pop('QT_WAYLAND_DISABLE_WINDOWDECORATION', None)
    app = QApplication([sys.argv[0]])
    app.setApplicationName('Mellipi Browser')
    app.setDesktopFileName('mellipi-browser')
    window = Browser((QWebEngineProfile, QWebEnginePage, QWebEngineNewWindowRequest, QWebEngineView), args.private)
    urls = [url for value in args.urls if (url := address_url(value)) is not None]
    for index, url in enumerate(urls):
        if index == 0:
            window.open_url(window.tabs.currentWidget(), url)
        else:
            window.add_tab(url)
    window.show()
    result = app.exec()
    # Profile ownership must outlive every view, including pages closed earlier.
    from PyQt6.sip import delete
    profile = window.profile
    delete(window)
    delete(profile)
    return result


if __name__ == '__main__':
    sys.exit(main())
