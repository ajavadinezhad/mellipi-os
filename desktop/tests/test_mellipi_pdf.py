"""Exercise reading position persistence using a real Poppler fixture."""
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPlainTextEdit

from mellipi_pdf import PdfWindow, ReadingPositions


def write_pdf(path):
    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Count 3 /Kids [3 0 R 4 0 R 5 0 R] >>',
        *[b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 6 0 R >>'] * 3,
        b'<< /Length 0 >>\nstream\nendstream',
    ]
    pdf = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(f'{number} 0 obj\n'.encode() + obj + b'\nendobj\n')
    xref = len(pdf)
    pdf.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:
        pdf.extend(f'{offset:010d} 00000 n \n'.encode())
    pdf.extend(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    path.write_bytes(pdf)


class PdfPositionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait(self, condition):
        for _ in range(250):
            if condition():
                return
            QTest.qWait(20)
        self.fail('PDF operation did not finish')

    @unittest.skipUnless(shutil.which('pdfinfo') and shutil.which('pdftoppm'), 'requires Poppler CLI')
    def test_close_reopen_and_document_replacement(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'XDG_STATE_HOME': tmp, 'ORBIT_SETTINGS_FILE': tmp+'/settings.json'}):
            path = Path(tmp)/'fixture.pdf'
            write_pdf(path)
            first_key = ReadingPositions.key(path)
            first = PdfWindow(str(path))
            try:
                self.wait(lambda: first.pending_position == (first_key, 1))
                first.go(3)
                self.wait(lambda: first.pending_position == (first_key, 3))
            finally:
                first.close()

            reopened = PdfWindow(path.as_uri())
            try:
                self.wait(lambda: reopened.pending_position == (first_key, 3))
                self.assertIn('Resumed at page 3 of 3', reopened.status.text())
            finally:
                reopened.close()

            replacement = path.with_suffix('.new')
            write_pdf(replacement)
            replacement.replace(path)
            new_key = ReadingPositions.key(path)
            self.assertNotEqual(first_key, new_key)
            revised = PdfWindow(str(path))
            try:
                self.wait(lambda: revised.pending_position == (new_key, 1))
                self.assertNotIn('Resumed', revised.status.text())
            finally:
                revised.close()

    @unittest.skipUnless(shutil.which('pdfinfo') and shutil.which('pdftoppm'), 'requires Poppler CLI')
    def test_source_replacement_keeps_original_revision_exportable(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'XDG_STATE_HOME': tmp}):
            path = Path(tmp) / 'original.pdf'
            write_pdf(path)
            original = path.read_bytes()
            exported = path.with_name('exported.pdf')
            window = PdfWindow(str(path))
            try:
                self.wait(lambda: window.pending_position is not None)
                window.marks.append(('note', 1, (.1, .2), 'keep this note'))
                window.annotation_dirty = True
                replacement = path.with_suffix('.replacement')
                replacement.write_bytes(original + b'\n% replacement revision\n')
                replacement.replace(path)
                window.go(2)
                self.wait(lambda: window.pending_position is not None and window.pending_position[1] == 2)
                self.assertIn('Original changed', window.status.text())
                self.assertEqual(window.reader_path().read_bytes(), original)
                with patch('mellipi_pdf.FileChooser.getSaveFileName', return_value=(str(exported), '')):
                    window.save_annotated_copy()
                    self.wait(lambda: not window.exporting)
                self.assertFalse(window.annotation_dirty, window.status.text())
                self.assertTrue(exported.is_file())
                self.assertTrue(path.read_bytes().endswith(b'% replacement revision\n'))
            finally:
                window.annotation_dirty = False
                window.close()

    @unittest.skipUnless(shutil.which('pdfinfo') and shutil.which('pdftoppm'), 'requires Poppler CLI')
    def test_adjacent_page_is_prefetched_then_reused(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'XDG_STATE_HOME': tmp}):
            path = Path(tmp) / 'adjacent.pdf'
            write_pdf(path)
            window = PdfWindow(str(path))
            try:
                self.wait(lambda: 2 in window.page_cache)
                with patch.object(window.renderer, 'run') as render:
                    window.go(2)
                    render.assert_not_called()
                self.assertEqual(window.page, 2)
                self.assertFalse(window.canvas.image.isNull())
            finally:
                window.close()

    def test_page_text_dialog_selects_current_search_phrase(self):
        window = PdfWindow()
        self.addCleanup(window.close)
        window.document = Path('/tmp/fixture.pdf')
        window.query.setText('selected phrase')

        def extract(_command, _arguments, ready, **_options):
            ready(b'Sample SELECTED PHRASE on this page.', '')

        def inspect(dialog):
            content = dialog.findChild(QPlainTextEdit)
            self.assertTrue(content.isReadOnly())
            self.assertEqual(content.textCursor().selectedText(), 'SELECTED PHRASE')

        with patch.object(window.text_reader, 'run', side_effect=extract), patch(
                'mellipi_pdf.exec_owned_dialog', side_effect=inspect):
            window.show_page_text()

    def test_private_and_bounded(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'XDG_STATE_HOME': tmp}):
            storage = ReadingPositions()
            with patch('mellipi_pdf.MAX_READING_POSITIONS', 2):
                for name in ('older', 'middle', 'newest'):
                    self.assertTrue(storage.save(name, 4))
            self.assertEqual(storage.get('older', 8), 1)
            self.assertEqual(storage.get('middle', 8), 4)
            self.assertEqual(storage.get('newest', 3), 1)
            self.assertEqual(storage.directory.stat().st_mode & 0o777, 0o700)
            self.assertEqual(storage.path.stat().st_mode & 0o777, 0o600)
            storage.path.chmod(0o644)
            self.assertEqual(storage.get('middle', 8), 1)
            self.assertFalse(storage.save('other', 4))

    @unittest.skipUnless(shutil.which('pdfinfo') and shutil.which('pdftoppm'), 'requires Poppler CLI')
    def test_bookmarks_survive_reopen_and_navigate_without_changing_pdf(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'XDG_STATE_HOME': tmp, 'ORBIT_SETTINGS_FILE': tmp+'/settings.json'}):
            path = Path(tmp) / 'bookmarks.pdf'
            write_pdf(path)
            original = path.read_bytes()
            key = ReadingPositions.key(path)
            first = PdfWindow(str(path))
            try:
                self.wait(lambda: first.pending_position == (key, 1))
                first.go(2)
                first.toggle_bookmark()
                first.go(3)
                self.wait(lambda: first.pending_position == (key, 3))
            finally:
                first.close()
            reopened = PdfWindow(str(path))
            try:
                self.wait(lambda: reopened.pending_position == (key, 3))
                reopened.show_bookmarks()
                page = next(action for action in reopened.bookmark_menu.actions() if action.text() == 'Page 2')
                page.trigger()
                self.assertEqual(reopened.page, 2)
                reopened.toggle_bookmark()
                self.assertEqual(ReadingPositions().bookmarks(key, 3), ())
                self.assertEqual(path.read_bytes(), original)
            finally:
                reopened.close()

    def test_close_after_successful_export_but_not_after_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            window = PdfWindow()
            self.addCleanup(window.deleteLater)
            window.document = Path(tmp) / 'original.pdf'
            window.marks = [('note', 1, (), 'Notes')]
            window.annotation_dirty = True
            window.show()
            request = Mock()
            with (patch.object(window, 'annotation_request', request),
                  patch('mellipi_pdf.themed_choice', return_value=1) as choice,
                  patch('mellipi_pdf.FileChooser.getSaveFileName', return_value=(str(Path(tmp) / 'copy.pdf'), ''))):
                self.assertFalse(window.close())
                self.assertIs(choice.call_args.args[0], window)
                request.call_args.args[3](None, 'No space left')
                self.app.processEvents()
                self.assertTrue(window.isVisible())
                self.assertTrue(window.annotation_dirty)
                self.assertFalse(window.close())
                request.call_args.args[3]({'saved': True}, '')
                self.wait(lambda: not window.isVisible())
