"""Photo edits are reversible without writing to the original image."""
from unittest import TestCase
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from mellipi_photos import PhotosWindow


def photo(width, height, color):
    pix = QImage(width, height, QImage.Format.Format_RGB32)
    pix.fill(QColor(color))
    return pix


class PhotosHistoryTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = PhotosWindow()
        self.addCleanup(self.window.deleteLater)
        self.window.display(None, photo(20, 30, 'red'))

    def test_redo_restores_saved_revision_and_new_edit_discards_it(self):
        view = self.window
        view.rotate()
        view.saved_revision = view.revision
        self.assertEqual(view.canvas.image.width(), 30)
        view.undo()
        self.assertTrue(view.dirty)
        self.assertEqual(view.canvas.image.width(), 20)
        self.assertTrue(view.redo_btn.isEnabled())
        view.redo_btn.click()
        self.assertFalse(view.dirty)
        self.assertEqual(view.canvas.image.width(), 30)
        self.assertFalse(view.redo_btn.isEnabled())
        view.undo()
        view.commit(photo(10, 10, 'blue'))
        self.assertFalse(view.redo_btn.isEnabled())
        view.undo()
        view.display(None, photo(22, 24, 'green'))
        self.assertFalse(view.undo_btn.isEnabled())
        self.assertFalse(view.redo_btn.isEnabled())

    def test_undo_and_redo_share_memory_budget(self):
        view = self.window
        with patch('mellipi_photos.MAX_HISTORY_BYTES', 3000):
            for color in ('green', 'blue', 'red'):
                view.commit(photo(20, 30, color))
            self.assertEqual(len(view.history), 1)
            view.undo()
            self.assertFalse(view.undo_btn.isEnabled())
            self.assertTrue(view.redo_btn.isEnabled())
            view.redo()
            self.assertEqual(view.canvas.image.pixelColor(0, 0), QColor('red'))

    def test_leaving_dirty_image_honors_cancel_discard_and_save(self):
        self.window.rotate()
        with patch('mellipi_photos.themed_choice', return_value=0):
            self.assertFalse(self.window.confirm_leave())
        with patch('mellipi_photos.themed_choice', return_value=2):
            self.assertTrue(self.window.confirm_leave())
        with (patch('mellipi_photos.themed_choice', return_value=1),
              patch.object(self.window, 'save_as', return_value=False) as save):
            self.assertFalse(self.window.confirm_leave())
            save.assert_called_once()

    def test_save_copy_keeps_edits_dirty_for_jpeg_and_checkpoints_png(self):
        from PyQt6.QtGui import QImageWriter
        if b'jpeg' not in QImageWriter.supportedImageFormats():
            self.skipTest('Qt JPEG encoder is unavailable')
        self.window.rotate()
        with TemporaryDirectory() as tmp:
            jpeg, png = (Path(tmp) / name for name in ('copy.jpg', 'copy.png'))
            with (patch('mellipi_photos.FileChooser.getSaveFileName',
                        return_value=(str(jpeg), 'JPEG image (*.jpg *.jpeg)')),
                  patch('mellipi_photos.ThemedInput.getInt', return_value=(90, True))):
                self.window.save_btn.click()
            self.assertEqual(QImage(str(jpeg)).width(), 30)
            self.assertTrue(self.window.dirty)
            self.assertIn('Edits remain unsaved', self.window.status.text())
            with patch('mellipi_photos.FileChooser.getSaveFileName',
                       return_value=(str(png), 'PNG image (*.png)')):
                self.assertTrue(self.window.save_as())
            self.assertEqual(QImage(str(png)).pixelColor(0, 0), QColor('red'))
            self.assertFalse(self.window.dirty)

    def wait_for_photo(self):
        for _ in range(150):
            if not self.window.photo_job:
                return
            QTest.qWait(10)
        self.fail('Photo load did not finish')

    def test_large_photo_opens_as_bounded_preview_without_enabling_save(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'large.jpg'
            self.assertTrue(photo(5100, 3300, 'red').save(str(path)))
            self.assertTrue(self.window.open_path(str(path)))
            self.wait_for_photo()
            self.assertEqual(self.window.path, path)
            self.assertEqual(self.window.preview_size.width(), 5100)
            self.assertLessEqual(self.window.canvas.image.width(), 2560)
            self.assertFalse(self.window.edit_toggle.isEnabled())
            self.assertFalse(self.window.save_as())
            self.assertEqual(self.window.copy_action.text(), 'Copy preview')
            self.window.copy()
            image = self.app.clipboard().image()
            self.assertIn(f'{image.width()} × {image.height()}', self.window.status.text())

    def test_file_created_during_save_is_not_overwritten(self):
        from desktop_icons import rename_no_replace
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'new.png'
            def concurrent_rename(source, destination):
                path.write_bytes(b'concurrent producer')
                return rename_no_replace(source, destination)
            with (patch('mellipi_photos.FileChooser.getSaveFileName', return_value=(str(path), '')),
                  patch('mellipi_photos.rename_no_replace', side_effect=concurrent_rename),
                  patch('mellipi_photos.themed_prompt') as prompt):
                self.assertFalse(self.window.save_as())
                self.assertEqual(path.read_bytes(), b'concurrent producer')
                self.assertIn('appeared', prompt.call_args.args[2])

    def test_confirmed_replacement_refuses_file_changed_during_confirmation(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'replace.png'
            path.write_bytes(b'original')
            def prompt(_owner, title, *_):
                if title == 'Replace existing copy?':
                    path.write_bytes(b'other writer')
                    return True
                return False
            with (patch('mellipi_photos.FileChooser.getSaveFileName', return_value=(str(path), '')),
                  patch('mellipi_photos.themed_prompt', side_effect=prompt)):
                self.assertFalse(self.window.save_as())
                self.assertEqual(path.read_bytes(), b'other writer')

    def test_slideshow_skips_unreadable_images_and_stops_at_end_or_on_edit(self):
        with TemporaryDirectory() as tmp:
            first, middle, last = (Path(tmp) / f'{name}.png' for name in ('a', 'b', 'c'))
            self.assertTrue(photo(20, 30, 'red').save(str(first)))
            middle.write_text('not an image')
            self.assertTrue(photo(30, 20, 'blue').save(str(last)))
            view = self.window
            self.assertTrue(view.open_path(str(first)))
            self.wait_for_photo()
            view.slideshow_button.click()
            self.assertTrue(view.slideshow.isActive())
            view.advance_slideshow()
            self.wait_for_photo()
            self.assertEqual(view.path, last)
            self.assertFalse(view.slideshow.isActive())
            self.assertFalse(view.slideshow_button.isEnabled())
            self.assertTrue(view.open_path(str(first)))
            self.wait_for_photo()
            view.slideshow_button.click()
            view.rotate()
            self.assertTrue(view.dirty)
            self.assertFalse(view.slideshow.isActive())
            view.advance_slideshow()
            self.assertEqual(view.path, first)
