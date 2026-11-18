"""Shared, live Mellipi appearance for Qt Widgets applications."""
from pathlib import Path
from functools import lru_cache
from math import ceil
from html import escape

from PyQt6.QtCore import QFileSystemWatcher, QPoint, QSize, QTemporaryDir, Qt, pyqtSignal, QObject
from PyQt6.QtGui import QColor, QIcon, QPainter, QPalette, QTextOption
from PyQt6.QtWidgets import QApplication, QAbstractButton, QBoxLayout, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QPushButton, QSizePolicy, QTabBar, QTextEdit, QToolButton, QVBoxLayout, QWidget

from app_palette import HEADER_HEIGHTS, colors, identity_appearance
from installed_launcher import user_environment
from preferences import Preferences
from qt_titlebar import TitleBar


@lru_cache(maxsize=1)
def _stepper_icon_directory():
    return QTemporaryDir()


def _stepper_icon(direction, color):
    # Qt stylesheets require a URL for subcontrol images.
    directory = _stepper_icon_directory()
    if not directory.isValid():
        return ''
    ink = QColor(color).name()
    target = Path(directory.path()) / f'{direction}-{ink[1:]}.svg'
    if not target.exists():
        points = '2,5 5,2 8,5' if direction == 'up' else '2,2 5,5 8,2'
        try:
            target.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="7" viewBox="0 0 10 7"><polyline points="{points}" fill="none" stroke="{ink}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>')
        except OSError:
            return ''
    return target.as_posix()


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
                           radius={'square': 0, 'soft': 6, 'rounded': 10}[prefs['corners']],
                           heading_size=round(19*prefs['textScale']),
                           padding={'comfortable': 8, 'compact': 6, 'extra': 4}[prefs['density']])
        self.tokens.update(step_up=_stepper_icon('up', palette['text']),
                           step_down=_stepper_icon('down', palette['text']),
                           step_up_disabled=_stepper_icon('up', palette['faint']),
                           step_down_disabled=_stepper_icon('down', palette['faint']))
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
    QFrame#titlebar { background: %(chrome)s; border-bottom: 1px solid %(chrome_edge)s; }
    QLabel#windowTitle { color: %(chrome_text)s; font-weight: 700; }
    QLabel#muted { color: %(muted)s; }
    QLabel#emptyStageHeading { color: %(text)s; font-size: %(heading_size)dpx; font-weight: 700; }
    QPushButton#emptyStageAction { background: %(accent)s; color: %(accent_text)s; }
    QPushButton#emptyStageAction:hover, QPushButton#emptyStageAction:focus { border-color: %(text)s; }
    QPushButton, QToolButton {
        background: transparent; color: %(text)s;
        padding: %(padding)dpx 10px; border: 1px solid transparent;
        border-radius: %(radius)dpx;
    }
    QPushButton:hover, QToolButton:hover { background: %(hover)s; }
    QPushButton[mellipiPrimary="true"]:enabled {
        background: %(accent)s; color: %(accent_text)s; font-weight: 600;
    }
    QPushButton[mellipiPrimary="true"]:focus { border-color: %(accent_text)s; }
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
        subcontrol-origin: padding; subcontrol-position: top right;
        width: 24px; background: transparent; border: 0; border-left: 1px solid %(separator)s; }
    QComboBox::down-arrow { image: url("%(step_down)s"); width: 10px; height: 7px; }
    QComboBox::down-arrow:disabled { image: url("%(step_down_disabled)s"); }
    QAbstractSpinBox { padding-right: 25px; }
    QAbstractSpinBox::up-button, QAbstractSpinBox::down-button, QDateTimeEdit::drop-down {
        subcontrol-origin: padding; width: 22px; background: transparent;
        border-left: 1px solid %(separator)s;
    }
    QAbstractSpinBox::up-button { subcontrol-position: top right; }
    QAbstractSpinBox::down-button { subcontrol-position: bottom right; }
    QDateTimeEdit::drop-down { subcontrol-position: top right; }
    QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover,
    QDateTimeEdit::drop-down:hover { background: %(hover)s; }
    QAbstractSpinBox::up-arrow { image: url("%(step_up)s"); width: 10px; height: 7px; }
    QAbstractSpinBox::down-arrow, QDateTimeEdit::down-arrow {
        image: url("%(step_down)s"); width: 10px; height: 7px;
    }
    QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::up-arrow:off {
        image: url("%(step_up_disabled)s");
    }
    QAbstractSpinBox::down-arrow:disabled, QAbstractSpinBox::down-arrow:off,
    QDateTimeEdit::down-arrow:disabled { image: url("%(step_down_disabled)s"); }
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
    QTabBar::tab { padding: %(padding)dpx 10px; background: transparent; color: %(muted)s;
        border: 1px solid transparent; border-bottom: 2px solid transparent;
        border-top-left-radius: %(radius)dpx; border-top-right-radius: %(radius)dpx; }
    QTabBar::tab:!selected:hover { background: %(hover)s; color: %(text)s; }
    QTabBar::tab:selected { background: %(surface)s; color: %(text)s; border-bottom-color: %(focus)s; }
    QTabBar::tab:focus { border-bottom-color: %(focus)s; }
    QToolButton#mellipiTabClose { background: transparent; border: 1px solid transparent; padding: 1px; }
    QToolButton#mellipiTabClose:hover { background: %(hover)s; }
    QToolButton#mellipiTabClose:focus { border-color: %(focus)s; }
    QAbstractItemView:focus { border: 1px solid %(focus)s; }
    QAbstractItemView { background: %(surface)s; color: %(text)s;
        alternate-background-color: %(raised)s; border: %(outline_width)dpx solid %(control_border)s;
        selection-background-color: %(selected_surface)s; selection-color: %(text)s; }
    QHeaderView::section { background: %(surface)s; color: %(muted)s;
        font-weight: 600; border: 0; border-bottom: 1px solid %(separator)s; padding: 5px 8px; }
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
        dialog = style_dialog(QDialog(parent), parent)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        prompt = QLabel(label, dialog)
        layout.addWidget(prompt)
        field = QLineEdit(text, dialog)
        prompt.setBuddy(field)
        layout.addWidget(field)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setProperty('mellipiPrimary', True)
        layout.addWidget(buttons)
        dialog.ensurePolished()
        field.ensurePolished()
        available = parent.screen().availableGeometry().width()
        ideal = max(300, field.fontMetrics().horizontalAdvance(text) + 48)
        dialog.resize(max(1, min(ideal, max(300, parent.width() - 32), available - 32)), dialog.sizeHint().height())
        field.selectAll()
        field.setFocus()
        try:
            accepted = exec_owned_dialog(dialog) == QDialog.DialogCode.Accepted
            return field.text() if accepted else None, accepted
        finally:
            dialog.deleteLater()

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


