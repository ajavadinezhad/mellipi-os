"""Shared, live Mellipi appearance for Qt Widgets applications."""
from pathlib import Path
from functools import lru_cache

from PyQt6.QtCore import QFileSystemWatcher, QPoint, Qt, pyqtSignal, QObject
from PyQt6.QtGui import QColor, QIcon, QPainter, QPalette
from PyQt6.QtWidgets import QApplication, QAbstractButton, QDialog, QHBoxLayout, QInputDialog, QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget

from app_palette import HEADER_HEIGHTS, colors, identity_appearance
from installed_launcher import user_environment
from preferences import Preferences
from qt_titlebar import TitleBar


class ThemeWatch(QObject):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = Path(user_environment()['ORBIT_SETTINGS_FILE'])
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.reload)
        self.watcher.fileChanged.connect(self.reload)
        self.signature = None
        self.reload()

    def reload(self, *_):
        # Prefer the directory as files are saved with atomic replacement. If
        # it doesn't exist yet, track the closest existing ancestor.
        directory = next((p for p in self.path.parents if p.is_dir()), None)
        directory = str(directory) if directory else None
        if directory and directory not in self.watcher.directories():
            if self.watcher.addPath(directory) and self.watcher.directories() != [directory]:
                self.watcher.removePaths([p for p in self.watcher.directories() if p != directory])
        if self.path.is_file() and str(self.path) not in self.watcher.files():
            self.watcher.addPath(str(self.path))
        self.preferences = Preferences(self.path)
        prefs = self.preferences.values
        palette = colors(self.preferences)
        self.tokens = dict(palette, theme_id=prefs['themePreset'], density=prefs['density'], text_scale=prefs['textScale'],
                           font_size=round(14*prefs['textScale']),
                           outline_width=1 if prefs['highContrast'] else 0,
                           focus_width=2 if prefs['highContrast'] else 1,
                           input_edge=palette['control_border'] if prefs['highContrast'] else palette['border'],
                           radius={'square': 0, 'soft': 4, 'rounded': 8}[prefs['corners']],
                           padding={'comfortable': 8, 'compact': 6, 'extra': 4}[prefs['density']])
        if self.tokens != self.signature:
            self.signature = self.tokens
            self.changed.emit()


def widget_palette(tokens):
    palette = QPalette()
    for role, key in ((QPalette.ColorRole.Window, 'background'), (QPalette.ColorRole.Base, 'surface'),
                      (QPalette.ColorRole.AlternateBase, 'raised'), (QPalette.ColorRole.Button, 'raised'),
                      (QPalette.ColorRole.WindowText, 'text'), (QPalette.ColorRole.Text, 'text'),
                      (QPalette.ColorRole.ButtonText, 'text'), (QPalette.ColorRole.Highlight, 'accent'),
                      (QPalette.ColorRole.HighlightedText, 'accent_text'), (QPalette.ColorRole.Link, 'accent_ink'),
                      (QPalette.ColorRole.ToolTipBase, 'raised'), (QPalette.ColorRole.ToolTipText, 'text'),
                      (QPalette.ColorRole.PlaceholderText, 'muted')):
        palette.setColor(role, QColor(tokens[key]))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(tokens['faint']))
    return palette


def apply_titlebar(bar, tokens):
    bar.update_controls(tokens['accent_ink'], tokens['theme_id'] == 'cyberpunk')
    bar.setMinimumHeight(HEADER_HEIGHTS[tokens['density']])


@lru_cache(maxsize=128)
def _original_icon(name, ink):
    from mellipi_icons import svg
    from PyQt6.QtGui import QPixmap
    icon = QIcon()
    for size in (16, 20, 24, 32, 48):
        data = svg(name, ink, size=size)
        if not data:
            break
        pixmap = QPixmap()
        if pixmap.loadFromData(data, 'SVG'):
            icon.addPixmap(pixmap)
    return icon


def original_icon(name, ink='#303745'):
    # Return an implicitly shared copy so a caller cannot mutate the cache.
    return QIcon(_original_icon(name, ink))


def symbolic_icon(name, ink):
    custom = original_icon(name, ink)
    if not custom.isNull():return custom
    for category in ('actions', 'places', 'status', 'devices', 'legacy', 'apps', 'categories', 'mimetypes'):
        path = Path('/usr/share/icons/Adwaita/symbolic') / category / (name + '-symbolic.svg')
        if path.is_file():
            icon = QIcon(str(path))
            break
    else:
        icon = QIcon.fromTheme(name + '-symbolic', QIcon.fromTheme(name))
    pixmap = icon.pixmap(16, 16)
    if pixmap.isNull():
        return icon
    painter = QPainter(pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QColor(ink))
    painter.end()
    return QIcon(pixmap)


