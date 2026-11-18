import tempfile
import unittest
import os
import stat
from pathlib import Path

from disk_backend import ATA, BLOCK, DRIVE, FS, NVME, PART, SWAP, TABLE, _image_size, allowed_target, catalog, removal_target, UDisks

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

    def test_verify_opens_read_only_and_refuses_device_replacement(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        client = object.__new__(UDisks)
        client.dbus = SimpleNamespace(Dictionary=lambda value, **kw: value, Int32=int)
        client.objects = lambda: self.objects
        block = Mock()
        client.interface = lambda path, iface: block
        with tempfile.TemporaryDirectory() as folder:
            image, media = Path(folder) / 'disk.img', Path(folder) / 'usb'
            image.write_bytes(b'i' * 512)
            media.write_bytes(b'i' * 512 + b'data after the image')
            real_fstat = os.fstat
            fd = os.open(media, os.O_RDONLY)
            block.OpenDevice.return_value.take.return_value = fd
            fake_stat = SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=self.disk.number)
            with patch('disk_backend.has_holders', self.no_holders), patch(
                    'disk_backend.os.fstat', side_effect=lambda value: fake_stat if value == fd else real_fstat(value)):
                self.assertEqual(client.verify_image(self.disk, image, lambda _: None, lambda: False), 'match')
            self.assertEqual(block.OpenDevice.call_args.args[0], 'r')
            self.assertTrue(block.OpenDevice.call_args.args[1]['flags'] & os.O_EXCL)
            with self.assertRaises(OSError):
                real_fstat(fd)
            self.objects[USB][DRIVE]['Serial'] = 'replacement'
            with patch('disk_backend.has_holders', self.no_holders):
                with self.assertRaisesRegex(ValueError, 'removable'):
                    client.verify_image(self.disk, image, lambda _: None, lambda: False)
            self.assertEqual(block.OpenDevice.call_count, 1)

    def test_safe_remove_fails_closed_for_system_or_sibling_devices(self):
        self.objects[USB][DRIVE].update(CanPowerOff=True, SiblingId='physical-usb')
        self.objects[VOLUME][FS]['MountPoints'] = [b'/media/user/disk\0']
        target, mounted = removal_target(self.objects, self.disk, self.no_holders)
        self.assertEqual(target.identity, self.disk.identity)
        self.assertEqual(mounted, [VOLUME])
        self.objects[VOLUME][FS]['MountPoints'] = [b'/\0']
        with self.assertRaisesRegex(ValueError, 'system volume'):
            removal_target(self.objects, self.disk, self.no_holders)
        self.objects[VOLUME][FS]['MountPoints'] = []
        self.objects['/sibling'] = {DRIVE: {'SiblingId': 'physical-usb'}}
        with self.assertRaisesRegex(ValueError, 'shares a physical'):
            removal_target(self.objects, self.disk, self.no_holders)

    def test_safe_remove_never_powers_off_a_volume_reopened_during_unmount(self):
        from unittest.mock import Mock, patch
        self.objects[USB][DRIVE]['CanPowerOff'] = True
        self.objects[VOLUME][FS]['MountPoints'] = [b'/media/user/disk\0']
        client = object.__new__(UDisks)
        client.dbus = Mock()
        client.objects = lambda: self.objects
        fs, drive = Mock(), Mock()
        client.interface = lambda path, iface: fs if iface == FS else drive
        with patch('disk_backend.has_holders', self.no_holders):
            with self.assertRaisesRegex(ValueError, 'still mounted'):
                client.safe_remove(self.disk)
            drive.PowerOff.assert_not_called()
            fs.Unmount.side_effect = lambda *_args, **_kwargs: self.objects[VOLUME][FS].update(MountPoints=[])
            client.safe_remove(self.disk)
            drive.PowerOff.assert_called_once()

    def test_safe_remove_reports_partial_result_and_refreshes_even_without_hotplug(self):
        from unittest.mock import Mock, patch
        from mellipi_disks import Job
        self.objects[USB][DRIVE]['CanPowerOff'] = True
        self.objects[VOLUME][FS]['MountPoints'] = [b'/media/first\0']
        extra = self.objects['/second'] = {
            BLOCK: dict(self.objects[VOLUME][BLOCK], Device=b'/dev/sdz2\0', DeviceNumber=1236),
            FS: {'MountPoints': [b'/media/second\0']},
            PART: {'Number': 2},
        }
        client = object.__new__(UDisks)
        client.dbus, client.bus = Mock(), Mock()
        client.objects = lambda: self.objects
        first, second, drive = Mock(), Mock(), Mock()
        first.Unmount.side_effect = lambda *_args, **_kwargs: self.objects[VOLUME][FS].update(MountPoints=[])
        second.Unmount.side_effect = RuntimeError('Second volume is busy')
        client.interface = lambda path, iface: {VOLUME: first, '/second': second, USB: drive}[path]
        job = Job(None, 'remove', self.disk)
        with (patch('disk_backend.has_holders', self.no_holders),
              patch('mellipi_disks.UDisks', return_value=client)):
            job.run()
        self.assertIn('Unmounted 1 volume', job.error)
        self.assertIn('Second volume is busy', job.error)
        self.assertFalse(next(row for row in job.rows if row.path == VOLUME).mounts)
        self.assertTrue(extra[FS]['MountPoints'])
        drive.PowerOff.assert_not_called()

    def test_close_during_refresh_does_not_wait_on_application_thread(self):
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        from unittest.mock import Mock, patch
        from mellipi_disks import Disks
        app = QApplication.instance() or QApplication([])
        with patch.object(Disks, 'refresh'):
            window = Disks()
        window.show()
        job = window.job = Mock(kind='list')
        self.assertFalse(window.close())
        self.assertFalse(window.isVisible())
        job.wait.assert_not_called()
        window.done()
        QTest.qWait(1)
        self.assertIsNone(window.job)

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
