"""Removable-media operations through UDisks and its normal polkit policy."""

from dataclasses import dataclass
import os
from pathlib import Path
import stat

SERVICE = 'org.freedesktop.UDisks2'
ROOT = '/org/freedesktop/UDisks2'
BLOCK = SERVICE + '.Block'
DRIVE = SERVICE + '.Drive'
ATA = DRIVE + '.Ata'
NVME = SERVICE + '.NVMe.Controller'
FS = SERVICE + '.Filesystem'
PART = SERVICE + '.Partition'
TABLE = SERVICE + '.PartitionTable'
SWAP = SERVICE + '.Swapspace'
MGR = 'org.freedesktop.DBus.ObjectManager'
CHUNK = 1024 * 1024


def path_text(value):
    return os.fsdecode(bytes(value).rstrip(b'\x00'))


@dataclass(frozen=True)
class DriveHealth:
    status: str
    updated: int = 0
    temperature_c: float | None = None
    power_hours: int | None = None
    bad_sectors: int | None = None
    warnings: tuple = ()


def cached_health(interfaces):
    """Use properties already delivered by GetManagedObjects; do not wake drives."""
    nvme = NVME in interfaces
    smart = interfaces.get(NVME if nvme else ATA, {})
    if not nvme and not smart.get('SmartSupported'):
        return DriveHealth('Unavailable')
    if not nvme and not smart.get('SmartEnabled'):
        return DriveHealth('Disabled on this drive')
    updated = int(smart.get('SmartUpdated', 0))
    if not 0 < updated <= 253402300799:
        return DriveHealth('No cached reading yet')
    if nvme:
        labels = {
            'spare': 'Low spare capacity',
            'temperature': 'Temperature outside safe range',
            'degraded': 'Reduced reliability',
            'readonly': 'Media is read-only',
            'volatile_mem': 'Volatile memory backup failed',
            'pmr_readonly': 'Persistent memory is read-only or unreliable',
        }
        warnings = tuple(dict.fromkeys(labels.get(str(value), 'Other controller warning')
                                       for value in smart.get('SmartCriticalWarning', ())))
        assessed = 'SmartCriticalWarning' in smart
        power_hours = int(smart.get('SmartPowerOnHours', 0)) or None
        bad_sectors = None
    else:
        warnings = ('Drive reports a failure warning',) if smart.get('SmartFailing') else ()
        assessed = 'SmartFailing' in smart
        seconds = int(smart.get('SmartPowerOnSeconds', 0))
        power_hours = seconds // 3600 if seconds else None
        bad_sectors = int(smart.get('SmartNumBadSectors', -1))
        if bad_sectors < 0:
            bad_sectors = None
        if smart.get('SmartNumAttributesFailing', 0) > 0:
            warnings += ('One or more SMART attributes are failing',)
        if bad_sectors:
            warnings += ('Bad sectors reported',)
    status = 'Warning reported' if warnings else 'No warnings reported' if assessed else 'Assessment unavailable'
    kelvin = float(smart.get('SmartTemperature', 0))
    return DriveHealth(status, updated, kelvin - 273.15 if 0 < kelvin < 1000 else None,
                       power_hours, bad_sectors, warnings)


@dataclass(frozen=True)
class Device:
    path: str
    drive: str
    node: str
    name: str
    number: int
    size: int
    serial: str
    filesystem: str
    mounts: tuple
    writable_usb: bool
    partition: bool
    partitioned: bool
    system: bool
    connection: str = ''
    model: str = ''
    firmware: str = ''
    read_only: bool = False
    health: DriveHealth = DriveHealth('Unavailable')

    @property
    def identity(self):
        return self.path, self.drive, self.node, self.number, self.serial, self.size


def catalog(objects):
    devices = []
    health_by_drive = {}
    for path, properties in sorted(objects.items()):
        block = properties.get(BLOCK)
        if block is None or block.get('HintIgnore'):
            continue
        drive_path = str(block.get('Drive', '/'))
        interfaces = objects.get(drive_path, {})
        drive = interfaces.get(DRIVE, {})
        if not drive:
            continue
        node = path_text(block.get('Device', b''))
        if not node.startswith('/dev/') or not block.get('Size'):
            continue
        name = ' '.join(filter(None, (str(drive.get('Vendor', '')).strip(),
                                      str(drive.get('Model', '')).strip()))) or node
        is_partition = PART in properties
        if is_partition:
            name = str(block.get('IdLabel', '')).strip() or f'{name} · Partition {properties[PART].get("Number", "?")}'
        serial = str(drive.get('Serial', '') or drive.get('Id', ''))
        writable_usb = (
            drive.get('ConnectionBus') == 'usb'
            and bool(drive.get('Removable') or drive.get('MediaRemovable'))
            and bool(drive.get('MediaAvailable'))
            and not drive.get('Optical')
            and not block.get('HintSystem')
            and not block.get('ReadOnly')
            and block.get('CryptoBackingDevice', '/') == '/'
            and bool(serial)
        )
        if drive_path not in health_by_drive:
            health_by_drive[drive_path] = cached_health(interfaces)
        devices.append(Device(str(path), drive_path, node, name, int(block.get('DeviceNumber', 0)),
                             int(block['Size']), serial,
                             str(block.get('IdType', '')), tuple(path_text(p) for p in properties.get(FS, {}).get('MountPoints', ())),
                             writable_usb, is_partition, TABLE in properties, bool(block.get('HintSystem')),
                             'NVMe' if NVME in interfaces else str(drive.get('ConnectionBus', '')).upper(),
                             str(drive.get('Model', '')).strip(), str(drive.get('Revision', '')).strip(),
                             bool(block.get('ReadOnly')), health_by_drive[drive_path]))
    return devices


