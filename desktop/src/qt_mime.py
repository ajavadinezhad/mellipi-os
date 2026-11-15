from qt_compat import QT5, QT6_WAYLAND
if QT5:
    from PyQt5.QtCore import QMimeData
elif QT6_WAYLAND:
    from PyQt6.QtCore import QMimeData
else:
    from PySide6.QtCore import QMimeData
