"""Window controls shared by Mellipi Qt applications."""
from PyQt6.QtCore import QEvent, QSize, Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QPushButton
from window_controls import glyph_svg


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
        self.cyberpunk = False
        for glyph, action in (('minimize', window.showMinimized),
                              ('maximize', self.toggle_maximized),
                              ('close', window.close)):
            button = QPushButton()
            button.clicked.connect(action)
            button.setObjectName('windowControl')
            button.setFixedSize(32, 28)
            button.setIconSize(QSize(16, 16))
            self.controls[glyph] = button
            layout.addWidget(button)
        window.installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched is self.owner and event.type() == QEvent.Type.WindowStateChange:
            self.update_controls(self.control_ink, self.cyberpunk)
        return super().eventFilter(watched, event)

    def update_controls(self, ink, cyberpunk=False):
        self.control_ink = ink
        self.cyberpunk = cyberpunk
        for name, button in self.controls.items():
            glyph = 'restore' if name == 'maximize' and self.owner.isMaximized() else name
            icon = QIcon()
            for size in (16, 24, 32, 48):
                pixmap = QPixmap()
                if pixmap.loadFromData(glyph_svg(glyph, ink, cyberpunk, size=size), 'SVG'):
                    icon.addPixmap(pixmap)
            button.setIcon(icon)
            button.setAccessibleName(glyph.capitalize())
            button.setToolTip(glyph.capitalize())

    def toggle_maximized(self):
        if self.owner.isMaximized():
            self.owner.showNormal()
        else:
            self.owner.showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.owner.windowHandle().startSystemMove():
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
        else:
            super().mouseDoubleClickEvent(event)
