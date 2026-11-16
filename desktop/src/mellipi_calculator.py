"""Mellipi Calculator, a theme-aware Qt 6 desktop app."""
import sys

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QFont, QFontMetrics, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from calculator_core import CalculationError, MAX_EXPRESSION, calculate
from qt_app import AppWindow, symbolic_icon


HISTORY_LIMIT = 30


class ExpressionField(QLineEdit):
    def __init__(self, calculator):
        super().__init__()
        self.calculator = calculator

    def keyPressEvent(self, event):
        typed = event.text()
        if typed == '=':
            self.calculator.evaluate()
            return
        if (self.calculator.showing_result and typed and typed[0].lower() in '0123456789.(sal'
                and not event.modifiers() & (Qt.KeyboardModifier.ControlModifier
                                             | Qt.KeyboardModifier.AltModifier
                                             | Qt.KeyboardModifier.MetaModifier)):
            self.clear()
        super().keyPressEvent(event)


class Calculator(AppWindow):
    extra_style = """
        QLineEdit#expression { padding: 12px; }
        QLabel#calculationFeedback { color: %(muted)s; padding: 4px; }
        QListWidget#calculationHistory::item { padding: 5px 8px; }
        QPushButton#equals { background: %(accent)s; color: %(accent_text)s; }
        QPushButton#equals:hover, QPushButton#equals:pressed { border-color: %(focus)s; }
        QPushButton#equals:focus { border-color: %(focus)s; }
        QPushButton#operation { color: %(accent_ink)s; background: %(selected_surface)s; }
        QPushButton#operation:hover, QPushButton#operation:pressed { background: %(hover)s; }
    """

    def __init__(self, expression=''):
        super().__init__('Calculator')
        self.resize(352, 402)
        self.setMinimumWidth(282)
        self.workspace = QScrollArea()
        self.workspace.setFrameShape(QFrame.Shape.NoFrame)
        self.workspace.setWidgetResizable(True)
        keypad = QWidget()
        self.controls = QVBoxLayout(keypad)
        self.controls.setContentsMargins(0, 0, 0, 0)
        self.workspace.setWidget(keypad)
        self.content.addWidget(self.workspace, 1)
        self.last_expression = ''
        self.showing_result = False
        self.field = ExpressionField(self)
        self.field.setObjectName('expression')
        self.field.setAccessibleName('Expression and result')
        self.field.setPlaceholderText('0')
        self.field.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.field.setMaxLength(MAX_EXPRESSION)
        self.field.setMinimumHeight(56)
        self.field.textEdited.connect(self.edited)
        self.field.returnPressed.connect(self.evaluate)
        self.controls.addWidget(self.field)

        self.feedback = QLabel()
        self.feedback.setObjectName('calculationFeedback')
        self.feedback.setTextFormat(Qt.TextFormat.PlainText)
        self.feedback.setWordWrap(True)
        self.feedback.setMinimumHeight(32)
        self.controls.addWidget(self.feedback)
        grid = QGridLayout()
        grid.setSpacing(6)
        for column in range(4):
            grid.setColumnStretch(column, 1)
        for row, keys in enumerate((
            ('(', ')', '%', '÷'),
            ('7', '8', '9', '×'),
            ('4', '5', '6', '−'),
            ('1', '2', '3', '+'),
            ('0', '.', '^', '='),
        )):
            for column, key in enumerate(keys):
                button = self.button(key, self.evaluate if key == '=' else lambda k=key:self.insert(k))
                if key == '=':
                    button.setObjectName('equals')
                    button.setAccessibleName('Equals')
                elif key in ('÷', '×', '−', '+', '^'):
                    button.setObjectName('operation')
                    button.setAccessibleName({'÷':'Divide', '×':'Multiply', '−':'Subtract', '+':'Add', '^':'Power'}[key])
                grid.addWidget(button, row, column)
        self.controls.addLayout(grid)
        actions = QHBoxLayout()
        self.history_button = self.icon_button('History', 'history', self.toggle_history)
        self.history_button.setCheckable(True)
        self.history_button.setToolTip('Show calculation history (Ctrl+H)')
        actions.addWidget(self.icon_button('Clear expression', 'edit-clear', self.clear), 1)
        functions = self.icon_button('Functions', 'calculator', lambda: None)
        menu = QMenu(functions)
        for function, description in (
            ('sqrt', 'Square root'), ('abs', 'Absolute value'), ('ln', 'Natural logarithm'), ('log10', 'Base-10 logarithm'),
        ):
            menu.addAction(f'{description} · {function}(…)', lambda _checked=False, name=function: self.insert_function(name))
        functions.setMenu(menu)
        actions.addWidget(functions, 1)
        actions.addWidget(self.history_button, 1)
        actions.addWidget(self.icon_button('Copy result', 'edit-copy', self.copy_result), 1)
        self.controls.addLayout(actions)
        self.setup_history()
        self.controls.addStretch(1)

        self.shortcuts = []
        for key, action in [('Escape', self.escape), ('Ctrl+R', self.recall),
                            ('Ctrl+H', self.toggle_history)]:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(action)
            self.shortcuts.append(shortcut)
        self.themeChanged.connect(self.refresh_type)
        self.refresh_type()
        self.field.setFocus()
        if expression:
            self.field.setText(expression)
            self.evaluate()

    def button(self, text, action):
        button = QPushButton(text)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setMinimumHeight(36)
        # Keep typing focus in the expression when operating the keypad with a mouse.
        button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        button.clicked.connect(lambda checked=False: action())
        return button

    def icon_button(self, text, icon, action):
        button = self.button(text, action)
        button.setAccessibleName(text)
        button.setToolTip(text)
        button.setProperty('calculatorActionIcon', icon)
        return button

    def setup_history(self):
        self.history_panel = QWidget()
        layout = QVBoxLayout(self.history_panel)
        layout.setContentsMargins(0, 0, 0, 0)
        self.history_note = QLabel('Calculations stay in this window until you close it.')
        self.history_note.setWordWrap(True)
        self.history_note.setObjectName('calculationFeedback')
        layout.addWidget(self.history_note)
        self.history = QListWidget()
        self.history.setObjectName('calculationHistory')
        self.history.setAccessibleName('Previous calculations, newest first')
        self.history.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.history.setMinimumHeight(104)
        self.history.setMaximumHeight(152)
        self.history.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history.currentItemChanged.connect(self.history_selection_changed)
        self.history.itemActivated.connect(self.recall_history)
        layout.addWidget(self.history)

        actions = QHBoxLayout()
        self.history_recall = self.icon_button('Recall calculation', 'edit-undo', self.recall_history)
        self.history_copy = self.icon_button('Copy previous result', 'edit-copy', self.copy_history)
        self.history_clear = self.icon_button('Clear history', 'edit-delete', self.clear_history)
        for button in (self.history_recall, self.history_copy, self.history_clear):
            actions.addWidget(button, 1)
        layout.addLayout(actions)
        self.controls.addWidget(self.history_panel)
        self.history_panel.hide()
        self.history_selection_changed()

    def history_selection_changed(self, *_):
        selected = self.history.currentItem() is not None
        self.history_recall.setEnabled(selected)
        self.history_copy.setEnabled(selected)
        self.history_clear.setEnabled(self.history.count() > 0)

    def toggle_history(self):
        opening = self.history_panel.isHidden()
        if opening:
            self.history_panel.show()
            self.history_button.setChecked(True)
            if self.history.count():
                self.history.setCurrentRow(0)
                self.history.setFocus()
            self.controls.activate()
            self.workspace.ensureWidgetVisible(self.history_panel, 0, 0)
        else:
            self.history_panel.hide()
            self.history_button.setChecked(False)
            self.field.setFocus()
            self.workspace.ensureWidgetVisible(self.field, 0, 0)

    def escape(self):
        if not self.history_panel.isHidden():
            self.toggle_history()
        else:
            self.clear()

    def record_history(self, expression, result):
        data = (expression, result)
        latest = self.history.item(0)
        if latest is not None and latest.data(Qt.ItemDataRole.UserRole) == data:
            return
        label = f'{expression} = {result}'
        item = QListWidgetItem(label)
        item.setToolTip(label)
        item.setData(Qt.ItemDataRole.UserRole, data)
        self.history.insertItem(0, item)
        if self.history.count() > HISTORY_LIMIT:
            self.history.takeItem(HISTORY_LIMIT)
        self.history.setCurrentRow(0)
        self.history_selection_changed()

    def recall_history(self, item=None):
        item = item or self.history.currentItem()
        if item is not None:
            self.field.setText(item.data(Qt.ItemDataRole.UserRole)[0])
            self.edited()
            self.field.setFocus()

    def copy_history(self):
        item = self.history.currentItem()
        if item is not None:
            QApplication.clipboard().setText(item.data(Qt.ItemDataRole.UserRole)[1])
            self.feedback.setText('Copied result')

    def clear_history(self):
        self.history.clear()
        self.last_expression = ''
        self.history_selection_changed()

    def refresh_display(self):
        scale = self.theme['text_scale']
        font = QFont(self.field.font())
        font.setPixelSize(round((36 if self.showing_result else 25) * scale))
        font.setWeight(QFont.Weight.DemiBold if self.showing_result else QFont.Weight.Medium)
        self.field.setFont(font)
        height_font = QFont(font)
        height_font.setPixelSize(round(36 * scale))
        # Reserve the display height so evaluating never shifts the number pad.
        self.field.setMinimumHeight(max(56, QFontMetrics(height_font).height() + 26))
        ink = self.theme['accent_ink'] if self.showing_result else self.theme['text']
        self.field.setStyleSheet(f'font-size: {font.pixelSize()}px; font-weight: {font.weight()}; color: {ink};')

    def refresh_type(self):
        self.refresh_display()
        side = round(16 * self.theme['text_scale'])
        for button in self.findChildren(QPushButton):
            name = button.property('calculatorActionIcon')
            if not name:
                continue
            icon = symbolic_icon(name, self.theme['accent_ink'])
            button.setIcon(icon)
            button.setIconSize(QSize(side, side))
            button.setText(button.accessibleName() if icon.isNull() else '')

    def edited(self):
        if self.showing_result:
            self.showing_result = False
            self.refresh_display()
        self.feedback.clear()

    def insert(self, key):
        if self.showing_result and key not in ('÷', '×', '−', '+', '^', '%'):
            self.field.clear()
        self.field.insert(key)
        self.edited()
        self.field.setFocus()

    def insert_function(self, name):
        selection = self.field.selectedText()
        if self.showing_result and not selection:
            self.field.selectAll()
            selection = self.field.selectedText()
        text = f'{name}({selection})'
        if len(self.field.text()) - len(selection) + len(text) > MAX_EXPRESSION:
            self.feedback.setText('Expression is too long')
            return
        self.field.insert(text)
        if not selection:
            self.field.setCursorPosition(self.field.cursorPosition() - 1)
        self.edited()
        self.field.setFocus()

    def evaluate(self):
        expression = self.field.text().strip()
        if not expression or self.showing_result:
            return
        try:
            result = calculate(expression)
        except CalculationError as error:
            self.feedback.setText(str(error))
            self.field.setFocus()
            return
        self.last_expression = expression
        self.field.setText(result)
        self.showing_result = True
        self.refresh_display()
        self.feedback.setText((expression if len(expression) <= 64 else expression[:61] + '…') + ' =')
        self.record_history(expression, result)
        self.field.setFocus()

    def recall(self):
        if self.last_expression:
            self.field.setText(self.last_expression)
            self.edited()
            self.field.setFocus()

    def clear(self):
        self.field.clear()
        self.edited()
        self.field.setFocus()

    def copy_result(self):
        if self.field.text().strip() and not self.showing_result:
            self.evaluate()
        if self.showing_result:
            QApplication.clipboard().setText(self.field.text())
            self.feedback.setText('Copied result')


def main():
    app = QApplication([sys.argv[0]])
    app.setApplicationName('Calculator')
    app.setOrganizationName('Mellipi')
    app.setDesktopFileName('mellipi-calculator')
    app.setWindowIcon(QIcon.fromTheme('mellipi-calculator', QIcon.fromTheme('accessories-calculator')))
    window = Calculator(' '.join(sys.argv[1:]))
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
