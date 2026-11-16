import unittest

from native_app import Bridge


class TaskbarWindowMenuTest(unittest.TestCase):
    def test_each_entry_targets_its_window_and_describes_where_it_is(self):
        group = dict(name='Files', windows=[
            dict(id='8', title='Downloads', desktop=0, active=True),
            dict(id='9', title='Projects', desktop=2, minimized=True),
        ])
        first, second = Bridge.taskbarWindowItems(group, True)
        self.assertEqual((first['label'],first['action'],first['value']), ('Downloads','focus','8'))
        self.assertEqual(first['detail'], 'Files · Workspace 1 · Active')
        self.assertEqual((second['label'],second['value']), ('Projects','9'))
        self.assertEqual(second['detail'], 'Files · Workspace 3 · Minimized')
