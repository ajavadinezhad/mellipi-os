"""Display requests arriving from the separate QML Settings window."""
import json
import unittest

from display_config import catalog, command, validated


class DisplayRequestTests(unittest.TestCase):
    rows = [{'name': 'HDMI-A-1', 'modes': [{'value': '2560x1080'}]}]

    def request(self, x, y):
        return validated(self.rows, *json.loads(json.dumps(
            ['HDMI-A-1', '2560x1080', 1.25, 'normal', x, y])))

    def test_qml_double_coordinates_become_integers_for_watchdog(self):
        result = self.request(0.0, -1080.0)
        self.assertIs(type(result['x']), int)
        self.assertIs(type(result['y']), int)
        self.assertTrue(command(result).endswith('position 0 -1080'))

    def test_bad_positions_remain_rejected(self):
        for value in (True, '0', 0.5, float('inf'), float('nan'), -32769, 32769.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.request(value, 0)
        self.assertEqual(self.request(-32768.0, 32768.0)['y'], 32768)

    def test_catalog_preserves_current_ultrawide_dimensions_and_skips_incomplete_output(self):
        preferred = dict(width=3440, height=1440, refresh=60000)
        current = dict(width=3240, height=1356, refresh=60000)
        rows = catalog([
            dict(name='DP-1', active=True, current_mode={'width': 2560}, modes=[preferred]),
            dict(name='HDMI-A-1', active=True, current_mode=current, modes=[preferred, None]),
        ])
        self.assertEqual([row['name'] for row in rows], ['HDMI-A-1'])
        self.assertEqual(rows[0]['mode'], '3240x1356@60.000Hz')
        self.assertEqual([(m['width'], m['height']) for m in rows[0]['modes']], [(3440, 1440), (3240, 1356)])

    def test_catalog_marks_standard_modes_without_removing_active_custom_timing(self):
        def mode(width,height,refresh):
            return dict(width=width,height=height,refresh=refresh)
        custom=mode(3240,1356,59930)
        [row]=catalog([dict(name='HDMI-A-1',active=True,current_mode=custom,
                            modes=[mode(3440,1440,59940),mode(3280,1376,57000),
                                   mode(2560,1080,60000),mode(2560,1080,75000)])])
        self.assertEqual([(m['width'],m['height']) for m in row['modes'] if m['standard']],
                         [(3440,1440),(2560,1080),(2560,1080)])
        self.assertEqual(validated([row],row['name'],row['mode'],1.25,'normal',0,0)['mode'],
                         '3240x1356@59.930Hz')
