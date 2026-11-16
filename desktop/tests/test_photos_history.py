"""Photo edits are reversible without writing to the original image."""
from unittest import TestCase
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory
from PyQt6.QtGui import QColor, QImage
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

    def test_slideshow_skips_unreadable_images_and_stops_at_end_or_on_edit(self):
        with TemporaryDirectory() as tmp:
            first, middle, last = (Path(tmp) / f'{name}.png' for name in ('a', 'b', 'c'))
            self.assertTrue(photo(20, 30, 'red').save(str(first)))
            middle.write_text('not an image')
            self.assertTrue(photo(30, 20, 'blue').save(str(last)))
            view = self.window
            self.assertTrue(view.open_path(str(first)))
            view.slideshow_button.click()
            self.assertTrue(view.slideshow.isActive())
            view.advance_slideshow()
            self.assertEqual(view.path, last)
            self.assertFalse(view.slideshow.isActive())
            self.assertFalse(view.slideshow_button.isEnabled())
            self.assertTrue(view.open_path(str(first)))
            view.slideshow_button.click()
            view.rotate()
            self.assertTrue(view.dirty)
            self.assertFalse(view.slideshow.isActive())
            view.advance_slideshow()
            self.assertEqual(view.path, first)
