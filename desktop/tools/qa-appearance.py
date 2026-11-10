#!/usr/bin/env python3
"""Finite Qt6/offscreen visual checks using temporary preferences and context data.

Run with .venv/bin/python tools/qa-appearance.py [--output-dir /tmp/orbit-appearance-qa].
Only Orbit's own surfaces are rendered. No live desktop settings are changed.
"""
import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir', type=Path, default=Path('/tmp/orbit-appearance-qa'))
args = parser.parse_args()
args.output_dir.mkdir(parents=True, exist_ok=True)

# Set isolation before importing the bridge or its database module.
settings_directory = tempfile.TemporaryDirectory(prefix='orbit-appearance-qa-')
os.environ.update(QT_QPA_PLATFORM='offscreen', QT_QUICK_BACKEND='software', DISPLAY='', ORBIT_SETTINGS_FILE=str(Path(settings_directory.name) / 'settings.json'), ORBIT_DATA=settings_directory.name)
# Offscreen surfaces are not continuously exposed, so render settled states.
Path(os.environ['ORBIT_SETTINGS_FILE']).write_text(json.dumps({'reducedMotion': True}))
for key in ('SWAYSOCK', 'WAYLAND_DISPLAY', 'ORBIT_QT', 'ORBIT_TEST_SERVICES'):
    os.environ.pop(key, None)

import native_app
from qt_compat import QObject, QPainter, QTimer

checks = []
failures = []
CASES = [
    ('style', 0, {'mode': 'light', 'corners': 'square', 'accent': '#a8c9ff', 'compact': True}),
    ('black', 0, {'mode': 'dark', 'darkLevel': 'black', 'wallpaper': 'auto'}),
    ('desktop', 1, {'mode': 'dark', 'corners': 'soft', 'dockAlign': 'right', 'wallpaper': 'solid', 'backgroundColor': '#263849', 'clock24': True, 'clockDate': False}),
    ('motion', 2, {'corners': 'rounded', 'dockAlign': 'left', 'wallpaper': 'dusk', 'reducedMotion': True, 'workspaceMotion': False}),
]


def guarded(function):
    def invoke():
        try:
            function()
        except Exception as error:
            failures.append(str(error))
            print('Appearance QA failed: ' + str(error), file=sys.stderr, flush=True)
            native_app.QApplication.instance().exit(1)
    return invoke


class AppearanceEngine(native_app.QQmlApplicationEngine):
    def load(self, url):
        super().load(url)
        if not self.rootObjects():
            return
        self.qa_root = self.rootObjects()[0]
        self.qa_bridge = self.rootContext().contextProperty('Orbit')
        self.qa_case = 0
        # Native smoke visits other pages until 2250 ms. Begin only after those
        # visits settle, then advance cases sequentially rather than on a clock.
        QTimer.singleShot(2400, guarded(self.select_next))
        QTimer.singleShot(8000, guarded(self.timeout))

    def select_next(self):
        if self.qa_case == len(CASES):
            self.verify_complete()
            native_app.QApplication.instance().quit()
            return
        name, section, preferences = CASES[self.qa_case]
        panel = self.qa_root.findChild(QObject, 'appearancePanel')
        assert panel is not None, 'Appearance panel was not instantiated'
        for key, value in preferences.items():
            self.qa_bridge.setPreference(key, value)
        assert panel.setProperty('section', section), 'Could not select ' + name
        self.qa_deadline = time.monotonic() + 1.6
        self.qa_previous_size = None
        self.qa_stable_frames = 0
        self.request_frame()

    def request_frame(self):
        # Offscreen windows are not continuously exposed. Request a frame and
        # allow layout/polish events to run before examining rendered pixels.
        for window_name in ('desktopSurface', 'topbarSurface', 'dockSurface', 'overlaySurface'):
            window = self.qa_root.findChild(QObject, window_name)
            window.requestUpdate()
        QTimer.singleShot(60, guarded(self.verify_settled))

    def verify_settled(self):
        name, section, preferences = CASES[self.qa_case]
        panel = self.qa_root.findChild(QObject, 'appearancePanel')
        overlay = self.qa_root.findChild(QObject, 'overlaySurface')
        assert panel is not None and panel.property('section') == section, name + ' tab changed unexpectedly'
        assert overlay.isVisible(), name + ' panel is hidden'
        assert not self.qa_bridge.qmlErrors, self.qa_bridge.qmlErrors
        panel_image = overlay.grabWindow()
        size = (float(panel.property('width')), float(panel.property('height')), overlay.width(), overlay.height())
        rendered = not panel_image.isNull() and panel_image.pixelColor(panel_image.width() // 2, panel_image.height() // 2).alpha() > 0
        usable = 0 < size[0] <= size[2] and 0 < size[1] <= size[3]
        if rendered and usable and size == self.qa_previous_size:
            self.qa_stable_frames += 1
        else:
            self.qa_stable_frames = 0
        self.qa_previous_size = size
        if self.qa_stable_frames < 2:
            assert time.monotonic() < self.qa_deadline, name + ' did not reach a stable, nontransparent render'
            self.request_frame()
            return
        for key, value in preferences.items():
            assert self.qa_bridge.preferences.values[key] == value, key + ' did not apply'

        desktop = self.qa_root.findChild(QObject, 'desktopSurface')
        image = desktop.grabWindow()
        assert not image.isNull(), 'Desktop render is empty'
        painter = QPainter(image)
        for window_name in ('topbarSurface', 'dockSurface', 'overlaySurface'):
            window = self.qa_root.findChild(QObject, window_name)
            if window.isVisible():
                snapshot = panel_image if window_name == 'overlaySurface' else window.grabWindow()
                painter.drawImage(window.x() - desktop.x(), window.y() - desktop.y(), snapshot)
        painter.end()
        screenshot = args.output_dir / (name + '.png')
        assert image.save(str(screenshot)), 'Could not save ' + str(screenshot)
        checks.append({'tab': name, 'width': size[0], 'height': size[1], 'screenshot': str(screenshot.resolve())})
        self.qa_case += 1
        QTimer.singleShot(60, guarded(self.select_next))

    def verify_complete(self):
        assert len(checks) == len(CASES), 'Only ' + str(len(checks)) + ' appearance tabs completed'
        assert not self.qa_bridge.qmlErrors, self.qa_bridge.qmlErrors

    def timeout(self):
        raise AssertionError('Appearance QA exceeded its eight-second limit')


class SmokeTimers(QTimer):
    @staticmethod
    def singleShot(delay, callback):
        # Extend only the native smoke's final capture; its page visitation and
        # all product timers keep their normal behavior. QA quits by eight secs.
        if delay == 2900 and getattr(callback, '__name__', '') == 'snapshot':
            delay = 8500
        return QTimer.singleShot(delay, callback)


native_app.QQmlApplicationEngine = AppearanceEngine
native_app.QTimer = SmokeTimers
sys.argv = ['native_app.py', '--smoke-test', '--initial-panel', 'settings']
try:
    result = native_app.main()
    if len(checks) != len(CASES):
        failures.append('Incomplete appearance checks')
    print(json.dumps({'appearance_tabs': checks, 'failures': failures}), flush=True)
    sys.exit(result or bool(failures))
finally:
    settings_directory.cleanup()
