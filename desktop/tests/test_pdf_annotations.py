"""Round-trip standard annotations through the installed Poppler libraries."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from pdf_annotations import execute, revision


def fixture(rotation=0):
    body = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Count 1 /Kids [3 0 R] >>',
        f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 440 440] /CropBox [20 20 420 320] /Rotate {rotation} >>'.encode(),
    ]
    result = b'%PDF-1.4\n'
    offsets = []
    for number, obj in enumerate(body, 1):
        offsets.append(len(result))
        result += str(number).encode() + b' 0 obj\n' + obj + b'\nendobj\n'
    size = len(result)
    result += b'xref\n0 4\n0000000000 65535 f \n'
    result += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets)
    return result + f'trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n{size}\n%%EOF\n'.encode()


@unittest.skipUnless(shutil.which('pdftoppm'), 'Poppler renderer required')
class PdfAnnotationsTest(unittest.TestCase):
    def test_round_trip_offset_crop_and_rotation(self):
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation), tempfile.TemporaryDirectory() as folder:
                source, output = Path(folder) / 'source.pdf', Path(folder) / 'copy.pdf'
                original = fixture(rotation)
                source.write_bytes(original)
                request = {'revision': revision(source), 'marks': [
                    ['highlight', 1, [.12, .30, .37, .40], ''],
                    ['note', 1, [.65, .65], 'Notes á · سلام'],
                ]}
                self.assertTrue(execute('save', source, request, output))
                self.assertEqual(source.read_bytes(), original)
                self.assertEqual(execute('notes', output, {'page': 1}), ['Notes á · سلام'])
                self.assertIn(b'/Subtype /Highlight', output.read_bytes())
                self.assertIn(b'/Subtype /Text', output.read_bytes())
                pp = subprocess.check_output(['pdftoppm', '-r', '72', '-cropbox', '-singlefile', str(output)])
                _, dimensions, _, pixels = pp.split(b'\n', 3)
                width, height = map(int, dimensions.split())
                offset = (int(.35 * height)*width + int(.25 * width)) * 3
                self.assertLess(pixels[offset+2], 220, 'Highlight should cover the selected area')
                self.assertEqual(pixels[:3], b'\xff\xff\xff')
                with self.assertRaisesRegex(ValueError, 'Choose a new filename'):
                    execute('save', source, request, source)
                with self.assertRaisesRegex(ValueError, 'Choose a new filename'):
                    execute('save', source, request, output)

    def test_stale_document_and_empty_range_leave_no_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / 'source.pdf', Path(folder) / 'copy.pdf'
            source.write_bytes(fixture())
            request = {'revision': revision(source), 'marks': [
                ['highlight', 1, [.2, .3, .2, .7], ''],
            ]}
            with self.assertRaisesRegex(ValueError, 'highlight area is empty'):
                execute('save', source, request, output)
            source.write_bytes(fixture(90))
            with self.assertRaisesRegex(ValueError, 'original PDF changed'):
                execute('save', source, request, output)
            self.assertFalse(output.exists())
