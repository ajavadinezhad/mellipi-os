import json
import tempfile
import unittest
from pathlib import Path

from preferences import Preferences


class AutoGridPreferencesTest(unittest.TestCase):
    def test_legacy_grid_count_migrates_but_disabled_choice_survives(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            path.write_text(json.dumps({'windowPlacement': 'grid-7', 'windowPlacementEnabled': False}))
            values = Preferences(path).values
            self.assertEqual(values['windowPlacement'], 'auto')
            self.assertFalse(values['windowPlacementEnabled'])
            self.assertTrue(Preferences(Path(folder) / 'new.json').values['windowPlacementEnabled'])

    def test_icon_sizes_are_independent_and_only_supported_values_persist(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            preferences = Preferences(path)
            preferences.update(dict(taskbarIconScale=75, desktopIconScale=150))
            values = Preferences(path).values
            self.assertEqual((values['taskbarIconScale'], values['desktopIconScale']), (75, 150))
            for bad in (True, '150', 300):
                with self.assertRaises(ValueError):
                    preferences.set('taskbarIconScale', bad)
