"""Exercise new copy-only exports without touching real media or package state."""
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
from types import SimpleNamespace
from unittest import TestCase, skipUnless
from unittest.mock import patch
import wave

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage

from file_transfers import identity
from mellipi_media import read_playlist, write_playlist
from mellipi_photos import export_pixels, save_copy
from mellipi_recorder import Recorder, trim_recording
from pdf_annotations import extract, execute, parse_pages, revision
from test_pdf_annotations import fixture


class CopyWorkflowTests(TestCase):
    def test_photo_export_strips_text_and_preserves_or_flattens_alpha(self):
        original = QImage(3, 3, QImage.Format.Format_ARGB32)
        original.fill(Qt.GlobalColor.transparent)
        original.setPixelColor(1, 1, QColor('red'))
        original.setText('Description', 'private')
        png = export_pixels(original, b'png')
        jpeg = export_pixels(original, b'jpeg')
        self.assertEqual(png.textKeys(), [])
        self.assertEqual(png.pixelColor(0, 0).alpha(), 0)
        self.assertEqual(jpeg.pixelColor(0, 0), QColor('white'))
        self.assertEqual(jpeg.pixelColor(1, 1), QColor('red'))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'photo.jpg'
            save_copy(path, jpeg, codec=b'jpeg', quality=83)
            self.assertTrue(path.read_bytes().startswith(b'\xff\xd8'))
            with self.assertRaises(ValueError):
                save_copy(path, jpeg, codec=b'jpeg')

    def test_playlist_round_trips_duplicate_order_and_rejects_nonlocal_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            first, second = base / '#first.wav', base / 'second.wav'
            for track in (first, second):
                track.touch()
            playlist = base / 'saved.m3u8'
            write_playlist(playlist, [first, second, first])
            self.assertEqual(read_playlist(playlist), ([first, second, first], 0))
            with self.assertRaises(ValueError):
                write_playlist(playlist, [second])
            with playlist.open('a') as stream:
                stream.write('https://example.invalid/media.wav\nmissing.wav\n')
            self.assertEqual(read_playlist(playlist), ([first, second, first], 2))

    def test_playlist_distinguishes_filename_characters_from_newlines(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            tracks = [base / 'one\u2028two.wav', base / 'three\vfour.wav']
            for track in tracks:
                track.touch()
            playlist = base / 'saved.m3u8'
            write_playlist(playlist, tracks)
            playlist.write_bytes(playlist.read_bytes().replace(b'\n', b'\r\n'))
            self.assertEqual(read_playlist(playlist), (tracks, 0))

    def test_wav_trim_copies_exact_frames_keeps_source_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = (Path(folder) / name for name in ('original.wav', 'trimmed.wav'))
            frames = struct.pack('<16h', *range(16))
            with wave.open(str(source), 'wb') as original:
                original.setparams((2, 2, 8000, 0, 'NONE', 'not compressed'))
                original.writeframes(frames)
            original = source.read_bytes()
            self.assertEqual(trim_recording(source, output, 1, 5, identity(source)), output)
            self.assertEqual(source.read_bytes(), original)
            with wave.open(str(output), 'rb') as trimmed:
                self.assertEqual(trimmed.getnframes(), 4)
                self.assertEqual(trimmed.readframes(4), frames[4:20])
            with self.assertRaises(ValueError):
                trim_recording(source, output, 1, 2, identity(source))

    def test_rename_declines_replaced_recording_after_dialog(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            original, replacement = base / 'original.wav', base / 'incoming.wav'
            original.write_bytes(b'original')
            replacement.write_bytes(b'intended to keep its original name')
            status = []
            ui = SimpleNamespace(selected_recording=lambda: original, recording=None,
                                 refresh_library=lambda: None,
                                 status=SimpleNamespace(setText=status.append))
            def dialog(*_args, **_kwargs):
                replacement.replace(original)
                return 'Renamed', True
            with patch('mellipi_recorder.ThemedInput.getText', side_effect=dialog):
                Recorder.rename_selected(ui)
            self.assertIn('changed', status[-1])
            self.assertEqual(original.read_bytes(), b'intended to keep its original name')
            self.assertFalse((base / 'Renamed.wav').exists())

    @skipUnless(shutil.which('pdfseparate') and shutil.which('pdfunite'), 'Poppler tools required')
    def test_pdf_extract_nonadjacent_rotated_pages_with_marks(self):
        with tempfile.TemporaryDirectory(prefix='mellipi-%-') as folder:
            base = Path(folder)
            parts = []
            for rotation in (0, 180, 90):
                page = base / f'input-{rotation}.pdf'
                page.write_bytes(fixture(rotation))
                parts.append(page)
            source, output = base / 'source.pdf', base / 'pages.pdf'
            subprocess.run(['pdfunite', *map(str, parts), str(source)], check=True)
            raw = source.read_bytes()
            pages = parse_pages('3, 1', 3)
            request = {'revision': revision(source), 'pages': pages,
                       'marks': [['note', 3, [.5, .5], 'Selected markup']]}
            self.assertTrue(extract(source, request, output))
            self.assertEqual(execute('notes', output, {'page': 1}), ['Selected markup'])
            self.assertEqual(execute('notes', output, {'page': 2}), [])
            self.assertEqual(source.read_bytes(), raw)
            with self.assertRaises(ValueError):
                extract(source, request, output)
            with self.assertRaises(ValueError):
                parse_pages('4', 3)
