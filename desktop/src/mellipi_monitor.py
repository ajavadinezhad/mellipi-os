"""Mellipi System Monitor, using Linux procfs and no persistent service."""
from dataclasses import dataclass
import os
from pathlib import Path
import signal
import sys
import time

os.environ['ORBIT_QT'] = '6'
os.environ['QT_WAYLAND_SHELL_INTEGRATION'] = 'xdg-shell'
os.environ.pop('QT_WAYLAND_DISABLE_WINDOWDECORATION', None)

from PyQt6.QtCore import Qt, QEvent, QThread, QTimer
from PyQt6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QHeaderView, QLabel,
                             QLineEdit, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

import icon_theme
from qt_app import AppWindow, themed_prompt


@dataclass(frozen=True)
class Process:
    pid: int
    name: str
    start: int
    ticks: int
    rss: int
    uid: int

    @property
    def key(self):
        return self.pid, self.start


def read_process(directory, page_size):
    raw = (directory / 'stat').read_text(encoding='utf-8', errors='replace')
    begin, end = raw.index('('), raw.rindex(')')
    fields = raw[end + 1:].split()
    return Process(int(directory.name), ' '.join(raw[begin + 1:end].split()),
                   int(fields[19]), int(fields[11]) + int(fields[12]),
                   max(0, int(fields[21])) * page_size, directory.stat().st_uid)


def read_sample(root=Path('/proc')):
    counters = [int(value) for value in (root / 'stat').read_text().splitlines()[0].split()[1:9]]
    memory = {}
    for line in (root / 'meminfo').read_text().splitlines():
        key, _, value = line.partition(':')
        if key in ('MemTotal', 'MemAvailable', 'MemFree'):
            memory[key] = int(value.split()[0]) * 1024
    processes = {}
    page_size = os.sysconf('SC_PAGE_SIZE')
    for child in root.iterdir():
        if not child.name.isascii() or not child.name.isdecimal():
            continue
        try:
            item = read_process(child, page_size)
            processes[item.key] = item
        except (OSError, ValueError, IndexError):
            continue  # Processes may exit or be hidden while procfs is read.
    return (time.monotonic(), sum(counters), counters[3] + counters[4],
            memory['MemTotal'], memory.get('MemAvailable', memory.get('MemFree', 0)),
            processes)


def terminate_process(process):
    """Signal an exact same-user process, never a replacement with a reused PID."""
    if process.pid <= 1 or process.pid == os.getpid() or process.uid != os.geteuid():
        raise PermissionError('You can only end your own processes.')
    fd = os.pidfd_open(process.pid)
    try:
        current = read_process(Path('/proc') / str(process.pid), os.sysconf('SC_PAGE_SIZE'))
        if current.key != process.key or current.uid != process.uid:
            raise ProcessLookupError('That process is no longer running.')
        signal.pidfd_send_signal(fd, signal.SIGTERM)
    finally:
        os.close(fd)


def size_label(value):
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if value < 1024 or unit == 'TiB':
            return f'{value:.1f} {unit}'
        value /= 1024


class SampleJob(QThread):
    result = None
    error = ''

    def run(self):
        try:
            self.result = read_sample()
        except (OSError, IndexError, KeyError, ValueError) as error:
            self.error = str(error)


class ProcessRow(QTreeWidgetItem):
    def __lt__(self, other):
        col = self.treeWidget().sortColumn()
        a = self.data(col, Qt.ItemDataRole.UserRole)
        b = other.data(col, Qt.ItemDataRole.UserRole)
        return a < b


