"""On-demand Xwayland clipboard owner; no windows, focus changes or polling.

Qt Wayland selection writes require keyboard focus. Screenshot capture restores
app focus before completing, so publish PNG bytes through Xwayland's selection
bridge instead. This process exists only while it owns this clipboard item.
"""
import os
import select
import subprocess
from pathlib import Path


def publish_png(path):
    environment=dict(os.environ,QT_QPA_PLATFORM='xcb')
    if not environment.get('DISPLAY'):raise RuntimeError('Screenshot clipboard needs the session Xwayland display')
    process=subprocess.Popen(['/usr/bin/python3',str(Path(__file__).resolve()),str(path)],env=environment,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True)
    try:
        ready,_,_=select.select([process.stdout],[],[],4)
        if not ready or process.stdout.readline()!=b'READY\n':raise RuntimeError('Screenshot clipboard ownership could not be established')
    except Exception:
        process.terminate();process.wait(timeout=2);raise
    finally:process.stdout.close()
    return process


def main(path):
    from PyQt5.QtCore import QMimeData,QTimer
    from PyQt5.QtGui import QGuiApplication
    data=Path(path).read_bytes()
    if not data.startswith(b'\x89PNG\r\n\x1a\n') or len(data)>100_000_000:raise ValueError('Invalid screenshot PNG')
    app=QGuiApplication(['orbit-screenshot-clipboard']);clipboard=app.clipboard()
    ready=False
    def changed():
        if ready and not clipboard.ownsClipboard():app.quit()
    def confirm():
        nonlocal ready
        if not clipboard.ownsClipboard():app.exit(1);return
        ready=True;print('READY',flush=True)
    def publish():
        mime=QMimeData();mime.setData('image/png',data);clipboard.setMimeData(mime)
        QTimer.singleShot(100,confirm)
    clipboard.dataChanged.connect(changed);QTimer.singleShot(0,publish)
    return app.exec_()

if __name__=='__main__':
    import sys
    sys.exit(main(sys.argv[1]))