BASE_STYLE = '''
    QWidget { font-size: %(font_size)dpx; }
    QMainWindow, QDialog { background: %(background)s; color: %(text)s; }
    QFrame#titlebar { border-bottom: 1px solid %(separator)s; }
    QLabel#windowTitle { color: %(text)s; font-weight: 600; }
    QLabel#muted { color: %(muted)s; }
    QLabel#emptyStageHeading { color: %(text)s; font-weight: 650; }
    QPushButton#emptyStageAction { background: %(accent)s; color: %(accent_text)s; }
    QPushButton#emptyStageAction:hover, QPushButton#emptyStageAction:focus { border-color: %(text)s; }
    QPushButton, QToolButton {
        background: %(raised)s; color: %(text)s;
        padding: %(padding)dpx 10px; border: 1px solid transparent;
        border-radius: %(radius)dpx;
    }
    QPushButton:hover, QToolButton:hover { background: %(hover)s; }
    QDialogButtonBox QPushButton[mellipiPrimary="true"]:enabled {
        background: %(accent)s; color: %(accent_text)s; font-weight: 600;
    }
    QDialogButtonBox QPushButton[mellipiPrimary="true"]:focus { border-color: %(accent_text)s; }
    QDialogButtonBox QPushButton:default { font-weight: 600; }
    QDialogButtonBox QPushButton:default:focus { border-color: %(focus)s; }
    QPushButton:pressed, QToolButton:pressed, QPushButton:checked, QToolButton:checked {
        background: %(selected_surface)s; color: %(text)s;
    }
    QPushButton:disabled, QToolButton:disabled, QComboBox:disabled { color: %(faint)s; }
    QPushButton:focus, QToolButton:focus, QComboBox:focus, QLineEdit:focus { border-color: %(focus)s; }
    QPushButton#windowControl { background: transparent; padding: 0; }
    QPushButton#windowControl:hover { background: %(hover)s; }
    QPushButton#windowControl:focus { border-color: %(focus)s; }
    QToolTip {
        background: %(surface)s; color: %(text)s; border: 1px solid %(control_border)s;
        padding: 4px 7px;
    }
    /* Reserve the focus border so text and size hints don't shift on focus. */
    QLineEdit, QComboBox, QAbstractSpinBox, QPlainTextEdit, QTextEdit {
        background: %(surface)s; color: %(text)s;
        border: %(focus_width)dpx solid %(input_edge)s;
        padding: %(padding)dpx; border-radius: %(radius)dpx;
        selection-background-color: %(accent)s; selection-color: %(accent_text)s; }
    QLineEdit:hover, QComboBox:hover, QAbstractSpinBox:hover {
        border-color: %(control_border)s;
    }
    QComboBox { padding-right: 28px; }
    QComboBox::drop-down {
        subcontrol-origin: padding; subcontrol-position: top right; width: 24px; }
    QComboBox QAbstractItemView {
        background: %(raised)s; color: %(text)s; border: 1px solid %(input_edge)s;
        border-radius: %(radius)dpx; padding: 3px; outline: 0;
        selection-background-color: %(selected_surface)s; selection-color: %(text)s;
    }
    QComboBox QAbstractItemView::item { padding: 4px 8px; }
    QLineEdit:focus, QComboBox:focus, QAbstractSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {
        border: %(focus_width)dpx solid %(focus)s; }
    QLineEdit:disabled, QComboBox:disabled, QAbstractSpinBox:disabled, QPlainTextEdit:disabled, QTextEdit:disabled {
        color: %(faint)s; border-color: %(separator)s; }
    /* Spin boxes and editable combos already draw the input frame. */
    QAbstractSpinBox QLineEdit, QAbstractSpinBox QLineEdit:focus,
    QComboBox QLineEdit, QComboBox QLineEdit:focus {
        background: transparent; border: 0; border-radius: 0; padding: 0;
    }
    QTabWidget::pane { border: 0; }
    QTabBar::tab { padding: %(padding)dpx 10px; background: %(raised)s; color: %(muted)s;
        border-bottom: 2px solid transparent; }
    QTabBar::tab:selected { background: %(selected_surface)s; color: %(text)s; border-bottom-color: %(focus)s; }
    QTabBar::tab:focus { border-bottom-color: %(focus)s; }
    QAbstractItemView:focus { border: 1px solid %(focus)s; }
    QAbstractItemView { background: %(surface)s; color: %(text)s;
        alternate-background-color: %(raised)s; border: %(outline_width)dpx solid %(control_border)s;
        selection-background-color: %(selected_surface)s; selection-color: %(text)s; }
    QHeaderView::section { background: %(raised)s; color: %(text)s;
        border: 0; border-bottom: 1px solid %(separator)s; padding: 5px; }
    QMenu { background: %(raised)s; color: %(text)s; border: 1px solid %(separator)s; }
    QMenu::item { padding: 6px 12px; }
    QMenu::item:selected { background: %(selected_surface)s; color: %(text)s; }
    QMenu::separator { height: 1px; background: %(separator)s; margin: 4px 8px; }
    QProgressBar { background: %(surface)s; border: 0; }
    QProgressBar::chunk { background: %(focus)s; }
'''


