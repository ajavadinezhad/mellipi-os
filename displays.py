"""Read-only monitor selection driven by Qt screen events, without polling.

Persistence belongs to the caller: store requestedName, not selectedName, so a
preferred monitor can return after an unplug/replug cycle. An empty request
tracks the system's current primary screen.
"""
from qt_compat import QObject, Property, Signal, Slot


class DisplaySettings(QObject):
    changed = Signal()

    def __init__(self, app, requested_name='', parent=None):
        super().__init__(parent)
        self.app = app
        self._requested = self._validate_name(requested_name)
        self._transient = ''
        self._rows = []
        self._selected = None
        self._selected_name = ''
        self._screen_signals = {}
        self._app_signals = []
        self._closed = False
        for name in ('screenAdded', 'screenRemoved', 'primaryScreenChanged'):
            signal = getattr(app, name, None)
            if signal is not None:
                signal.connect(self._topology_changed)
                self._app_signals.append((signal, self._topology_changed))
        self._refresh()

    @staticmethod
    def _validate_name(name):
        if not isinstance(name, str) or len(name) > 256:
            raise ValueError('Invalid monitor name')
        return name

    def _disconnect(self, signals):
        for signal, callback in signals:
            try:
                signal.disconnect(callback)
            except (RuntimeError, TypeError):
                # QScreen can already have been destroyed during hot unplug.
                pass

    def _watch_screens(self, screens):
        live_ids = {id(screen) for screen in screens}
        for ident in set(self._screen_signals) - live_ids:
            self._disconnect(self._screen_signals.pop(ident))
        for screen in screens:
            if id(screen) in self._screen_signals:
                continue
            signals = []
            for name in ('geometryChanged', 'availableGeometryChanged', 'logicalDotsPerInchChanged'):
                signal = getattr(screen, name, None)
                if signal is not None:
                    signal.connect(self._screen_changed)
                    signals.append((signal, self._screen_changed))
            self._screen_signals[id(screen)] = signals

    def _topology_changed(self, *_):
        self._refresh()

    def _screen_changed(self, *_):
        # Also notify for DPI/work-area changes that leave the geometry equal.
        self._refresh(force=True)

    def _refresh(self, force=False):
        if self._closed:
            return
        primary = self.app.primaryScreen()
        rows, screens = [], []
        for screen in self.app.screens():
            try:
                geometry = screen.geometry()
                rows.append(dict(name=screen.name(), width=geometry.width(), height=geometry.height(), x=geometry.x(), y=geometry.y(), primary=screen is primary))
                screens.append(screen)
            except RuntimeError:
                # The display server may remove a QScreen before this callback.
                continue
        self._watch_screens(screens)
        target=self._transient or self._requested
        selected = next((screen for screen, row in zip(screens, rows) if target and row['name'] == target), None)
        if self._transient and selected is None:
            self._transient=''
            selected=next((screen for screen,row in zip(screens,rows) if self._requested and row['name']==self._requested),None)
        if selected is None:
            selected = next((screen for screen in screens if screen is primary), screens[0] if screens else None)
        selected_name = next((row['name'] for screen, row in zip(screens, rows) if screen is selected), '')
        changed = rows != self._rows or selected is not self._selected or selected_name != self._selected_name
        self._rows, self._selected, self._selected_name = rows, selected, selected_name
        if force or changed:
            self.changed.emit()

    values = Property('QVariantList', lambda self: [dict(row) for row in self._rows], notify=changed)
    requestedName = Property(str, lambda self: self._requested, notify=changed)
    selectedName = Property(str, lambda self: self._selected_name, notify=changed)
    selectedScreen = Property(QObject, lambda self: self._selected, notify=changed)

    def screen(self):
        """Return the resolved QScreen, or None while no displays are present."""
        return self._selected

    @Slot(str)
    def setRequestedName(self, name):
        name = self._validate_name(name)
        if name == self._requested and not self._transient:
            return
        self._requested = name
        self._transient = ''
        self._refresh(force=True)

    def setTransientName(self,name):
        name=self._validate_name(name)
        if name==self._selected_name:return
        if not any(row['name']==name for row in self._rows):return
        self._transient=name;self._refresh(force=True)

    def close(self):
        """Disconnect observers when replacing or explicitly disposing the model."""
        if self._closed:
            return
        self._closed = True
        self._disconnect(self._app_signals)
        self._app_signals.clear()
        for signals in self._screen_signals.values():
            self._disconnect(signals)
        self._screen_signals.clear()
