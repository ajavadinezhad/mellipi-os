"""Lazy, bounded XEmbed-to-SNI compatibility using the distro proxy binary."""
import os,shutil,sys
from pathlib import Path
from qt_compat import QObject,Property,Signal,Slot,QT5
if QT5:
    from PyQt5.QtCore import QProcess,QProcessEnvironment
else:
    from PySide6.QtCore import QProcess,QProcessEnvironment
from project_paths import PROJECT_ROOT as ROOT, SOURCE_ROOT
STOPPED=QProcess.NotRunning if QT5 else QProcess.ProcessState.NotRunning

def proxy_binary():
    local=ROOT/'.tray-runtime/bin/xembedsniproxy'
    return str(local) if local.is_file() and os.access(local,os.X_OK) else shutil.which('xembedsniproxy')

class LegacyProxy(QObject):
    changed=Signal();notice=Signal(str)
    def __init__(self,enabled=True,parent=None,binary=None,diagnostic_log=None):
        super().__init__(parent);self.enabled=enabled;self.binary=binary or proxy_binary();self.process=None;self.error='';self.attempts=0;self.closed=False;self._handlers=[];self.diagnostic_log=diagnostic_log or (os.environ.get("ORBIT_QA_LEGACY_LOG") if os.environ.get("ORBIT_QA")=="1" else None)
    state=Property('QVariantMap',lambda self:dict(available=bool(self.enabled and self.binary),running=self.process is not None and self.process.state()!=STOPPED,error=self.error,attempts=self.attempts),notify=changed)
    @Slot()
    def start(self):
        if self.closed or not self.enabled or self.process is not None and self.process.state()!=STOPPED:return False
        if not (os.environ.get('SWAYSOCK') or os.environ.get('ORBIT_NATIVE_CONTROL')) or not os.environ.get('DISPLAY'):return False
        if self.attempts>=2:return False
        if not self.binary:self.error='Legacy tray compatibility is unavailable; prepare the local tray runtime';self.changed.emit();return False
        self.attempts+=1;self.error='';process=QProcess(self);self.process=process
        from desktop import application_environment
        env=application_environment();env['QT_QPA_PLATFORM']='xcb'
        if self.diagnostic_log:env['QT_LOGGING_RULES']='kde.xembedsniproxy.debug=true'
        if str(ROOT/'.tray-runtime') in self.binary:
            env['LD_LIBRARY_PATH']=str(ROOT/'.tray-runtime/lib');env['QT_PLUGIN_PATH']=str(ROOT/'.tray-runtime/plugins')
        environment=QProcessEnvironment()
        for key,value in env.items():environment.insert(key,value)
        process.setProcessEnvironment(environment);process.setStandardOutputFile(os.devnull);process.setStandardErrorFile(self.diagnostic_log or os.devnull)
        process.setProgram(sys.executable);process.setArguments([str(SOURCE_ROOT/'idle_child.py'),str(os.getpid()),self.binary])
        process.started.connect(self.changed.emit)
        def failed(*_):
            if self.closed:return
            self.error='Legacy tray compatibility could not start: '+process.errorString();self.notice.emit(self.error);self.changed.emit()
        def finished(code,*_):
            if self.closed:return
            if code:self.error='Legacy tray compatibility exited; another tray may already own the X11 icons'
            self.changed.emit()
        self._handlers.append((process,failed,finished))
        process.errorOccurred.connect(failed);process.finished.connect(finished);process.start();self.changed.emit();return True
    def close(self):
        self.closed=True
        if self.process and self.process.state()!=STOPPED:
            self.process.terminate()
            if not self.process.waitForFinished(2000):self.process.kill();self.process.waitForFinished(1000)
