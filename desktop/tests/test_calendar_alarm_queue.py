from pathlib import Path
from contextlib import ExitStack
from tempfile import TemporaryDirectory
import unittest

from mellipi_alarm_queue import cancel_alarm, fire, locked_queue, queue_alarm, read_queue, restore


class AlarmQueueTests(unittest.TestCase):
    def test_alarm_retries_a_busy_queue_and_temporary_notification_failure(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'alarms.json'
            key = queue_alarm(path, 1001, now=lambda: 1000, run=lambda _: True)
            attempts = []
            calls = []
            def notify(args):
                calls.append(args)
                return len(calls) == 2
            with ExitStack() as held:
                held.enter_context(locked_queue(path))
                def release_then_retry(delay):
                    attempts.append(delay)
                    held.close()
                self.assertTrue(fire(path, key, now=lambda: 1001, run=notify, wait=release_then_retry))
            self.assertEqual(attempts, [.2, .4])
            self.assertEqual(len(calls), 2)
            self.assertFalse(read_queue(path))
            self.assertFalse(fire(path, key, now=lambda: 1001, run=notify))
            self.assertEqual(len(calls), 2)

    def test_imported_title_is_plain_in_notification_and_persists(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'alarms.json'
            commands = []
            run = lambda args: not commands.append(args)
            key = queue_alarm(path, 1015, label='<b>Review</b>', now=lambda: 1000, run=run)
            self.assertEqual(read_queue(path)[key]['label'], '<b>Review</b>')
            self.assertTrue(fire(path, key, now=lambda: 1015, run=run))
            self.assertEqual(commands[-1][-2:], ['Event reminder', '&lt;b&gt;Review&lt;/b&gt;'])

    def test_alarm_delivered_once_even_after_restore(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'alarms.json'
            commands = []
            run = lambda args: not commands.append(args)
            key = queue_alarm(path, 1001, now=lambda: 1000, run=run)
            self.assertIn('--on-calendar=@1001', commands[0])
            self.assertEqual(read_queue(path), {key: 1001})
            restore(path, now=lambda: 2000, run=run, login=True)
            self.assertIn('--on-active=8s', commands[1])
            self.assertTrue(fire(path, key, now=lambda: 2000, run=run))
            self.assertEqual(commands[2][-1], 'Missed alarm')
            self.assertFalse(fire(path, key, now=lambda: 2000, run=run))
            self.assertEqual(len(commands), 3)

    def test_failed_schedule_rolls_back_and_cancel_blocks_late_timer(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'alarms.json'
            with self.assertRaisesRegex(OSError, 'schedule'):
                queue_alarm(path, 1001, now=lambda: 1000, run=lambda _: False)
            self.assertEqual(read_queue(path), {})
            key = queue_alarm(path, 1007, now=lambda: 1000, run=lambda _: True)
            self.assertTrue(cancel_alarm(path, key, run=lambda _: False))
            self.assertFalse(fire(path, key, now=lambda: 2000,
                                  run=lambda _: self.fail('Canceled alarm must not notify')))
