"""Mellipi Disks: inspect, mount, format and write removable drives."""
from datetime import datetime, timezone
import os
from pathlib import Path
import sys

os.environ['ORBIT_QT'] = '6'
os.environ['QT_WAYLAND_SHELL_INTEGRATION'] = 'xdg-shell'
os.environ.pop('QT_WAYLAND_DISABLE_WINDOWDECORATION', None)

from PyQt6.QtCore import Qt, QEvent, QSize, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QShortcut, QDesktopServices, QIcon, QKeySequence
from PyQt6.QtWidgets import (QApplication, QDialog, QGridLayout,
                             QHeaderView, QLabel, QProgressBar, QPushButton, QScrollArea,
                             QSizePolicy, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from file_chooser import FileChooser
from files_icons import icon
from disk_backend import UDisks
import icon_theme
from qt_app import BASE_STYLE, AppWindow, symbolic_icon, themed_prompt, widget_palette


class Job(QThread):
    progress = pyqtSignal(int)

    def __init__(self, parent, kind, device=None, image=None):
        super().__init__(parent)
        self.kind, self.device, self.image = kind, device, image
        self.rows, self.error = [], ''

    def run(self):
        try:
            disks = UDisks()
            try:
                if self.kind in ('mount', 'unmount'):
                    disks.mount(self.device, unmount=self.kind == 'unmount')
                if self.kind == 'format':
                    disks.format(self.device)
                if self.kind == 'image':
                    disks.image(self.device, self.image, self.progress.emit)
                self.rows = disks.list()
            finally:
                disks.close()
        except Exception as error:
            self.error = str(error)[:320] or 'The system disk service could not complete the operation.'


def size_label(value):
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if value < 1024 or unit == 'TiB':
            return f'{value:.0f} {unit}' if unit == 'B' else f'{value:.1f} {unit}'
        value /= 1024


def detail_groups(row):
    device = [
        ('Device', row.node),
        ('Size', size_label(row.size)),
        ('Format', row.filesystem or 'Not detected'),
        ('Access', 'Read-only' if row.read_only else 'Read/write'),
        ('Connection', row.connection),
        ('Drive model', row.model),
        ('Firmware', row.firmware),
        ('Mounted at', '\n'.join(row.mounts) if row.mounts else 'Not mounted'),
    ]
    health = row.health
    metrics = [('Status', health.status)]
    if health.warnings:
        metrics.append(('Warnings', '\n'.join(health.warnings)))
    if health.updated:
        stamp = datetime.fromtimestamp(health.updated, tz=timezone.utc)
        metrics.append(('Cached reading', f'{stamp:%Y-%m-%d %H:%M} UTC'))
    if health.temperature_c is not None:
        metrics.append(('Temperature', f'{health.temperature_c:.0f} °C'))
    if health.power_hours is not None:
        metrics.append(('Powered on', f'{health.power_hours:,} hours'))
    if health.bad_sectors is not None:
        metrics.append(('Bad sectors', f'{health.bad_sectors:,}'))
    return ('Device and volume', device), ('Drive health (SMART)', metrics)


class DriveDetails(QDialog):
    def __init__(self, owner, row):
        super().__init__(owner, Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle('Drive details')
        self.setAccessibleName('Drive details')
        self.setPalette(widget_palette(owner.theme))
        self.setStyleSheet((BASE_STYLE + """
            QDialog#driveDetails { border: 1px solid %(control_border)s; }
            QScrollArea, QWidget#driveDetailsBody { background: %(surface)s; border: 0; }
            QLabel#detailHeading { color: %(accent_ink)s; font-weight: 600; }
        """) % owner.theme)
        self.setObjectName('driveDetails')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        heading = self.label(row.name, 'detailHeading')
        layout.addWidget(heading)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setAccessibleName('Device and drive health information')
        body = QWidget()
        body.setObjectName('driveDetailsBody')
        groups = QVBoxLayout(body)
        groups.setContentsMargins(12, 8, 12, 8)
        groups.setSpacing(10)
        for section, fields in detail_groups(row):
            groups.addWidget(self.label(section, 'detailHeading'))
            grid = QGridLayout()
            grid.setColumnStretch(1, 1)
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(5)
            for index, (name, value) in enumerate((name, value) for name, value in fields if value):
                key = self.label(name, 'muted')
                key.setMaximumWidth(round(112 * owner.theme['text_scale']))
                field = self.label(str(value))
                field.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse |
                                              Qt.TextInteractionFlag.TextSelectableByKeyboard)
                field.setAccessibleName(name)
                grid.addWidget(key, index, 0, Qt.AlignmentFlag.AlignTop)
                grid.addWidget(field, index, 1, Qt.AlignmentFlag.AlignTop)
            groups.addLayout(grid)
        groups.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        close = QPushButton('Close')
        close.clicked.connect(self.accept)
        close.setDefault(True)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        close.setFocus()
        available = owner.screen().availableGeometry()
        self.resize(min(550, available.width() - 24), min(480, available.height() - 24))

    @staticmethod
    def label(text, style=''):
        result = QLabel(text)
        result.setObjectName(style)
        result.setTextFormat(Qt.TextFormat.PlainText)
        result.setWordWrap(True)
        result.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        if style == 'muted':
            result.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        return result


class Disks(AppWindow):
    extra_style = """
        QTreeWidget::item { padding: 4px 3px; }
        QTreeWidget::item:selected { background: %(selected_surface)s; color: %(text)s; }
        QTreeWidget:focus { border: 1px solid %(focus)s; }
        QPushButton[diskPrimary="true"]:enabled {
            background: %(selected_surface)s; color: %(accent_ink)s; font-weight: 600;
        }
        QPushButton[diskPrimary="true"]:enabled:hover { border-color: %(focus)s; }
    """

    def __init__(self, image=None):
        super().__init__('Disks')
        self.setWindowIcon(QIcon.fromTheme('mellipi-disks', QIcon.fromTheme('drive-harddisk')))
        self.resize(740, 490)
        self.setMinimumSize(510, 320)
        self.job = None
        self.image = image
        if self.image and self.image.startswith('file:'):
            url = QUrl(self.image)
            self.image = url.toLocalFile() if url.isLocalFile() and not url.host() else None
        self.devices = []
        self.refresh_button = self.button('view-refresh', 'Refresh', self.refresh, icon_only=True)
        self.header.addWidget(self.refresh_button)
        self.details_button = self.button('dialog-information', 'Details', self.show_details, icon_only=True)
        self.details_button.setToolTip('Drive details (Ctrl+I)')
        self.header.addWidget(self.details_button)

        self.volumes = QTreeWidget()
        self.volumes.setHeaderLabels(['Drive or volume', 'Size', 'Format', 'Device'])
        self.volumes.setAccessibleName('Drives and volumes')
        self.volumes.setAlternatingRowColors(True)
        self.volumes.setUniformRowHeights(True)
        self.volumes.setTextElideMode(Qt.TextElideMode.ElideRight)
        header = self.volumes.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 4):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
        self.volumes.viewport().installEventFilter(self)
        self.volumes.currentItemChanged.connect(self.update_controls)
        self.themeChanged.connect(self.apply_device_appearance)
        self.content.addWidget(self.volumes, 1)
        self.hint = QLabel()
        self.hint.setTextFormat(Qt.TextFormat.PlainText)
        self.hint.setWordWrap(True)
        self.hint.setObjectName('muted')
        self.content.addWidget(self.hint)

        self.actions = QGridLayout()
        self.actions.setSpacing(8)
        self.open_button = self.button('folder-open', 'Open mounted volume', self.open_volume, icon_only=True)
        self.mount_button = self.button('media-eject', 'Mount', self.mount_volume)
        self.format_button = self.button('edit-clear', 'Format…', self.format_volume)
        self.image_button = self.button('media-optical', 'Write Image…', self.write_image)
        self.action_buttons = (self.open_button, self.mount_button, self.format_button, self.image_button)
        self._stacked_actions = None
        self.content.addLayout(self.actions)
        self.progress = QProgressBar()
        self.progress.hide()
        self.content.addWidget(self.progress)
        QShortcut(QKeySequence.StandardKey.Refresh, self).activated.connect(self.refresh)
        QShortcut(QKeySequence('Ctrl+I'), self).activated.connect(self.show_details)
        self.update_controls()  # Parents the volume actions before resolving their icons.
        self.refresh_icons()
        self.apply_device_appearance()
        self.refresh()

    def apply_device_appearance(self):
        size = round(16 * self.theme['text_scale'])
        self.volumes.setIconSize(QSize(size + 2, size + 2))
        for button in (*self.action_buttons, self.details_button, self.refresh_button):
            button.setIconSize(QSize(size, size))
        self.repaint_device_icons()
        self.reflow()

    def reflow(self):
        if not hasattr(self, 'action_buttons'):
            return
        metric = self.volumes.fontMetrics()
        # Keep name, size and format readable; device paths remain available
        # through tooltips and Details when there is no room for a fourth column.
        show_device = self.volumes.viewport().width() >= max(570, 32 * metric.averageCharWidth() + 250)
        if self.volumes.isColumnHidden(3) == show_device:
            self.volumes.setColumnHidden(3, not show_device)
        for col, sample in ((1, '999.9 GiB'), (2, 'Filesystem'), (3, '/dev/nvme0n1p1')):
            if not self.volumes.isColumnHidden(col):
                size = metric.horizontalAdvance(sample) + 18
                if self.volumes.columnWidth(col) != size:
                    self.volumes.setColumnWidth(col, size)
        stack = self.width() < sum(button.sizeHint().width() for button in self.action_buttons) + 48
        if stack == self._stacked_actions:
            return
        self._stacked_actions = stack
        for button in self.action_buttons:
            self.actions.removeWidget(button)
        for col in range(4):
            self.actions.setColumnStretch(col, 1 if col < (2 if stack else 4) else 0)
        for index, button in enumerate(self.action_buttons):
            row, col = divmod(index, 2) if stack else (0, index)
            self.actions.addWidget(button, row, col)

    def eventFilter(self, target, event):
        if target is self.volumes.viewport() and event.type() == QEvent.Type.Resize:
            self.reflow()
        return super().eventFilter(target, event)

    def repaint_device_icons(self):
        from PyQt6.QtWidgets import QTreeWidgetItemIterator
        cursor = QTreeWidgetItemIterator(self.volumes)
        while cursor.value():
            item = cursor.value()
            row = self.devices[item.data(0, Qt.ItemDataRole.UserRole)]
            tint = '#e7ad76' if row.writable_usb else '#87abdf'
            item.setIcon(0, icon('duotone', 'hard-drives', self.theme['text'], tint,
                                 self.theme['text']))
            cursor += 1

    def button(self, icon, text, action, *, icon_only=False):
        button = QPushButton('' if icon_only else text)
        if icon_only:
            button.setAccessibleName(text)
            button.setToolTip(text)
            button.setMinimumSize(32, 32)
        button.setProperty('mellipiSymbolicIcon', icon)
        button.clicked.connect(action)
        return button

    def current(self):
        item = self.volumes.currentItem()
        index = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        return self.devices[index] if isinstance(index, int) and 0 <= index < len(self.devices) else None

    def update_controls(self, *_):
        row = self.current()
        ready = self.job is None
        self.refresh_button.setEnabled(ready)
        self.details_button.setEnabled(bool(ready and row))
        self.open_button.setEnabled(bool(ready and row and row.mounts))
        self.mount_button.setEnabled(bool(ready and row and row.filesystem and row.filesystem != 'swap'
                                          and not (row.mounts and row.system)))
        mounted = bool(row and row.mounts)
        self.mount_button.setText('Unmount' if mounted else 'Mount')
        for button, primary in ((self.open_button, mounted), (self.mount_button, not mounted)):
            if button.property('diskPrimary') != primary:
                button.setProperty('diskPrimary', primary)
                button.style().unpolish(button)
                button.style().polish(button)
        self.reflow()
        self.format_button.setEnabled(bool(ready and row and row.writable_usb
                                           and (row.partition or not row.partitioned)))
        self.image_button.setEnabled(bool(ready and row and row.writable_usb and not row.partition))
        if ready and row:
            self.hint.setText(', '.join(row.mounts) if row.mounts else 'Not mounted')
        elif ready:
            self.hint.setText(f'Select a USB drive for “{Path(self.image).name}”.' if self.image else
                              'Connect a drive, then select a volume.')

    def refresh(self):
        self.start('list')

    def show_details(self):
        row = self.current()
        if row and self.job is None:
            DriveDetails(self, row).exec()

    def open_volume(self):
        row = self.current()
        if row and row.mounts:
            QDesktopServices.openUrl(QUrl.fromLocalFile(row.mounts[0]))

    def mount_volume(self):
        row = self.current()
        if row:
            self.start('unmount' if row.mounts else 'mount', row)

    def confirm(self, row, title, message):
        return themed_prompt(
            self, title, f'{message}\n\n{row.name}\n{row.node} · {size_label(row.size)}'
            '\n\nAll data on the selected target will be erased.', title, 'Cancel')

    def format_volume(self):
        row = self.current()
        if row and self.confirm(row, 'Format as FAT', 'Format this USB volume?'):
            self.start('format', row)

    def write_image(self):
        row = self.current()
        if not row:
            return
        path = self.image or FileChooser.getOpenFileName(
            self, 'Select a disk image', '', 'Disk images (*.iso *.img);;All files (*)')[0]
        if path and self.confirm(row, 'Write Image', f'Write “{Path(path).name}” to this USB drive?'):
            self.start('image', row, path)
            self.image = None

    def start(self, kind, device=None, image=None):
        if self.job is not None:
            return
        self.job = Job(self, kind, device, image)
        self.job.finished.connect(self.done)
        self.job.progress.connect(self.progress.setValue)
        self.update_controls()
        self.hint.setText({'list': 'Looking for drives…', 'format': 'Formatting…',
                           'image': 'Writing image…', 'mount': 'Mounting…',
                           'unmount': 'Unmounting…'}[kind])
        self.progress.setRange(0, 100 if kind == 'image' else 0)
        if kind == 'image':
            self.progress.setValue(0)
        self.progress.show()
        self.job.start()

    def done(self):
        job, self.job = self.job, None
        previous = self.current()
        self.progress.hide()
        if job.error:
            self.update_controls()
            self.hint.setText(job.error)
        else:
            self.populate(job.rows, previous)
            if job.kind in ('format', 'image'):
                self.hint.setText('Image written. Your USB is ready.' if job.kind == 'image'
                                  else 'Volume formatted.')
        job.deleteLater()

    def populate(self, devices, previous):
        self.volumes.clear()
        self.devices = devices
        whole = {}
        target = None
        for index in sorted(range(len(devices)), key=lambda n: devices[n].partition):
            row = devices[index]
            item = QTreeWidgetItem([row.name, size_label(row.size), row.filesystem or '—', row.node])
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            for col in range(4):
                item.setToolTip(col, item.text(col))
            item.setToolTip(0, f'{row.name}\n{row.node}')
            if row.partition and row.drive in whole:
                whole[row.drive].addChild(item)
            else:
                self.volumes.addTopLevelItem(item)
                if not row.partition:
                    whole[row.drive] = item
            if previous and previous.identity == row.identity:
                target = item
        self.volumes.expandAll()
        self.reflow()
        self.volumes.setCurrentItem(target or (None if self.image else self.volumes.topLevelItem(0)))
        if self.image and target is None:
            self.volumes.clearSelection()
        self.repaint_device_icons()
        self.update_controls()

    def closeEvent(self, event):
        if self.job and self.job.kind != 'list':
            self.hint.setText('Wait for the drive operation to finish before closing.')
            event.ignore()
            return
        if self.job:
            self.job.wait(9000)
            if self.job.isRunning():
                event.ignore()
                return
        super().closeEvent(event)


def main():
    args = sys.argv[1:]
    app = QApplication([sys.argv[0]])
    app.setApplicationName('Disks')
    app.setOrganizationName('Mellipi')
    app.setDesktopFileName('mellipi-disks')
    icon_theme.configure()
    window = Disks(args[0] if args else None)
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
