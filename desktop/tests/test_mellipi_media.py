from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtWidgets import QApplication

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
