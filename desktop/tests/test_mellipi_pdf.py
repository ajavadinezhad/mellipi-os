"""Exercise reading position persistence using a real Poppler fixture."""
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

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
