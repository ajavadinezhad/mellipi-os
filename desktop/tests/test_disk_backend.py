import tempfile
import unittest
from pathlib import Path

from disk_backend import ATA, BLOCK, DRIVE, FS, NVME, PART, SWAP, TABLE, _image_size, allowed_target, catalog

USB = '/usb'
DISK = '/disk'
VOLUME = '/volume'


def fixture():
    return {
        USB: {DRIVE: {'ConnectionBus': 'usb', 'Removable': True, 'MediaAvailable': True,
                      'Model': 'USB drive', 'Serial': 'test-original'}},
        DISK: {BLOCK: {'Drive': USB, 'Size': 1000000, 'DeviceNumber': 1234,
                       'Device': b'/dev/sdz\0'}, TABLE: {}},
        VOLUME: {BLOCK: {'Drive': USB, 'Size': 800000, 'DeviceNumber': 1235,
                         'Device': b'/dev/sdz1\0'}, PART: {'Number': 1},
                 FS: {'MountPoints': []}},
    }


class UsbTargetTests(unittest.TestCase):
    def setUp(self):
        self.objects = fixture()
        self.disk, self.volume = catalog(self.objects)
        self.no_holders = lambda _: False

    def test_only_whole_disk_can_receive_image_and_only_partition_can_be_formatted(self):
        self.assertEqual(allowed_target(self.objects, self.disk, 'image', self.no_holders), self.disk)
        self.assertEqual(allowed_target(self.objects, self.volume, 'format', self.no_holders), self.volume)
        with self.assertRaises(ValueError):
            allowed_target(self.objects, self.volume, 'image', self.no_holders)
        with self.assertRaises(ValueError):
            allowed_target(self.objects, self.disk, 'format', self.no_holders)

    def test_rejects_in_use_or_system_members_of_selected_device(self):
        for interface, attribute, value in (
                (FS, 'MountPoints', [b'/media/user/usb\0']),
                (SWAP, 'Active', True), (BLOCK, 'HintSystem', True)):
            with self.subTest(interface=interface):
                objects = fixture()
                objects[VOLUME].setdefault(interface, {})[attribute] = value
                with self.assertRaises(ValueError):
                    allowed_target(objects, self.disk, 'image', self.no_holders)
        with self.assertRaises(ValueError):
            allowed_target(self.objects, self.disk, 'image', lambda number: number == self.volume.number)

    def test_rejects_replaced_targets_and_internal_disks(self):
        self.objects[USB][DRIVE]['Serial'] = 'test-replacement'
        with self.assertRaises(ValueError):
            allowed_target(self.objects, self.disk, 'image', self.no_holders)
        self.objects[USB][DRIVE]['ConnectionBus'] = 'ata'
        disk = catalog(self.objects)[0]
        self.assertFalse(disk.writable_usb)
        with self.assertRaises(ValueError):
            allowed_target(self.objects, disk, 'image', self.no_holders)

    def test_image_size_requires_nonempty_regular_file(self):
        with tempfile.TemporaryDirectory() as directory:
            with (Path(directory) / 'image.iso').open('w+b') as image:
                image.write(b'short')
                image.flush()
                with self.assertRaises(ValueError):
                    _image_size(image.fileno())
                image.truncate(4096)
                self.assertEqual(_image_size(image.fileno()).st_size, 4096)

    def test_drive_menu_tracks_the_selected_target(self):
        from dataclasses import replace
        from unittest.mock import patch
        from PyQt6.QtWidgets import QApplication
        from mellipi_disks import Disks

        app = QApplication.instance() or QApplication([])
        with patch.object(Disks, 'refresh'):
            window = Disks()
        try:
            system = replace(self.volume, path='/system', drive='/system-drive',
                             writable_usb=False, mounts=('/',), system=True, filesystem='ext4')
            window.populate([self.disk, self.volume, system], None)
            self.assertTrue(window.image_action.isEnabled())
            self.assertFalse(window.format_action.isEnabled())
            window.volumes.setCurrentItem(window.volumes.topLevelItem(0).child(0))
            self.assertFalse(window.image_action.isEnabled())
            self.assertTrue(window.format_action.isEnabled())
            window.volumes.setCurrentItem(window.volumes.topLevelItem(1))
            self.assertFalse(window.more_button.isEnabled())
            self.assertTrue(window.open_button.isEnabled())
            self.assertFalse(window.mount_button.isEnabled())
            window.show()
            window.resize(900, 480)
            app.processEvents()
            self.assertGreater(window.inspector.x(), window.volumes.x())
            self.assertEqual(window.mount_status.text(), '/')
            window.resize(440, 300)
            app.processEvents()
            self.assertLess(window.inspector.y(), window.volumes.y())
            self.assertIn('Mounted', window.device_summary.text())
            self.assertTrue(window.inspector.rect().contains(window.mount_button.geometry()))
        finally:
            window.close()
            app.processEvents()


class DriveHealthTests(unittest.TestCase):
    def test_unavailable_disabled_and_unsampled_are_not_reported_healthy(self):
        for ata, status in (
                ({}, 'Unavailable'),
                ({'SmartSupported': True}, 'Disabled on this drive'),
                ({'SmartSupported': True, 'SmartEnabled': True, 'SmartFailing': True}, 'No cached reading yet')):
            with self.subTest(status=status):
                objects = fixture()
                objects[USB][ATA] = ata
                health = catalog(objects)[0].health
                self.assertEqual(health.status, status)
                self.assertFalse(health.warnings)
                self.assertIsNone(health.temperature_c)

    def test_ata_health_is_shared_with_partition_but_does_not_change_identity(self):
        objects = fixture()
        original = catalog(objects)[0]
        objects[USB][DRIVE]['Revision'] = '3.1'
        objects[USB][ATA] = {'SmartSupported': True, 'SmartEnabled': True, 'SmartUpdated': 1700000000,
                             'SmartFailing': False, 'SmartPowerOnSeconds': 7200, 'SmartTemperature': 310.15,
                             'SmartNumBadSectors': 2, 'SmartNumAttributesFailing': 1}
        disk, partition = catalog(objects)
        self.assertEqual(disk.identity, original.identity)
        self.assertIs(disk.health, partition.health)
        self.assertEqual((disk.connection, disk.firmware), ('USB', '3.1'))
        self.assertEqual((disk.health.status, disk.health.bad_sectors, disk.health.power_hours),
                         ('Warning reported', 2, 2))
        self.assertEqual(disk.health.temperature_c, 37)
        self.assertEqual(len(disk.health.warnings), 2)

    def test_nvme_warns_about_read_only_and_keeps_missing_metrics_unknown(self):
        objects = fixture()
        objects[USB][NVME] = {'SmartUpdated': 1700000000, 'SmartCriticalWarning': ['readonly']}
        disk = catalog(objects)[0]
        self.assertEqual(disk.connection, 'NVMe')
        self.assertEqual(disk.health.warnings, ('Media is read-only',))
        self.assertIsNone(disk.health.temperature_c)
        self.assertIsNone(disk.health.bad_sectors)
        objects[USB][NVME]['SmartCriticalWarning'] = []
        self.assertEqual(catalog(objects)[0].health.status, 'No warnings reported')
