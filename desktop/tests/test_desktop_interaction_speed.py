"""Functional regressions for desktop command latency; no physical devices."""
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from arrangements import ArrangementEngine
from brightness import BrightnessControls
from native_app import Bridge
from qt_compat import QApplication, QObject, Signal
from settings_host import SettingsHost
from system_services import SystemServices


AREA = dict(x=0, y=32, width=800, height=560)
RECT = dict(x=80, y=92, width=400, height=280)


class DesktopInteractionTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def until(self, condition):
        deadline = time.monotonic() + 2
        while not condition():
            if time.monotonic() > deadline:
                self.fail('Timed out waiting for the private desktop fixture')
            self.app.processEvents()
            time.sleep(.005)

    def test_wifi_shows_cache_and_connects_during_a_held_scan(self):
        service = SystemServices(enabled=False)
        self.addCleanup(service.close)
        service.state['wifiEnabled'] = True
        scan_started, release_scan, connected = (threading.Event() for _ in range(3))
        cache_reads = []
        cached = [dict(ssid='Known network', active=False)]
        joined = [dict(ssid='Known network', active=True)]

        def scan(rescan):
            if rescan:
                scan_started.set()
                release_scan.wait(5)
                raise RuntimeError('Obsolete scan failed')
            cache_reads.append(1)
            return cached if len(cache_reads) == 1 else joined

        def execute(args):
            if 'connect' in args:
                self.assertEqual(args[-1], 'Known network')
                connected.set()
            return 'connected:full:enabled'

        with patch('system_services.wifi_scan', side_effect=scan), patch('system_services.run', side_effect=execute):
            try:
                service.refreshWifi()
                self.until(lambda:scan_started.is_set() and service.state['wifiNetworks']==cached)
                service.connectWifi('Known network', '')
                self.until(lambda:connected.is_set() and not service.state['wifiConnecting'])
                self.assertTrue(service.state['wifiScanning'])
            finally:
                release_scan.set()
            self.until(lambda:service.state['wifiNetworks']==joined)
        self.assertEqual(service.state['wifiError'], '')

    def test_failed_wifi_join_refreshes_cache_without_hiding_the_error(self):
        service = SystemServices(enabled=False)
        self.addCleanup(service.close)
        service.state['wifiEnabled'] = True
        scan_started, release_scan = threading.Event(), threading.Event()
        cached = [dict(ssid='Old result', active=False)]
        updated = [dict(ssid='Known network', active=False)]
        reads = []

        def scan(rescan):
            if rescan:
                scan_started.set()
                release_scan.wait(5)
                return [dict(ssid='Obsolete result', active=True)]
            reads.append(1)
            return cached if len(reads) == 1 else updated

        def execute(args):
            if 'connect' in args:
                raise RuntimeError('Wrong password')
            return 'disconnected:none:enabled'

        with patch('system_services.wifi_scan', side_effect=scan), patch('system_services.run', side_effect=execute):
            try:
                service.refreshWifi()
                self.until(lambda:scan_started.is_set() and service.state['wifiNetworks']==cached)
                service.connectWifi('Known network', '')
                self.until(lambda:'Wrong password' in service.state['wifiError'])
            finally:
                release_scan.set()
            self.until(lambda:service.state['wifiNetworks']==updated)
        self.assertIn('Wrong password', service.state['wifiError'])

    def test_workspace_intents_keep_latest_request_independently_per_output(self):
        from queue import Empty, Queue
        callbacks = Queue()
        bridge = SimpleNamespace(_windowPool=None, _windowPending=set(), isWayland=False,
                                 frameChanged=Mock(), notify=Mock(),
                                 completed=SimpleNamespace(emit=callbacks.put))
        started, release = threading.Event(), threading.Event()
        requests = []
        def hold():
            started.set()
            release.wait(5)
        def send(output, number):
            return Bridge.windowTask(bridge,output,'workspace-output',
                                     lambda:requests.append((output,number)))
        def pump():
            while True:
                try: callbacks.get_nowait()()
                except Empty:return not bridge._windowPending
        try:
            Bridge.windowTask(bridge,'fixture','hold',hold)
            self.assertTrue(started.wait(2))
            self.assertTrue(send('HDMI-A-1',2))
            self.assertTrue(send('DP-1',3))
            self.assertTrue(send('HDMI-A-1',4))
            release.set()
            self.until(pump)
            self.assertEqual(requests,[('HDMI-A-1',4),('DP-1',3)])
            bridge.notify.assert_not_called()
        finally:
            release.set()
            Bridge.closeWindowTasks(bridge)

    def test_settings_focus_waits_for_ready_and_mapped_events_without_retries(self):
        class Shell(QObject):
            windowsChanged=Signal()
            _windows=[]
            windowActions=None
            rememberSettingsSection=Mock()
            focusWindow=Mock()
            notify=Mock()

        shell=Shell()
        server=Mock()
        with tempfile.TemporaryDirectory() as temp, patch('settings_host.socket_path', return_value=temp+'/control'), \
                patch('settings_host.QLocalServer',return_value=server):
            host=SettingsHost(shell,{})
            host.send=Mock()
            host.process=Mock(poll=Mock(return_value=None))
            client=Mock()
            host.clients[client]=bytearray()
            try:
                host.show(9)
                shell.windowsChanged.emit()
                self.assertTrue(host.show_timeout.isActive())
                shell._windows=[dict(id='settings',klass='orbit-settings')]
                shell.windowsChanged.emit()
                shell.focusWindow.assert_not_called()
                client.readAll.return_value=b'{"ready":true}\n'
                host.read(client)
                shell.focusWindow.assert_called_once_with('settings')
                self.assertFalse(host.show_timeout.isActive())
                self.assertFalse(host.show_pending)
                host.send.assert_called_once_with(client,{'show':True})
                shell.windowsChanged.emit()
                shell.focusWindow.assert_called_once()
                host.show(10)
                self.assertEqual(shell.focusWindow.call_count,2)
                self.assertFalse(host.show_timeout.isActive())
            finally:
                host.close()

    def test_settings_retires_only_its_unready_child_and_allows_retry(self):
        class Shell(QObject):
            windowsChanged=Signal()
            _windows=[]
            windowActions=None
            rememberSettingsSection=Mock()
            notify=Mock()

        shell=Shell()
        with tempfile.TemporaryDirectory() as temp, patch('settings_host.socket_path',return_value=temp+'/control'), \
                patch('settings_host.QLocalServer', return_value=Mock()):
            host=SettingsHost(shell,{})
            try:
                ready=Mock(poll=Mock(return_value=None))
                host.process=host.show_process=ready
                host.ready=host.show_pending=True
                host.show_timed_out()
                ready.terminate.assert_not_called()
                stalled=Mock(poll=Mock(return_value=None))
                host.process=host.show_process=stalled
                host.show_pending=True;host.ready=False
                host.show_timed_out()
                stalled.terminate.assert_called_once()
                self.assertIsNone(host.show_process)
                host.show(5)
                self.assertTrue(host.show_pending)
                with patch.object(host,'start_show_process') as start:
                    host.process_exited(stalled)
                    start.assert_called_once()
            finally:host.close()

    def test_monitor_reports_requested_value_then_reverts_to_confirmed_readback(self):
        device=dict(id=4,name='Monitor',identity='Monitor A',bus='3',percent=48,maximum=100,backend='ddc')
        with tempfile.TemporaryDirectory() as temp:
            control=BrightnessControls(enabled=False,root=temp)
            self.addCleanup(control.close)
            control._device=device
            control._externalId=4
            control._state=dict(available=True,percent=48,backend='ddc')
            with patch.object(BrightnessControls,'submit') as submit:
                control.setBrightness(76)
                self.assertEqual(control.state['pendingPercent'],76)
                control.setBrightness(85)
                self.assertEqual(control.state['pendingPercent'],85)
                self.assertEqual(submit.call_count,1)
                _, details=submit.call_args
                control.apply(dict(kind='write',device=dict(device,percent=76),**details))
                self.assertEqual(control.state['pendingPercent'],85)
                self.assertEqual(submit.call_count,2)
                _, details=submit.call_args
                control.apply(dict(kind='write',error='Display changed',**details))
                self.assertNotIn('pendingPercent',control.state)
                self.assertEqual(control.state['percent'],76)

    def test_native_restore_uses_one_snapshot_and_rescales_removed_output(self):
        native=Mock()
        native.snapshot.return_value=dict(
            outputs=[dict(name='remaining',rect=AREA,workarea=AREA)],
            desktops=[dict(id=0),dict(id=1)],
            windows=[dict(id=str(ident),pid=ident,klass='test-app',desktop=0,rect=RECT)
                     for ident in range(1,25)])
        actions=SimpleNamespace(client=native,lock=threading.RLock(),saved={},snapped={},_persist=Mock())
        former=dict(x=800,y=32,width=1600,height=1120)
        rows=[dict(id=ident,key=(ident,'test-app',0),desktop=2,
                   rect=dict(x=960,y=152,width=800,height=560),area=former,output='removed',
                   floating=True) for ident in range(1,26)]
        with tempfile.TemporaryDirectory() as temp,patch('arrangements.time.sleep') as sleep:
            engine=ArrangementEngine(actions,Path(temp)/'layouts.json')
            self.assertEqual(engine.restore_rows(rows),dict(applied=24,skipped=1))
            native.snapshot.assert_called_once()
            sleep.assert_not_called()
            self.assertEqual(native.move.call_count,24)
            native.request.assert_any_call('resize',id=1,rect=RECT,output='remaining')

    def test_native_restore_preserves_maximized_state_and_normal_geometry(self):
        native=Mock()
        native.snapshot.return_value=dict(outputs=[dict(name='HDMI-A-1',rect=AREA,workarea=AREA)],
            desktops=[dict(id=0),dict(id=1)],
            windows=[dict(id='1',pid=55,klass='test-app',desktop=0,rect=RECT)])
        actions=SimpleNamespace(client=native,lock=threading.RLock(),saved={},snapped={},_persist=Mock())
        row=dict(id=1,key=(55,'test-app',0),desktop=2,rect=AREA,area=AREA,output='HDMI-A-1',
                 floating=True,snap='maximize',restore_rect=RECT)
        with tempfile.TemporaryDirectory() as temp:
            engine=ArrangementEngine(actions,Path(temp)/'layouts.json')
            self.assertEqual(engine.restore_rows([row],undo=True),dict(applied=1,skipped=0))
        native.move.assert_called_once_with(1,2)
        native.request.assert_called_once_with('snap',id=1,side='maximize',output='HDMI-A-1',restore_rect=RECT)

    def test_window_app_catalog_lookup_is_reused_for_case_variants(self):
        bridge=SimpleNamespace(_apps=[],_appMatchCache={})
        app=dict(id='example.desktop')
        with patch('desktop.match_application',return_value=app) as lookup:
            self.assertIs(Bridge.matchWindowApplication(bridge,dict(klass='Example')),app)
            self.assertIs(Bridge.matchWindowApplication(bridge,dict(klass='example')),app)
            lookup.assert_called_once()

    def test_launcher_closes_on_dispatch_and_failed_activation_is_reported(self):
        bridge=SimpleNamespace(_apps=[dict(id='sample.desktop',name='Sample')],
            _dockApps=[],_launchPool=object(),_launchCue=Mock(),_launchTimer=Mock(),
            appearance={'matchApps':False},panel='launcher',dismiss=Mock(),asyncTask=Mock(),
            playEventSound=Mock(),notify=Mock(),recordAppInteraction=Mock(),
            updateLaunchFeedback=Mock())
        with patch('desktop.application_environment',return_value={}), \
                patch('desktop.application_launch_path',return_value='/test/sample.desktop'), \
                patch('subprocess.Popen'):
            Bridge.launchApplication(bridge,'sample.desktop')
        bridge.dismiss.assert_called_once()
        self.assertTrue(bridge._pendingAppLaunches)
        _,_,failure=bridge.asyncTask.call_args.args
        failure('Dispatch failed')
        self.assertFalse(bridge._pendingAppLaunches)
        bridge.notify.assert_called_once_with('Could not start Sample: Dispatch failed')