def themed_choice(parent, title, message, primary, cancel=None, alternate=None, *, secondary=None):
    """Return Accepted, Rejected, 2 for alternate, or 3 for secondary."""
    dialog = QDialog(parent, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
    dialog.setWindowTitle(title)
    dialog.setPalette(widget_palette(parent.theme_watch.tokens))
    dialog.setStyleSheet((BASE_STYLE + """
        QDialog#themedPrompt { border: %(focus_width)dpx solid %(chrome_edge)s; }
        QLabel#promptHeading { color: %(text)s; font-size: %(headingSize)dpx; font-weight: 650; }
        QFrame#promptMarker { background: %(focus)s; border-radius: 1px; }
        QTextEdit#promptMessage {
            background: transparent; border: 1px solid transparent; padding: 0; color: %(text)s;
        }
        QTextEdit#promptMessage:focus { border-color: %(focus)s; }
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
    marker = QFrame(header, objectName='promptMarker')
    marker.setFixedWidth(3)
    heading_layout.addWidget(marker)
    heading = QLabel(title, header)
    heading.setTextFormat(Qt.TextFormat.PlainText)
    heading.setObjectName('promptHeading')
    heading.setWordWrap(True)
    heading_layout.addWidget(heading)
    layout.addWidget(header)
    body = QVBoxLayout()
    body.setContentsMargins(0, 0, 0, 0)
    body.setSpacing(14)
    available = parent.screen().availableGeometry()
    width_limit = max(1, available.width() - 56)
    heading.setMaximumWidth(min(440, width_limit))
    message_view = QTextEdit(dialog)
    message_view.setObjectName('promptMessage')
    message_view.setAccessibleName('Message')
    message_view.setReadOnly(True)
    message_view.setPlainText(message)
    message_view.setFrameShape(QFrame.Shape.NoFrame)
    message_view.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
    message_view.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    message_view.setTabChangesFocus(True)
    message_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    message_view.ensurePolished()
    metrics = message_view.fontMetrics()
    longest = max((metrics.horizontalAdvance(line) for line in message.splitlines()), default=0)
    message_width = min(440, width_limit, max(260, longest + 6))
    message_view.setFixedWidth(message_width)
    document = message_view.document()
    document.setDocumentMargin(1)
    # Reserve scrollbar width when measuring to avoid an extra clipped line
    # after a long message starts scrolling.
    scroll_width = message_view.verticalScrollBar().sizeHint().width()
    document.setTextWidth(max(1, message_width - scroll_width - 2))
    body.addWidget(message_view)
    buttons = QBoxLayout(QBoxLayout.Direction.LeftToRight)
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
    if secondary:
        extra = QPushButton(secondary, dialog)
        extra.setObjectName('promptAlternate')
        extra.clicked.connect(lambda: dialog.done(3))
        buttons.addWidget(extra)
    buttons.addWidget(action)
    dismiss.setDefault(True)
    dismiss.setFocus()
    button_order = ([dismiss] if cancel else []) + ([alternative] if alternate else []) + (
        [extra] if secondary else []) + [action]
    if sum(button.sizeHint().width() for button in button_order) + 8 * len(button_order) > width_limit:
        buttons.setDirection(QBoxLayout.Direction.TopToBottom)
        for button in button_order:
            buttons.setAlignment(button, Qt.AlignmentFlag.AlignRight)
    body.addLayout(buttons)
    layout.addLayout(body)
    remaining_height = available.height() - heading.sizeHint().height() - buttons.sizeHint().height() - 72
    view_height = min(ceil(document.size().height()) + 4, 300, max(message_view.fontMetrics().height() + 2, remaining_height))
    message_view.setFixedHeight(view_height)
    for previous, following in zip(button_order, [*button_order[1:], message_view]):
        dialog.setTabOrder(previous, following)
    dialog.setTabOrder(message_view, button_order[0])
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

    def theme(self, title, tokens, *, surface='background'):
        glyph, ink, badge = identity_appearance(title, tokens[surface], tokens['accent'])
        self.setPixmap(original_icon(glyph, ink).pixmap(15, 15))
        self.setStyleSheet(f'background: {badge}; border-radius: {tokens["radius"]}px;')


class ElidingLabel(QLabel):
    """A plain-text, single-line label that keeps the full accessible name."""

    def __init__(self, text=''):
        super().__init__(text)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setToolTip(self._tooltip(text))

    @staticmethod
    def _tooltip(text):
        return f'<span>{escape(text)}</span>' if text else ''

    def setText(self, text):
        super().setText(text)
        self.setToolTip(self._tooltip(text))

    def paintEvent(self, event):
        body = self.contentsRect()
        body.adjust(self.margin(), self.margin(), -self.margin(), -self.margin())
        if body.isEmpty():
            return
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(body, self.alignment().value | Qt.TextFlag.TextSingleLine.value,
                         self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, body.width()))


def action_ink(tokens, icon, primary=False):
    return tokens['accent_text'] if primary else tokens['accent_ink']


class AppWindow(QMainWindow):
    themeChanged = pyqtSignal()
    extra_style = ''

    def __init__(self, title):
        super().__init__()
        app = QApplication.instance()
        if app.style().objectName().casefold() != 'fusion':
            app.setStyle('Fusion')
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle(title)
        self.setCentralWidget(QWidget())
        layout = self.window_layout = QVBoxLayout(self.centralWidget())
        layout.setContentsMargins(0, 0, 0, 0)
        self.header = QHBoxLayout()
        self.identity_name = title
        self.identity_badge = AppIdentityBadge(self)
        self.header.addWidget(self.identity_badge)
        self.title = ElidingLabel(title)
        self.title.setObjectName('windowTitle')
        self.header.addWidget(self.title, 1)
        self.titlebar = TitleBar(self, self.header)
        layout.addWidget(self.titlebar)
        self._control_layouts = []
        self.content = QVBoxLayout()
        layout.addLayout(self.content, 1)
        self.theme_watch = ThemeWatch(self)
        self.theme_watch.changed.connect(self._apply_appearance)
        self._apply_appearance()

    def layout_spacing(self):
        """Keep density and available space independent of text/control size."""
        inset, section, control = {
            'comfortable': (16, 12, 8), 'compact': (11, 8, 6), 'extra': (7, 6, 4),
        }[self.theme['density']]
        # At large text the same width holds fewer buttons. Keep enough space
        # for the controls themselves before spending it on outer gutters.
        narrow = self.width() < round(500 * self.theme['text_scale'])
        short = self.height() < round(360 * self.theme['text_scale'])
        return (min(8, inset) if narrow else inset,
                min(6, section) if short else section,
                min(4, control) if narrow else control)

    def update_content_spacing(self):
        if not hasattr(self, 'theme'):
            return
        inset, section, control = self.layout_spacing()
        margins = (inset, 0, inset, inset)
        current = self.content.contentsMargins()
        if (current.left(), current.top(), current.right(), current.bottom()) != margins:
            self.content.setContentsMargins(*margins)
        groups = ((self.window_layout, section), (self.content, section), (self.header, control))
        for layout, spacing in (*groups, *((layout, control) for layout in self._control_layouts)):
            if layout.spacing() != spacing:
                layout.setSpacing(spacing)

    def space_controls(self, *layouts):
        self._control_layouts.extend(layouts)
        self.update_content_spacing()

    def viewport_width(self):
        """Use the window's current width, even before child layouts settle."""
        margins = self.content.contentsMargins()
        return max(0, self.contentsRect().width() - margins.left() - margins.right())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_content_spacing()

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
        self.update_content_spacing()
        palette = widget_palette(self.theme)
        self.setPalette(palette)
        QApplication.instance().setPalette(palette)
        apply_titlebar(self.titlebar, self.theme)
        self.identity_badge.theme(self.identity_name, self.theme, surface='chrome')
        self.setStyleSheet((BASE_STYLE + self.extra_style) % self.theme)
        self.refresh_icons()
        self.themeChanged.emit()

    def refresh_icons(self):
        for button in self.findChildren(QAbstractButton):
            name = button.property('mellipiSymbolicIcon')
            if name:
                button.setIcon(symbolic_icon(name, action_ink(self.theme,name,button.property('mellipiPrimary'))))
            if button.objectName() == 'mellipiTabClose':
                self.style_tab_close_button(button)

    def style_tab_close_button(self, button):
        side = round(22 * self.theme['text_scale'])
        glyph = round(13 * self.theme['text_scale'])
        button.setFixedSize(side, side)
        button.setIconSize(QSize(glyph, glyph))
        button.setIcon(symbolic_icon('window-close', self.theme['accent_ink']))

    def add_tab_close_button(self, tabs, index):
        page = tabs.widget(index)
        bar = tabs.tabBar()
        button = QToolButton(bar, objectName='mellipiTabClose')
        button.setAccessibleName('Close tab')
        button.setToolTip('Close tab')
        self.style_tab_close_button(button)

        def request_close():
            current = tabs.indexOf(page)
            if current >= 0:
                tabs.tabCloseRequested.emit(current)

        button.clicked.connect(request_close)
        bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, button)