def allowed_target(objects, selected, operation, holders):
    """Require a currently present, unused USB device and recheck its family."""
    devices = catalog(objects)
    target = next((d for d in devices if d.identity == selected.identity), None)
    if not target or not target.writable_usb:
        raise ValueError('Select a removable, writable USB device.')
    family = [(path, row) for path, row in objects.items()
              if row.get(BLOCK, {}).get('Drive') == target.drive]
    if not family or not target.number or any(
        row[BLOCK].get('HintSystem') or row[BLOCK].get('ReadOnly')
        or row.get(FS, {}).get('MountPoints') or row.get(SWAP, {}).get('Active')
        or holders(int(row[BLOCK].get('DeviceNumber', 0)))
        for _, row in family
    ):
        raise ValueError('A volume on this USB device is in use. Unmount it before continuing.')
    if operation == 'image' and target.partition:
        raise ValueError('Choose a whole USB device to write an image.')
    if operation == 'format' and not target.partition and (
            target.partitioned or any(PART in row for _, row in family)):
        raise ValueError('Select the USB partition you want to format.')
    return target


def has_holders(number):
    if not number:
        return True
    directory = Path(f'/sys/dev/block/{os.major(number)}:{os.minor(number)}/holders')
    try:
        return next(directory.iterdir(), None) is not None
    except OSError:
        return True


def _image_size(descriptor):
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_size < 512:
        raise ValueError('Choose a nonempty regular disk image.')
    return info


class UDisks:
    def __init__(self):
        import dbus
        self.dbus = dbus
        self.bus = dbus.SystemBus(private=True)

    def close(self):
        self.bus.close()

    def interface(self, path, interface):
        return self.dbus.Interface(self.bus.get_object(SERVICE, path, introspect=False), interface)

    def objects(self):
        return self.interface(ROOT, MGR).GetManagedObjects(timeout=8)

    def list(self):
        return catalog(self.objects())

    def mount(self, selected, unmount=False):
        current = next((d for d in self.list() if d.identity == selected.identity), None)
        if not current:
            raise ValueError('The selected drive was disconnected.')
        if unmount and (current.system or any(path in ('/', '/boot', '/boot/efi')
                                             for path in current.mounts)):
            raise ValueError('Disks does not unmount system volumes.')
        options = self.dbus.Dictionary({}, signature='sv')
        fs = self.interface(current.path, FS)
        if unmount:
            fs.Unmount(options, timeout=90)
        else:
            return str(fs.Mount(options, timeout=90))

    def format(self, selected):
        target = allowed_target(self.objects(), selected, 'format', has_holders)
        options = self.dbus.Dictionary({}, signature='sv')
        self.interface(target.path, BLOCK).Format('vfat', options, timeout=300)

    def image(self, selected, source, progress):
        source_fd = os.open(source, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = _image_size(source_fd)
            target = allowed_target(self.objects(), selected, 'image', has_holders)
            if before.st_size > target.size:
                raise ValueError('The image is larger than this USB device.')
            options = self.dbus.Dictionary(
                {'flags': self.dbus.Int32(os.O_EXCL | os.O_SYNC | os.O_CLOEXEC)}, signature='sv')
            block = self.interface(target.path, BLOCK)
            target_fd = block.OpenDevice('w', options, timeout=90).take()
            try:
                info = os.fstat(target_fd)
                if not stat.S_ISBLK(info.st_mode) or info.st_rdev != target.number:
                    raise ValueError('The selected USB device changed before writing.')
                allowed_target(self.objects(), target, 'image', has_holders)
                written = 0
                last = -1
                while written < before.st_size:
                    data = os.read(source_fd, min(CHUNK, before.st_size - written))
                    if not data:
                        raise OSError('The disk image was cut short during writing.')
                    remaining = memoryview(data)
                    while remaining:
                        count = os.write(target_fd, remaining)
                        if count <= 0:
                            raise OSError('Could not finish writing the disk image.')
                        written += count
                        remaining = remaining[count:]
                    percent = written * 100 // before.st_size
                    if percent != last:
                        progress(min(99, percent))
                        last = percent
                os.fsync(target_fd)
                after = _image_size(source_fd)
                if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                        after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise OSError('The image changed while writing. Rewrite the USB with a stable image.')
            finally:
                os.close(target_fd)
            progress(100)
        finally:
            os.close(source_fd)
