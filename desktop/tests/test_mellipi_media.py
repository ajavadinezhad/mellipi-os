from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from PyQt6.QtMultimedia import QMediaMetaData, QMediaPlayer
from PyQt6.QtWidgets import QApplication, QBoxLayout

from mellipi_media import Media


class RepeatTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        with patch('mellipi_media.PlayerBus', return_value=None):
            self.media = Media()
        self.addCleanup(self.media.deleteLater)
        self.addCleanup(self.media.close)
        self.media.queue = [Path('one.wav'), Path('two.wav')]
        self.media.index = 1
        self.media.path = self.media.queue[1]

    def test_reordering_duplicate_tracks_preserves_the_playing_occurrence(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        self.media.queue.append(self.media.queue[1])
        self.media.refresh_queue(1)
        with patch.object(self.media, 'load') as load:
            QTest.keyClick(self.media.queue_view,Qt.Key.Key_Down,Qt.KeyboardModifier.AltModifier)
            load.assert_not_called()
        self.assertEqual(self.media.index,2)
        self.assertNotIn('Current track',self.media.queue_view.item(1).text())
        self.assertIn('Current track',self.media.queue_view.item(2).text())

    def test_playlist_wraps_on_end_but_off_does_not(self):
        eos = QMediaPlayer.MediaStatus.EndOfMedia
        with patch.object(self.media, 'load') as load:
            self.media.media_status(eos)
            load.assert_not_called()
            self.media.repeat_actions['Playlist'].trigger()
            self.assertTrue(self.media.repeat_button.isChecked())
            self.media.media_status(eos)
            load.assert_called_once_with(0)
            self.media.index = 0
            self.assertTrue(self.media.can_previous())
            load.reset_mock()
            self.media.advance(-1)
            load.assert_called_once_with(1)

    def test_track_and_one_item_queue_use_native_looping(self):
        self.media.set_repeat('Track')
        self.assertEqual(self.media.player.loops(), QMediaPlayer.Loops.Infinite.value)
        self.assertFalse(self.media.can_next())
        self.media.set_repeat('Playlist')
        self.assertEqual(self.media.player.loops(), 1)
        self.media.queue.pop()
        self.media.index = 0
        self.media.sync_loops()
        self.assertFalse(self.media.can_next())
        self.assertEqual(self.media.player.loops(), QMediaPlayer.Loops.Infinite.value)
        self.media.set_repeat('None')
        self.assertFalse(self.media.repeat_button.isChecked())
        self.assertEqual(self.media.player.loops(), 1)

    def test_broken_track_exposes_retry_and_skip(self):
        self.media.index = 0
        self.media.path = self.media.queue[0]
        self.media.error(QMediaPlayer.Error.ResourceError)
        self.assertFalse(self.media.recovery.isHidden())
        self.assertFalse(self.media.skip_button.isHidden())
        with patch.object(self.media, 'load') as load:
            self.media.retry_button.click()
            self.media.skip_button.click()
            self.assertEqual([call.args[0] for call in load.call_args_list], [0, 1])

    def test_subtitle_menu_can_turn_captions_off(self):
        metadata = QMediaMetaData()
        metadata.insert(QMediaMetaData.Key.Title, 'English captions')
        with (patch.object(self.media.player, 'subtitleTracks', return_value=[metadata]),
              patch.object(self.media.player, 'activeSubtitleTrack', return_value=0),
              patch.object(self.media.player, 'setActiveSubtitleTrack') as pick):
            self.media.populate_tracks()
            menu = next(action.menu() for action in self.media.track_menu.actions()
                        if action.text() == 'Subtitles')
            self.assertIn('English captions', menu.actions()[1].text())
            self.assertTrue(menu.actions()[1].isChecked())
            menu.actions()[0].trigger()
            pick.assert_called_once_with(-1)

    def test_queue_moves_beside_stage_without_losing_selection(self):
        self.media.resize(940, 520)
        self.media.show()
        self.media.queue_toggle.click()
        self.app.processEvents()
        self.assertEqual(self.media.stage_layout.direction(), QBoxLayout.Direction.LeftToRight)
        self.assertEqual(self.media.queue_view.currentRow(), self.media.index)
        self.media.resize(450, 400)
        self.app.processEvents()
        self.assertEqual(self.media.stage_layout.direction(), QBoxLayout.Direction.TopToBottom)
        self.assertEqual(self.media.queue_view.currentRow(), self.media.index)
