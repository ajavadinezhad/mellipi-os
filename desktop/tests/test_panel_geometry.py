"""Floating taskbar popovers stay on their logical output."""
import tempfile
import unittest
from pathlib import Path

from preferences import Preferences

from panel_policy import panel_body_origin, panel_mask_origin, taskbar_overlay_layout, workspace_drop_target


class TaskbarPopoverGeometryTest(unittest.TestCase):
    def setUp(self):
        # A secondary output to the left of the primary at a scaled logical size.
        self.screen = dict(x=-640, y=23, width=640, height=410)

    def test_short_bar_with_large_popup_clamps_only_parallel_to_bar(self):
        x, y = self.screen['x'], self.screen['y']
        bars = {
            'left': dict(x=x+8, y=y+180, width=52, height=50),
            'right': dict(x=x+580, y=y+180, width=52, height=50),
            'top': dict(x=x+295, y=y+8, width=50, height=52),
            'bottom': dict(x=x+295, y=y+350, width=50, height=52),
        }
        for edge, bar in bars.items():
            for panel in ('notifications', 'window-capture'):
                with self.subTest(edge=edge, panel=panel):
                    width, height = (556, 378) if edge in ('left','right') else (608, 334)
                    origin = panel_body_origin(panel,width,height,self.screen,edge,bar)
                    self.assertGreaterEqual(origin['x'],x)
                    self.assertGreaterEqual(origin['y'],y)
                    self.assertLessEqual(origin['x']+width,x+640)
                    self.assertLessEqual(origin['y']+height,y+410)
                    if edge=='left':
                        self.assertEqual(origin['x'],bar['x']+bar['width']+12)
                    elif edge=='right':
                        self.assertEqual(origin['x']+width,bar['x']-12)
                    elif edge=='top':
                        self.assertEqual(origin['y'],bar['y']+bar['height']+12)
                    else:
                        self.assertEqual(origin['y']+height,bar['y']-12)
                    mask = panel_mask_origin(760,620,width,height,panel,edge)
                    buffer = panel_body_origin(panel,760,620,self.screen,edge,bar,
                                               content_size=(width,height))
                    self.assertEqual(origin,dict(x=buffer['x']+mask['x'],y=buffer['y']+mask['y']))

    def test_qt_fractional_sizes_clamp_to_integer_layer_margins(self):
        bar = dict(x=-640,y=69,width=64,height=364)
        layout = taskbar_overlay_layout('',self.screen,'left',bar,(420.0,382.5))
        self.assertEqual(layout['margins'],(76,14,0,0))
        self.assertTrue(all(type(value) is int for value in layout['margins']))

    def test_roomy_panel_stays_aligned_and_launcher_center_unchanged(self):
        bar = dict(x=-632,y=31,width=624,height=52)
        params = ('notifications',self.screen,'top',bar)
        self.assertEqual(taskbar_overlay_layout(*params),
                         taskbar_overlay_layout(*params,(300,150)))
        self.assertEqual(panel_body_origin('launcher',400,300,self.screen,'top',bar),
                         dict(x=-520,y=78))


    def test_session_exit_centers_on_secondary_output_on_every_edge(self):
        for edge in ('left', 'right', 'top', 'bottom'):
            with self.subTest(edge=edge):
                self.assertEqual(panel_body_origin('session-exit',400,200,self.screen,edge),
                                 dict(x=-520,y=128))
                self.assertEqual(panel_mask_origin(600,400,400,200,'session-exit',edge),
                                 dict(x=100,y=100))


class TaskbarPreferenceMigrationTest(unittest.TestCase):
    def test_saved_top_taskbar_migrates_to_bottom(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "settings.json"
            settings.write_text('{"panelPosition":"top","taskbarFloating":true}')
            preferences = Preferences(settings)
            self.assertEqual(preferences.appearance()["panelPosition"], "bottom")
            self.assertTrue(preferences.appearance()["taskbarFloating"])


class WorkspaceDropTargetTest(unittest.TestCase):
    def test_clipped_spaces_and_gap_are_not_workspace_targets(self):
        targets = [dict(id=0,x=12,y=8,width=0,height=30),
                   dict(id=1,x=12,y=8,width=19,height=30),
                   dict(id=2,x=34,y=8,width=30,height=30)]
        self.assertEqual(workspace_drop_target(targets,12,15),1)
        self.assertEqual(workspace_drop_target(targets,34,15),2)
        self.assertIsNone(workspace_drop_target(targets,32,15))
        self.assertIsNone(workspace_drop_target(targets,39,46))
