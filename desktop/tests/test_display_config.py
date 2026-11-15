"""Display requests arriving from the separate QML Settings window."""
import json
import unittest

from display_config import command, validated


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
