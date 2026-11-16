"""Bounded launch feedback; no polling or player process while idle."""
from pathlib import Path
import shutil
import time


class LaunchCue:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.requests = {}
        self.first = 0

    def begin(self, token, ident, windows):
        now = self.clock()
        if not self.requests:
            self.first = now
        known = set(windows)
        self.requests[token] = (ident, known, now + 4.5)

    def cancel(self, token):
        self.requests.pop(token, None)

    def observe(self, groups):
        for group in groups:
            ident = group['id']
            current = {window['id'] for window in group['windows']}
            pending = [token for token, (app, _, _) in self.requests.items() if app == ident]
            for token in pending:
                added = current - self.requests[token][1]
                if not added:
                    continue
                newest = min(added)
                self.cancel(token)
                for key, (app, known, deadline) in tuple(self.requests.items()):
                    if app == ident:
                        self.requests[key] = (app, known | {newest}, deadline)

    def visible(self):
        now = self.clock()
        for token, (_, _, deadline) in tuple(self.requests.items()):
            if now >= deadline:
                self.cancel(token)
        return bool(self.requests) and now - self.first >= .18


class EventSounds:
    names = frozenset(('launch', 'workspace', 'error'))

    def __init__(self, directory):
        self.directory = Path(directory)
        self.player = None
        self.process = None
        self.last = 0

    def play(self, name):
        if name not in self.names or time.monotonic() - self.last < .18:
            return
        from qt_compat import QProcess
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            return
        if self.player is None:
            self.player = shutil.which('pw-play') or shutil.which('paplay') or ''
        if not self.player:
            return
        if self.process is None:
            self.process = QProcess()
            self.process.setStandardOutputFile(QProcess.nullDevice())
            self.process.setStandardErrorFile(QProcess.nullDevice())
        self.process.start(self.player, [str(self.directory / (name + '.wav'))])
        self.last = time.monotonic()

    def close(self):
        if self.process and self.process.state() != self.process.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(500)