class Monitor(AppWindow):
    extra_style = """
        QFrame#cpuMetric { background: %(selected_surface)s; border-radius: %(radius)dpx; }
        QFrame#memoryMetric { background: %(raised)s; border-radius: %(radius)dpx; }
        QLabel#metricName { color: %(muted)s; font-weight: 600; }
        QLabel#cpuValue { color: %(accent_ink)s; font-weight: 700; }
        QLabel#memoryValue { color: %(text)s; font-weight: 700; }
    """

    def __init__(self):
        super().__init__('System Monitor')
        self.resize(690, 520)
        self.previous = self.job = None
        self.timer = QTimer(self, interval=2000)
        self.timer.timeout.connect(self.sample)
        metrics = QHBoxLayout()
        metrics.setSpacing(8)
        cpu_card, self.cpu_value = self.metric_card('CPU', 'cpu')
        memory_card, self.memory_value = self.metric_card('Memory', 'memory')
        metrics.addWidget(cpu_card, 1)
        metrics.addWidget(memory_card, 1)
        self.content.addLayout(metrics)
        self.search = QLineEdit(placeholderText='Filter processes by name or PID')
        self.search.setAccessibleName('Filter processes')
        self.search.textChanged.connect(self.filter_rows)
        self.content.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Process', 'PID', 'CPU', 'Memory'])
        self.tree.headerItem().setToolTip(2, '100% equals one fully used CPU core.')
        self.tree.headerItem().setToolTip(3, 'Resident memory, including shared pages.')
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSortingEnabled(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setStretchLastSection(False)
        self.themeChanged.connect(self.update_columns)
        self.update_columns()
        self.tree.sortItems(2, Qt.SortOrder.DescendingOrder)
        self.tree.itemSelectionChanged.connect(self.update_action)
        self.content.addWidget(self.tree, 1)
        bottom = QHBoxLayout()
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, 1)
        self.end = QPushButton('End process…', enabled=False)
        self.end.clicked.connect(self.end_process)
        bottom.addWidget(self.end)
        self.content.addLayout(bottom)
        if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
            self.end.setVisible(False)

    @staticmethod
    def metric_card(label, kind):
        frame = QFrame()
        frame.setObjectName(kind + 'Metric')
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(3)
        name = QLabel(label)
        name.setObjectName('metricName')
        value = QLabel('Reading…')
        value.setObjectName(kind + 'Value')
        value.setWordWrap(True)
        value.setAccessibleName(label + ' usage')
        layout.addWidget(name)
        layout.addWidget(value)
        return frame, value

    def update_columns(self):
        header = self.tree.header()
        metrics = header.fontMetrics()
        for column, sample in ((1, '4194304'), (2, '1000.0%'), (3, '999.9 GiB')):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            header.resizeSection(column, metrics.horizontalAdvance(sample) + 24)
            self.tree.headerItem().setTextAlignment(column, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def eligible(self):
        return self.isVisible() and not self.isMinimized()

    def update_polling(self):
        if not hasattr(self, 'timer'):
            return
        if self.eligible():
            if not self.timer.isActive():
                self.timer.start()
                self.sample()
        else:
            self.timer.stop()
            self.previous = None

    def showEvent(self, event):
        super().showEvent(event)
        self.update_polling()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.timer.stop()
        self.previous = None

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self.update_polling()

    def sample(self):
        if not self.eligible() or self.job is not None:
            return
        self.job = SampleJob(self)
        self.job.finished.connect(self.receive)
        self.job.start()

    def receive(self):
        result, error = self.job.result, self.job.error
        self.job.deleteLater()
        self.job = None
        if not self.eligible():
            return
        if error:
            self.cpu_value.setText('Unavailable')
            self.memory_value.setText('Unavailable')
        elif result:
            self.display(result)

    def closeEvent(self, event):
        self.timer.stop()
        if self.job is not None:
            self.job.wait()
        super().closeEvent(event)

    def display(self, sample):
        now, total, idle, mem, available, processes = sample
        previous, self.previous = self.previous, sample
        aggregate = '—'
        if previous and total > previous[1]:
            load = 100 * (1 - (idle - previous[2]) / (total - previous[1]))
            aggregate = f'{max(0, min(100, load)):.0f}%'
        self.cpu_value.setText(aggregate)
        self.memory_value.setText(f'{size_label(max(0, mem - available))} / {size_label(mem)}')
        selected = self.selected_process()
        scroll = self.tree.verticalScrollBar().value()
        elapsed = (now - previous[0]) * os.sysconf('SC_CLK_TCK') if previous else 0
        self.tree.setUpdatesEnabled(False)
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        rows = []
        match = None
        for process in processes.values():
            old = previous[5].get(process.key) if previous else None
            cpu = max(0, 100 * (process.ticks - old.ticks) / elapsed) if old and elapsed > 0 else -1
            row = ProcessRow([process.name, str(process.pid), f'{cpu:.1f}%' if cpu >= 0 else '—',
                              size_label(process.rss)])
            for column in (1, 2, 3):
                row.setTextAlignment(column, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for col, value in enumerate((process.name.casefold(), process.pid, cpu, process.rss)):
                row.setData(col, Qt.ItemDataRole.UserRole, value)
            row.setData(0, Qt.ItemDataRole.UserRole + 1, process)
            rows.append(row)
            if selected and selected.key == process.key:
                match = row
        self.tree.addTopLevelItems(rows)
        self.tree.setSortingEnabled(True)
        self.filter_rows()
        if match and not match.isHidden():
            self.tree.setCurrentItem(match)
        self.tree.verticalScrollBar().setValue(scroll)
        self.tree.setUpdatesEnabled(True)
        self.update_action()

    def filter_rows(self):
        needle = self.search.text().strip().casefold()
        for index in range(self.tree.topLevelItemCount()):
            row = self.tree.topLevelItem(index)
            hidden = needle not in row.text(0).casefold() and needle not in row.text(1)
            row.setHidden(hidden)
            if hidden and row.isSelected():
                row.setSelected(False)

    def selected_process(self):
        rows = self.tree.selectedItems()
        return rows[0].data(0, Qt.ItemDataRole.UserRole + 1) if rows else None

    def update_action(self):
        item = self.selected_process()
        self.end.setEnabled(bool(item and item.uid == os.geteuid() and item.pid not in (0, 1, os.getpid())))

    def end_process(self):
        item = self.selected_process()
        if not item:
            return
        if themed_prompt(self, 'End process?', f'End {item.name} (PID {item.pid})? Unsaved work may be lost.',
                         'End process', 'Cancel'):
            try:
                terminate_process(item)
                self.status.setText(f'Asked {item.name} to exit.')
                self.sample()
            except (OSError, ValueError, IndexError) as error:
                self.status.setText(f'Could not end the process: {error}')


def main():
    app = QApplication([sys.argv[0]])
    app.setApplicationName('System Monitor')
    app.setOrganizationName('Mellipi')
    app.setDesktopFileName('mellipi-monitor')
    icon_theme.configure()
    window = Monitor()
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
