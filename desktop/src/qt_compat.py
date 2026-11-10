"""Qt 6 for the existing X11 runtime; distro-matched Qt 5 for KDE layer-shell."""
import os
QT5=os.environ.get('ORBIT_QT')=='5'
if QT5:
    from PyQt5.QtCore import QObject, pyqtProperty as Property, pyqtSignal as Signal, pyqtSlot as Slot, QTimer, QUrl, Qt, QSize, QLockFile, QEvent, QSocketNotifier,QPointF,QCoreApplication
    from PyQt5.QtGui import QIcon,QColor,QImage,QPainter,QFont,QDesktopServices,QRegion
    from PyQt5.QtWidgets import QApplication,QSystemTrayIcon,QMenu
    from PyQt5.QtQml import QQmlApplicationEngine
    from PyQt5.QtQuick import QQuickImageProvider,QQuickWindow,QQuickItem
    from PyQt5.QtNetwork import QLocalServer
else:
    from PySide6.QtCore import QObject,Property,Signal,Slot,QTimer,QUrl,Qt,QSize,QLockFile,QEvent,QSocketNotifier,QPointF,QCoreApplication
    from PySide6.QtGui import QIcon,QColor,QImage,QPainter,QFont,QDesktopServices,QRegion
    from PySide6.QtWidgets import QApplication,QSystemTrayIcon,QMenu
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickImageProvider,QQuickWindow,QQuickItem
    from PySide6.QtNetwork import QLocalServer

def dispose_native_io(obj):
    """Close native Qt I/O on its owning GUI thread before Python GC can run.

    Call only after disconnecting callbacks/stopping workers in close(). Keep
    the model alive for readers, but don't leave its watch engine for a future
    worker-thread cyclic collection. No global GC policy or idle timer is used.
    """
    obj.deleteLater()
    QCoreApplication.sendPostedEvents(obj,QEvent.Type.DeferredDelete)
