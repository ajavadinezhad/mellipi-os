import os
from pathlib import Path
import struct
import tempfile
import unittest
import wave
from unittest.mock import patch

from PyQt6.QtCore import QUrl
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtWidgets import QApplication

from mellipi_recorder import Recorder, Recording, level, saved_recordings
from preferences import Preferences


class RecordingTest(unittest.TestCase):
    def test_chunk_boundaries_make_a_private_playable_wav(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'Recordings'
            record = Recording(root, 48000, 2)
            frame = struct.pack('=hh', -32768, 1024)
            self.assertEqual(record.append(frame[:3]), 0)
            self.assertEqual(record.append(frame[3:] + frame + b'x'), 100)
            self.assertEqual(record.frames, 2)
            self.assertFalse(record.path.exists())
            self.assertEqual(record.staging.stat().st_mode & 0o077, 0)
            path = record.finish()
            self.assertEqual(list(root.iterdir()), [path])
            with wave.open(str(path), 'rb') as wav:
                self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate(),
                                  wav.getnframes()), (2, 2, 48000, 2))
                self.assertEqual(wav.readframes(2), struct.pack('<hh', -32768, 1024) * 2)

    def test_never_publish_empty_or_discarded_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            empty = Recording(root, 44100, 1)
            self.assertIsNone(empty.finish())
            stopped = Recording(root, 44100, 1)
            stopped.append(struct.pack('=h', 16384))
            self.assertIsNone(stopped.finish(preserve=False))
            self.assertEqual(list(root.iterdir()), [])

    def test_peak_meter_is_normalized(self):
        self.assertEqual(level(b''), 0)
        self.assertEqual(level(struct.pack('=hh', 1024, -16384)), 50)
        self.assertEqual(level(struct.pack('=hh', 0, 32767)), 100)

    def test_wav_size_limit_discards_only_audio_past_a_complete_frame(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            'mellipi_recorder.RIFF_MAX_DATA_BYTES', 9
        ):
            record = Recording(Path(directory), 48000, 2)
            frame = struct.pack('=hh', 123, -456)
            record.append(frame + frame + frame[:3])
            self.assertTrue(record.at_limit)
            self.assertEqual(record.append(frame * 8), 0)
            with wave.open(str(record.finish()), 'rb') as wav:
                self.assertEqual(wav.getnframes(), 2)
                self.assertEqual(wav.readframes(8), struct.pack('<hh', 123, -456) * 2)


class RecordingLibraryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.older = self.make_wav('Older.wav')
        self.newer = self.make_wav('Newer.WAV')
        os.utime(self.older, (1000, 1000))
        os.utime(self.newer, (1001, 1001))
        # The library is independent of the host's sound server. Don't touch
        # audio hardware when exercising file management and source selection.
        devices = self.enterContext(patch('mellipi_recorder.QMediaDevices'))
        self.enterContext(patch('mellipi_recorder.QAudioOutput'))
        player = self.enterContext(patch('mellipi_recorder.QMediaPlayer'))
        devices.return_value.audioInputs.return_value = []
        player.PlaybackState = QMediaPlayer.PlaybackState
        self.window = Recorder(self.root)
        self.addCleanup(self.window.close)

    def make_wav(self, name):
        path = self.root / name
        with wave.open(str(path), 'wb') as output:
            output.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            output.writeframes(struct.pack('<h', 100) * 80)
        return path

    def test_library_filters_non_completed_files_and_tracks_selection(self):
        self.make_wav('.hidden.wav')
        (self.root / '.recording.part').touch()
        (self.root / 'directory.wav').mkdir()
        (self.root / 'link.wav').symlink_to(self.newer)
        self.assertEqual(saved_recordings(self.root), [self.newer, self.older])
        self.window.refresh_library()
        self.assertEqual(self.window.library.count(), 2)
        self.window.library.setCurrentRow(1)
        self.window.player.setSource.assert_called_with(QUrl.fromLocalFile(str(self.older)))
        self.window.refresh_library()
        self.assertEqual(self.window.selected_recording(), self.older)

    def test_rename_keeps_playback_selection_and_never_overwrites(self):
        self.window.library.setCurrentRow(0)
        with patch('mellipi_recorder.ThemedInput.getText', return_value=('Older', True)):
            self.window.rename_selected()
        self.assertTrue(self.newer.exists())
        self.assertTrue(self.older.exists())
        self.assertEqual(self.window.selected_recording(), self.newer)
        with patch('mellipi_recorder.ThemedInput.getText', return_value=('Interview', True)):
            self.window.rename_selected()
        destination = self.root / 'Interview.wav'
        self.assertFalse(self.newer.exists())
        self.assertTrue(destination.is_file())
        self.assertEqual(self.window.selected_recording(), destination)
        self.window.player.setSource.assert_called_with(QUrl.fromLocalFile(str(destination)))

    def test_refused_or_unavailable_trash_does_not_delete(self):
        self.window.library.setCurrentRow(0)
        with patch('mellipi_recorder.themed_prompt', return_value=False), patch('mellipi_recorder.QFile') as file:
            self.window.trash_selected()
            file.assert_not_called()
        with patch('mellipi_recorder.themed_prompt', return_value=True), patch('mellipi_recorder.QFile') as file:
            file.return_value.moveToTrash.return_value = False
            self.window.trash_selected()
        self.assertTrue(self.newer.exists())
        self.assertEqual(self.window.selected_recording(), self.newer)
        self.assertIn('Could not', self.window.status.text())

    def test_trash_refuses_a_replacement_while_confirmation_is_open(self):
        self.window.library.setCurrentRow(0)
        def replace(*args):
            replacement = self.root / 'replacement.wav'
            replacement.write_bytes(b'new file')
            replacement.replace(self.newer)
            return True
        with patch('mellipi_recorder.themed_prompt', side_effect=replace), patch('mellipi_recorder.QFile') as file:
            self.window.trash_selected()
            file.assert_not_called()
        self.assertEqual(self.newer.read_bytes(), b'new file')
        self.assertIn('changed', self.window.status.text())

    def test_library_actions_remain_accessible_above_list_at_large_text(self):
        preferences = Preferences(self.root / 'appearance.json')
        preferences.apply_theme('cobalt')
        preferences.update({'highContrast': True, 'textScale': 1.5, 'density': 'extra'})
        self.window.theme_watch.path = preferences.path
        self.window.theme_watch.reload()
        self.window.status.setText('Could not save recording. Check the name and folder permissions.')
        self.window.resize(430, 390)
        self.window.show()
        for _ in range(4):
            self.app.processEvents()
        self.assertGreater(self.window.status.height(), self.window.status.fontMetrics().height())
        self.assertLess(self.window.library_menu.geometry().bottom(), self.window.library.geometry().top())
        self.assertIn(self.window.rename_button, self.window.library_menu.menu().actions())
        self.assertIn(self.window.trash_button, self.window.library_menu.menu().actions())
        self.assertGreater(self.window.status.geometry().top(), self.window.library.geometry().bottom())
