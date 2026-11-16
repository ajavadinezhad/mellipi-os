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
