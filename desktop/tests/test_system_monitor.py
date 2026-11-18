"""Check process identity rather than the displayed name or a reused PID."""
from pathlib import Path
import os
import signal
import subprocess
import tempfile
import unittest

from mellipi_monitor import Process, UsageHistory, read_process, terminate_process


class SystemMonitorTests(unittest.TestCase):
    def test_history_can_show_a_usage_spike_but_expires_old_samples(self):
        history = UsageHistory()
        history.record(0, 5)
        history.record(2, 95)
        history.record(4, 10)
        line, = history.lines()
        self.assertEqual([point[1] for point in line], [.05, .95, .10])
        history.record(63, 50)
        self.assertEqual([len(line) for line in history.lines()], [1, 1])
        self.assertEqual(list(history.lines())[-1], [(1, .50)])
        history.record(65, 60)
        self.assertEqual([point[1] for point in next(history.lines())], [.50, .60])

    def test_failed_and_paused_samples_do_not_draw_continuous_history(self):
        history = UsageHistory()
        for timestamp, value in [(0, 1), (2, 15), (4, None), (6, 5), (20, 10), (22, 25)]:
            history.record(timestamp, value)
        self.assertEqual([[point[1] for point in line] for line in history.lines()],
                         [[.01, .15], [.05], [.10, .25]])

    def test_comm_with_closing_parenthesis_and_units(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / '123'
            directory.mkdir()
            values = ['0'] * 22
            values[0] = 'S'
            values[11:13] = ['3', '9']
            values[19] = '99'
            values[21] = '4'
            (directory / 'stat').write_text('123 (one) two) ' + ' '.join(values))
            process = read_process(directory, 4096)
            self.assertEqual(process, Process(123, 'one) two', 99, 12, 16384, os.geteuid()))

    def test_refresh_reuses_live_item_but_not_reused_pid(self):
        from PyQt6.QtWidgets import QApplication
        from mellipi_monitor import Monitor
        self.app = QApplication.instance() or QApplication([])
        monitor = Monitor()
        self.addCleanup(monitor.close)
        self.addCleanup(monitor.deleteLater)
        first = Process(999999, 'worker', 1, 10, 4096, os.geteuid())
        updated = Process(999999, 'worker', 1, 20, 8192, os.geteuid())
        reused = Process(999999, 'other', 2, 1, 4096, os.geteuid())
        monitor.display((1, 20, 10, 100, 50, {first.key: first}))
        row = monitor.rows_by_process[first.key]
        monitor.tree.setCurrentItem(row)
        monitor.display((3, 30, 13, 100, 50, {updated.key: updated}))
        self.assertIs(monitor.tree.currentItem(), row)
        self.assertEqual(monitor.selected_process(), updated)
        monitor.display((5, 40, 17, 100, 50, {reused.key: reused}))
        self.assertNotIn(first.key, monitor.rows_by_process)
        self.assertIsNot(monitor.rows_by_process[reused.key], row)
        self.assertIsNone(monitor.selected_process())

    def test_close_during_refresh_defers_without_waiting(self):
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        from unittest.mock import Mock, patch
        from mellipi_monitor import Monitor
        app = QApplication.instance() or QApplication([])
        with patch.object(Monitor, 'sample'):
            monitor = Monitor()
            monitor.show()
        job = monitor.job = Mock(result=None, error='')
        self.assertFalse(monitor.close())
        self.assertFalse(monitor.isVisible())
        job.wait.assert_not_called()
        monitor.receive()
        QTest.qWait(1)
        self.assertIsNone(monitor.job)

    @unittest.skipUnless(hasattr(os, 'pidfd_open') and hasattr(signal, 'pidfd_send_signal'), 'needs pidfd')
    def test_stale_identity_cannot_signal_disposable_process(self):
        with subprocess.Popen(['/bin/sleep', '10']) as child:
            try:
                process = read_process(Path('/proc') / str(child.pid), os.sysconf('SC_PAGE_SIZE'))
                stale = Process(process.pid, process.name, process.start + 1, process.ticks,
                                process.rss, process.uid)
                with self.assertRaises(ProcessLookupError):
                    terminate_process(stale)
                self.assertIsNone(child.poll())
                terminate_process(process)
                self.assertEqual(child.wait(timeout=3), -signal.SIGTERM)
            finally:
                if child.poll() is None:
                    child.kill()
