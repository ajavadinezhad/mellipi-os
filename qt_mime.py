from qt_compat import QT5
if QT5:
    from PyQt5.QtCore import QMimeData
else:
    from PySide6.QtCore import QMimeData
