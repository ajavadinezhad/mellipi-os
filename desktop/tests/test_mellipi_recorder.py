from pathlib import Path
import struct
import tempfile
import unittest
import wave
from unittest.mock import patch

from mellipi_recorder import Recording, level


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
