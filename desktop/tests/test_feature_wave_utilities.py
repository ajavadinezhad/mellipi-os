from datetime import date, datetime, time, timezone
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from disk_backend import compare_image_prefix
from mellipi_alarm_queue import fire, is_countdown, queue_alarm, read_queue, restore, write_queue
from mellipi_calendar import Event, EventStore, occurrences
from mellipi_monitor import Process, process_parents
from software_sources import Package, apt_preview


class FeatureWaveUtilities(unittest.TestCase):
    def test_calendar_reopens_monthly_and_leap_day_series(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'events.json'
            store = EventStore(path)
            bill = store.save_personal('Bill', '', date(2024, 1, 31), time(8), time(9), repeat='FREQ=MONTHLY')
            birthday = store.save_personal('Birthday', '', date(2024, 2, 29), repeat='FREQ=YEARLY')
            store = EventStore(path)
            self.assertFalse(store.error)
            instances = list(occurrences(store.records[bill.key], date(2024, 2, 1), date(2024, 4, 30)))
            self.assertEqual([row.start for row in instances], ['2024-03-31T08:00:00'])
            self.assertEqual(instances[0].reminder_stamp(), int(datetime(2024, 3, 31, 7, 55).timestamp()))
            birthdays = list(occurrences(store.records[birthday.key], date(2025, 1, 1), date(2028, 12, 31)))
            self.assertEqual([row.start for row in birthdays], ['2028-02-29'])

    def test_calendar_zoned_reminder_uses_absolute_time(self):
        event = Event('key', 'Fall back', '', '2027-11-07T06:30:00+00:00', '2027-11-07T07:00:00+00:00', False)
        self.assertEqual(event.reminder_stamp(), int(datetime(2027, 11, 7, 6, 25, tzinfo=timezone.utc).timestamp()))

    def test_countdown_restores_once_and_remains_separate_from_other_alarms(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'alarms.json'
            commands = []
            run = lambda arguments: not commands.append(arguments)
            alarm = queue_alarm(path, 1020, now=lambda: 1000, run=run)
            timer = queue_alarm(path, 1010, countdown=True, now=lambda: 1000, run=run)
            self.assertTrue(is_countdown(read_queue(path)[timer]))
            with self.assertRaisesRegex(ValueError, 'already running'):
                queue_alarm(path, 1011, countdown=True, now=lambda: 1000, run=run)
            restore(path, now=lambda: 1011, run=run, login=True)
            self.assertTrue(any('--on-active=8s' in command for command in commands))
            self.assertTrue(fire(path, timer, now=lambda: 1011, run=run))
            self.assertEqual(commands[-1][-1], 'Timer finished')
            self.assertFalse(fire(path, timer, now=lambda: 1011, run=run))
            self.assertEqual(read_queue(path), {alarm: 1020})

    def test_clock_page_restores_countdown_and_cancels_only_the_selected_alarm(self):
        from PyQt6.QtWidgets import QApplication, QWidget
        from mellipi_clocks import ClockPage
        self.app = QApplication.instance() or QApplication([])
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'alarms.json'
            with patch('mellipi_alarm_queue.queue_path', return_value=path):
                page = ClockPage(parent)
            self.addCleanup(page.deleteLater)
            stamp = int(page.state.wall()) + 3600
            saved_alarm, saved_timer = 'a'*32, 'b'*32
            write_queue(path, {saved_alarm: stamp, saved_timer: {'time': stamp, 'kind': 'countdown'}})
            page.state.alarm_at = stamp + 600
            page._sync_alarms()
            self.assertEqual(page.saved_timer, (saved_timer, stamp))
            page.alarm_choices.setCurrentIndex(page.alarm_choices.findData(''))
            page._sync_alarms()
            self.assertEqual(page.alarm_choices.currentData(), '')
            with patch.object(page, '_alarm_action') as action:
                page._cancel_alarm()
                self.assertIsNone(page.state.alarm_at)
                self.assertEqual(page.alarm_choices.findData(''), -1)
                self.assertEqual(page.alarm_choices.findData(saved_alarm), 0)
                self.assertFalse(page.cancel_alarm.isEnabled())
                action.assert_not_called()
                page._cancel_timer()
                self.assertEqual(action.call_args.args[0], ['cancel', saved_timer])

    def test_compare_only_image_prefix_and_support_cancel(self):
        with TemporaryDirectory() as folder:
            source, target = Path(folder) / 'source', Path(folder) / 'target'
            source.write_bytes(b'image')
            target.write_bytes(b'image trailing data')
            with source.open('rb') as a, target.open('rb') as b:
                got = []
                self.assertEqual(compare_image_prefix(a.fileno(), b.fileno(), 5, got.append, lambda: False), 'match')
                self.assertEqual(got, [100])
                self.assertEqual(compare_image_prefix(a.fileno(), b.fileno(), 5, got.append, lambda: True), 'canceled')
                target.write_bytes(b'wrong trailing data')
                self.assertEqual(compare_image_prefix(a.fileno(), b.fileno(), 5, got.append, lambda: False), 'mismatch')

    def test_process_tree_tracks_reparent_and_pid_reuse(self):
        first = Process(100, 'first', 10, 0, 0, os.getuid())
        second = Process(101, 'second', 12, 0, 0, os.getuid())
        child = Process(102, 'child', 13, 0, 0, os.getuid(), 100)
        self.assertEqual(process_parents({row.key: row for row in (first, second, child)}), {child.key: first.key})
        child = Process(102, 'child', 13, 0, 0, os.getuid(), 101)
        replacement = Process(101, 'replacement', 20, 0, 0, os.getuid())
        self.assertEqual(process_parents({row.key: row for row in (first, second, child)}), {child.key: second.key})
        self.assertFalse(process_parents({row.key: row for row in (first, replacement, child)}))

    def test_process_tree_keeps_selected_child_when_reparented(self):
        from PyQt6.QtWidgets import QApplication
        from mellipi_monitor import Monitor
        self.app = QApplication.instance() or QApplication([])
        window = Monitor()
        self.addCleanup(window.close)
        self.addCleanup(window.deleteLater)
        first = Process(100, 'first', 10, 0, 0, os.getuid())
        second = Process(101, 'second', 12, 0, 0, os.getuid())
        child = Process(102, 'child', 13, 0, 0, os.getuid(), 100)
        def display(t, child):
            window.display((t, t*10, t*5, 1024, 512, {row.key: row for row in (first, second, child)}))
        window.tree_mode.setChecked(True)
        display(1, child)
        row = window.rows_by_process[child.key]
        self.assertIs(row.parent(), window.rows_by_process[first.key])
        window.tree.setCurrentItem(row)
        child = Process(102, 'child', 13, 0, 0, os.getuid(), 101)
        display(2, child)
        self.assertIs(row.parent(), window.rows_by_process[second.key])
        self.assertEqual(window.selected_process(), child)
        window.tree_mode.setChecked(False)
        self.assertIsNone(row.parent())
        self.assertEqual(window.selected_process(), child)

    def test_progressive_software_search_keeps_chosen_package(self):
        from PyQt6.QtWidgets import QApplication
        from mellipi_software import SoftwareWindow
        from software_sources import SourceResult
        self.app = QApplication.instance() or QApplication([])
        window = SoftwareWindow()
        self.addCleanup(window.close)
        self.addCleanup(window.deleteLater)
        first = Package('apt', 'editor-one', 'Editor One', '')
        second = Package('apt', 'editor-two', 'Editor Two', '')
        late = Package('flatpak', 'org.example.Editor', 'Editor Three', '', scope='user', remote='Fixture')
        window.term = 'editor'
        window.search_finished({'apt': SourceResult([first, second])}, '')
        window.list.setCurrentItem(window.list.topLevelItem(1))
        self.assertEqual(window.selected(), second)
        window.search_finished({'apt': SourceResult([first, second]), 'flatpak': SourceResult([late])}, '')
        self.assertEqual(window.selected(), second)

    def test_preview_lists_dependencies_without_privileges_and_refuses_removals(self):
        package = Package('apt', 'editor-one', 'Editor One', '')
        with patch('software_sources.run', return_value='Inst lib-extra (1 info)\nInst editor-one (2 info)\n') as run:
            rows = apt_preview((package,), 'install')
            self.assertEqual([(operation, name) for operation, name, _ in rows],
                             [('Install', 'lib-extra'), ('Install', 'editor-one')])
            self.assertEqual(run.call_args.args[0][:2], ['/usr/bin/apt-get', '--simulate'])
        with patch('software_sources.run', return_value='Inst editor-one (2 info)\nRemv other-app [1]\n'):
            with self.assertRaisesRegex(RuntimeError, 'remove other-app'):
                apt_preview((package,), 'install')
