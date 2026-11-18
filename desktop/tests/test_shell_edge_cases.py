"""Regressions for stale launcher results and display topology snapshots."""
from pathlib import Path
import json
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace
from unittest import TestCase

from display_controls import DisplayControls
from launcher_files import LauncherFiles
from native_app import Bridge
from qt_compat import QApplication
from settings_host import SettingsHost


class ShellEdgeCases(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_for(self, predicate):
        deadline = monotonic() + 3
        while monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            sleep(.01)
        self.fail('Timed out waiting for the private shell fixture')

    def test_display_refresh_coalesces_changes_while_snapshot_is_busy(self):
        def output(name):
            mode = dict(width=1920, height=1080, refresh=60000)
            return dict(name=name, active=True, current_mode=mode, modes=[mode],
                        rect=dict(x=0, y=0, width=1920, height=1080))

        started, release = Event(), Event()
        calls = []

        def request(kind, _payload):
            calls.append(kind)
            if len(calls) == 1:
                started.set()
                if not release.wait(3):
                    raise RuntimeError('Display fixture did not release')
                return [output('DP-1')]
            return [output('DP-2')]

        control = DisplayControls(requester=request)
        try:
            published = []
            control.changed.connect(lambda: published.extend(row['name'] for row in control.outputs))
            control.refresh()
            self.assertTrue(started.wait(1))
            for _ in range(4):
                control.refresh()
            release.set()
            self.wait_for(lambda: [row['name'] for row in control.outputs] == ['DP-2'])
            self.assertEqual(calls, [3, 3])
            self.assertNotIn('DP-1', published)
        finally:
            release.set()
            control.close()

    def test_launcher_rejects_out_of_scope_symlink_and_replaced_result_parent(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            favorite, outside = root / 'favorite', root / 'outside'
            subfolder = favorite / 'sub'
            outside.mkdir()
            subfolder.mkdir(parents=True)
            original = subfolder / 'report.txt'
            original.touch()
            outside_file = outside / original.name
            outside_file.touch()
            (favorite / 'report-link.txt').symlink_to(outside_file)
            settings = SimpleNamespace(sync=lambda: None, value=lambda *_: {str(favorite): 'Work'})
            opened = []
            control = LauncherFiles(settings=settings, opener=lambda uri: opened.append(uri.toLocalFile()) or True)
            try:
                control.refresh()
                control.search(str(favorite), 'report')
                self.wait_for(lambda: control.rows)
                self.assertEqual([row['id'] for row in control.rows], [str(original)])
                subfolder.rename(favorite / 'original')
                subfolder.symlink_to(outside, target_is_directory=True)
                control.open(str(original))
                self.assertEqual(opened, [])
                self.assertFalse(control.rows)
                self.assertIn('changed', control.note)
            finally:
                control.close()

    def test_launcher_cancels_results_when_the_favorite_is_removed(self):
        with TemporaryDirectory() as temp:
            favorite = Path(temp)
            file = favorite / 'report.txt'
            file.touch()
            bookmarks = {str(favorite): 'Work'}
            settings = SimpleNamespace(sync=lambda: None, value=lambda *_: dict(bookmarks))
            opened = []
            control = LauncherFiles(settings=settings, opener=lambda uri: opened.append(uri.toLocalFile()) or True)
            try:
                control.refresh()
                control.search(str(favorite), 'report')
                self.wait_for(lambda: control.rows)
                bookmarks.clear()
                control.open(str(file))  # rechecks even if the launcher remains open
                self.assertEqual(opened, [])
                self.assertEqual(control.rows, [])
                self.assertEqual(control.folders, [])
            finally:
                control.close()

    def test_settings_close_stops_bluetooth_before_marking_window_inactive(self):
        class Client:
            def __init__(self, message):
                self.message = message

            def readAll(self):
                return json.dumps(self.message).encode() + b'\n'

        events = []
        host = SimpleNamespace(active=True, show_process=None, process=None, ready=True,
                               clients={}, send=lambda *_: self.fail('Unexpected Settings error'))
        bridge = SimpleNamespace(_panel='', _settingsPage='bluetooth', settingsHost=host,
                                 bluetoothControls=SimpleNamespace(
                                     stopDiscovery=lambda: events.append('stop discovery'),
                                     cancelPairing=lambda: events.append('cancel pairing')))
        bridge.settingsPageOpened = lambda name: Bridge.settingsPageOpened(bridge, name)
        host.bridge = bridge
        for message in ({'closing': True}, {'visible': False}):
            client = Client(message)
            host.clients[client] = bytearray()
            SettingsHost.read(host, client)
        self.assertFalse(host.active)
        self.assertFalse(host.ready)
        self.assertEqual(bridge._settingsPage, '')
        self.assertEqual(events, ['stop discovery', 'cancel pairing'])