def exec_owned_dialog(dialog):
    """Keep modal prompts with their owner; the compositor places them on Wayland."""
    owner = dialog.parentWidget()
    if owner is not None:
        owner = owner.window()
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        if not QApplication.platformName().startswith('wayland'):
            dialog.ensurePolished()
            if not dialog.testAttribute(Qt.WidgetAttribute.WA_Resized):
                dialog.adjustSize()
            available = owner.screen().availableGeometry()
            wanted = owner.frameGeometry().center() - QPoint(dialog.width() // 2, dialog.height() // 2)
            dialog.move(max(available.left(), min(wanted.x(), available.right() + 1 - dialog.width())),
                        max(available.top(), min(wanted.y(), available.bottom() + 1 - dialog.height())))
    return dialog.exec()


def style_dialog(dialog, parent):
    tokens = parent.theme_watch.tokens
    dialog.setPalette(widget_palette(tokens))
    dialog.setStyleSheet(BASE_STYLE % tokens)
    return dialog


class ThemedInput:
    @staticmethod
    def _ask(parent, title, label, setup, value):
        dialog = style_dialog(QInputDialog(parent), parent)
        dialog.setWindowTitle(title)
        dialog.setLabelText(label)
        setup(dialog)
        try:
            accepted = exec_owned_dialog(dialog) == QDialog.DialogCode.Accepted
            return value(dialog) if accepted else None, accepted
        finally:
            dialog.deleteLater()

    @classmethod
    def getText(cls, parent, title, label, *, text=''):
        return cls._ask(parent, title, label, lambda d: d.setTextValue(text), lambda d: d.textValue())

    @classmethod
    def getMultiLineText(cls, parent, title, label):
        return cls._ask(parent, title, label,
                        lambda d: d.setOption(QInputDialog.InputDialogOption.UsePlainTextEditForTextInput),
                        lambda d: d.textValue())

    @classmethod
    def getInt(cls, parent, title, label, initial, minimum, maximum):
        def setup(dialog):
            dialog.setInputMode(QInputDialog.InputMode.IntInput)
            dialog.setIntRange(minimum, maximum)
            dialog.setIntValue(initial)
        return cls._ask(parent, title, label, setup, lambda d: d.intValue())

    @classmethod
    def getItem(cls, parent, title, label, items, current, editable):
        def setup(dialog):
            dialog.setComboBoxItems(items)
            dialog.setComboBoxEditable(editable)
            if 0 <= current < len(items):
                dialog.setTextValue(items[current])
        return cls._ask(parent, title, label, setup, lambda d: d.textValue())


def themed_prompt(parent, title, message, primary, cancel=None):
    """Show a theme-aware modal; Enter defaults to cancel for confirmations."""
    return themed_choice(parent, title, message, primary, cancel) == QDialog.DialogCode.Accepted


def themed_choice(parent, title, message, primary, cancel=None, alternate=None):
    """Return Accepted, Rejected, or 2 when an alternate action was chosen."""
    dialog = QDialog(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
    dialog.setWindowTitle(title)
    dialog.setPalette(widget_palette(parent.theme_watch.tokens))
    dialog.setStyleSheet((BASE_STYLE + """
        QDialog#themedPrompt { border: 1px solid %(separator)s; }
        QLabel#promptHeading { color: %(text)s; font-size: %(headingSize)dpx; font-weight: 650; }
        QPushButton#promptPrimary { background: %(accent)s; color: %(accent_text)s; }
        QPushButton#promptPrimary:hover { border-color: %(text)s; }
        QPushButton#promptCancel { background: transparent; color: %(text)s; }
        QPushButton#promptCancel:hover { background: %(hover)s; }
    """) % dict(parent.theme_watch.tokens, headingSize=round(parent.theme_watch.tokens["font_size"] * 1.25)))
    dialog.setObjectName('themedPrompt')
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(10)
    header = QWidget(dialog)
    heading_layout = QHBoxLayout(header)
    heading_layout.setContentsMargins(0, 0, 0, 0)
    heading = QLabel(title, header)
    heading.setTextFormat(Qt.TextFormat.PlainText)
    heading.setObjectName('promptHeading')
    heading_layout.addWidget(heading)
    layout.addWidget(header)
    body = QVBoxLayout()
    body.setContentsMargins(0, 0, 0, 0)
    body.setSpacing(14)
    label = QLabel(message, dialog)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setMinimumWidth(260)
    label.setMaximumWidth(440)
    body.addWidget(label)
    buttons = QHBoxLayout()
    buttons.addStretch()
    action = QPushButton(primary, dialog)
    action.setObjectName('promptPrimary')
    action.clicked.connect(dialog.accept)
    if cancel:
        dismiss = QPushButton(cancel, dialog)
        dismiss.setObjectName('promptCancel')
        dismiss.clicked.connect(dialog.reject)
        buttons.addWidget(dismiss)
    else:
        dismiss = action
    if alternate:
        alternative = QPushButton(alternate, dialog)
        alternative.setObjectName('promptAlternate')
        alternative.clicked.connect(lambda: dialog.done(2))
        buttons.addWidget(alternative)
    buttons.addWidget(action)
    dismiss.setDefault(True)
    dismiss.setFocus()
    body.addLayout(buttons)
    layout.addLayout(body)
    try:
        return exec_owned_dialog(dialog)
    finally:
        dialog.deleteLater()


class AppIdentityBadge(QLabel):
    """A small app-colored mark; do not use it for focus or selection."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(22, 22)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def theme(self, title, tokens):
        glyph, ink, badge = identity_appearance(title, tokens['background'])
        self.setPixmap(original_icon(glyph, ink).pixmap(15, 15))
        self.setStyleSheet(f'background: {badge}; border-radius: {tokens["radius"]}px;')


class AppWindow(QMainWindow):
    themeChanged = pyqtSignal()
    extra_style = ''

    def __init__(self, title):
        super().__init__()
        QApplication.instance().setStyle('Fusion')
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle(title)
        self.setCentralWidget(QWidget())
        layout = QVBoxLayout(self.centralWidget())
        layout.setContentsMargins(8, 0, 8, 8)
        layout.setSpacing(8)
        self.header = QHBoxLayout()
        self.identity_name = title
        self.identity_badge = AppIdentityBadge(self)
        self.header.addWidget(self.identity_badge)
        self.title = QLabel(title)
        self.title.setObjectName('windowTitle')
        self.header.addWidget(self.title, 1)
        self.titlebar = TitleBar(self, self.header)
        layout.addWidget(self.titlebar)
        self.content = QVBoxLayout()
        self.content.setSpacing(8)
        layout.addLayout(self.content, 1)
        self.theme_watch = ThemeWatch(self)
        self.theme_watch.changed.connect(self._apply_appearance)
        self._apply_appearance()

    def empty_stage(self, heading, hint, action, callback):
        stage = QWidget(self)
        stack = QVBoxLayout(stage)
        stack.setSpacing(7)
        stack.addStretch()
        badge = AppIdentityBadge(stage)
        badge.setFixedSize(34, 34)
        badge.theme(self.identity_name, self.theme)
        self.themeChanged.connect(lambda: badge.theme(self.identity_name, self.theme))
        stack.addWidget(badge, alignment=Qt.AlignmentFlag.AlignHCenter)
        title = QLabel(heading)
        title.setObjectName('emptyStageHeading')
        stack.addWidget(title, alignment=Qt.AlignmentFlag.AlignHCenter)
        description = QLabel(hint)
        description.setObjectName('muted')
        description.setWordWrap(True)
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stack.addWidget(description)
        button = QPushButton(action)
        button.setObjectName('emptyStageAction')
        button.clicked.connect(callback)
        stack.addWidget(button, alignment=Qt.AlignmentFlag.AlignHCenter)
        stack.addStretch()
        return stage

    def _apply_appearance(self):
        self.theme = self.theme_watch.tokens
        palette = widget_palette(self.theme)
        self.setPalette(palette)
        QApplication.instance().setPalette(palette)
        apply_titlebar(self.titlebar, self.theme)
        self.identity_badge.theme(self.identity_name, self.theme)
        self.setStyleSheet((BASE_STYLE + self.extra_style) % self.theme)
        self.refresh_icons()
        self.themeChanged.emit()

    def refresh_icons(self):
        for button in self.findChildren(QAbstractButton):
            name = button.property('mellipiSymbolicIcon')
            if name:
                button.setIcon(symbolic_icon(name, self.theme['accent_ink']))
