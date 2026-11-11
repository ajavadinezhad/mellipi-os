import os
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch

from action_targets import SETTING_TARGETS
from qt_compat import QT5
from native_app import Bridge
from system_services import SystemServices, set_audio_device


class AuditedWorkflowsTest(TestCase):
    @skipUnless(QT5, "Mellipi Files uses Qt 5")
    def test_file_rename_prefills_selected_name_and_queues_work(self):
        from mellipi_files import Files
        source = Path('/tmp/example.txt')
        files = SimpleNamespace(selected=lambda: [source], ask_name=Mock(return_value='renamed.txt'),
                                run_job=Mock())
        Files.rename(files)
        files.ask_name.assert_called_once_with('Rename', 'example.txt')
        operation, = files.run_job.call_args.args
        with patch('mellipi_files.rename_no_replace') as rename:
            operation()
        rename.assert_called_once_with(source, source.with_name('renamed.txt'))

    def test_settings_deep_link_opens_allowlisted_target(self):
        section, tab, target = next(iter(SETTING_TARGETS.values()))
        bridge = SimpleNamespace(openSettingsSection=Mock(), interactionChanged=Mock())
        Bridge.openSettingsTarget(bridge, section, tab, target)
        bridge.openSettingsSection.assert_called_once_with(section)
        self.assertEqual(bridge._settingsTarget['target'], target)
        bridge.interactionChanged.emit.assert_called_once()

    def test_selecting_default_microphone_leaves_live_streams_alone(self):
        with patch('system_services.audio_devices', return_value=[{'name': 'wired'}]), \
             patch('system_services.run') as run:
            set_audio_device('wired', True)
        run.assert_called_once_with(['pactl', 'set-default-source', 'wired'])

    def test_suspend_aborts_when_required_lock_fails(self):
        service = SimpleNamespace(submit=Mock())
        with patch.dict(os.environ, {}, clear=True):
            SystemServices.power(service, 'suspend')
        key, action = service.submit.call_args.args
        self.assertEqual(key, 'power')
        with patch('preferences.Preferences', return_value=SimpleNamespace(values={'lockBeforeSleep': True})), \
             patch('screen_lock.launch_and_wait', side_effect=RuntimeError('lock failed')), \
             patch('system_services.run') as run:
            with self.assertRaisesRegex(RuntimeError, 'lock failed'):
                action()
        run.assert_not_called()
