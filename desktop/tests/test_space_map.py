import tempfile
import threading
import unittest
from pathlib import Path

from arrangements import ArrangementEngine, checkpoint_preview, space_map


AREA = dict(x=-800, y=46, width=800, height=554)
RECT = dict(x=-600, y=46, width=400, height=277)


class SpaceMapTests(unittest.TestCase):
    def test_drop_does_not_move_a_window_that_left_its_source(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            engine = ArrangementEngine(Mock(lock=threading.RLock()), Path(directory) / 'layouts.json')
            engine.capture = Mock(return_value=[dict(id=7, desktop=3)])
            move = Mock()
            with self.assertRaisesRegex(ValueError, 'no longer in the original workspace'):
                engine.record_action('Move to workspace 2', move, [7], expected_desktop=1)
            move.assert_not_called()
            self.assertEqual(engine.history, [])

    def test_geometry_respects_each_output_and_includes_empty_spaces(self):
        windows = [dict(id='7', desktop=1, workarea=AREA, rect=RECT, title='Terminal'),
                   dict(id='8', desktop=1, workarea=AREA, rect=RECT, minimized=True),
                   dict(id='9', desktop=1, transient=True)]
        overview = space_map([dict(id=1, name='2'), dict(id=0, name='Work')], windows, 1)
        self.assertEqual([space['name'] for space in overview], ['Work', 'Space 2'])
        self.assertEqual(overview[0]['windows'], [])
        selected = overview[1]
        self.assertTrue(selected['active'])
        self.assertEqual(selected['count'], 2)
        self.assertEqual(selected['tiles'][0]['tile'], dict(x=.25, y=0, w=.5, h=.5))
        self.assertEqual([tile['id'] for tile in selected['tiles']], ['7'])
        self.assertTrue(selected['windows'][1]['minimized'])

    def test_checkpoint_matches_live_identity_and_omits_minimized_windows(self):
        entry = dict(id='test', label='Move', rows=[
            dict(id=7, key=(75, 'terminal', 0), desktop=1, rect=RECT, area=AREA),
            dict(id=8, key=(85, 'browser', 0), desktop=2, rect=RECT, area=AREA),
            dict(id=9, key=(95, 'files', 0), desktop=3, rect=RECT, area=AREA)])
        preview = checkpoint_preview(entry, [
            dict(id='7', pid=75, klass='Terminal', title='Editing'),
            dict(id='8', pid=100, klass='browser', title='Replacement'),
            dict(id='9', pid=95, klass='files', title='Minimized', minimized=True)])
        self.assertEqual(preview['available'], 1)
        self.assertEqual([row['name'] for row in preview['rows']], ['Editing', 'browser', 'files'])

    def test_restoring_old_checkpoint_inverts_without_consuming_other_entries(self):
        class MemoryActions:
            lock = threading.RLock()

        class Engine(ArrangementEngine):
            def capture(self, ids=None):
                return [dict(self.current)] if ids is None or self.current['id'] in ids else []
            def restore_rows(self, rows, undo=False):
                self.current = dict(rows[0])
                return dict(applied=1, skipped=0)

        with tempfile.TemporaryDirectory() as directory:
            engine = Engine(MemoryActions(), Path(directory) / 'layouts.json')
            engine.current = dict(id=7, desktop=1)
            engine.record_action('Move to 2', lambda:engine.current.update(desktop=2), [7])
            initial = engine.history[-1]['id']
            for space in (3, 4, 3):
                engine.record_action('Move again', lambda:engine.current.update(desktop=space), [7])
            self.assertEqual(engine.current['desktop'], 3)
            self.assertEqual(engine.restore_checkpoint(initial)['applied'], 1)
            self.assertEqual(engine.current['desktop'], 1)
            self.assertEqual(len(engine.history), 5)
            self.assertEqual(engine.undo()['applied'], 1)
            self.assertEqual(engine.current['desktop'], 3)
            self.assertEqual(len(engine.history), 4)
            self.assertFalse(engine.path.exists())
            for i in range(12):
                engine.record_action('Move', lambda:engine.current.update(desktop=1+i % 2), [7])
            self.assertEqual(len(engine.history), 10)
            with self.assertRaisesRegex(ValueError, 'no longer available'):
                engine.restore_checkpoint(initial)
