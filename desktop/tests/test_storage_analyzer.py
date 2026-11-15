import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import storage_analyzer as storage


class StorageAnalyzerTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_sizes_direct_folders_without_following_links_or_reading_special_files(self):
        (self.root / 'small').write_bytes(b'one')
        tree = self.root / 'nested'
        tree.mkdir()
        (tree / 'data').write_bytes(b'second')
        (tree / 'cycle').symlink_to(self.root, target_is_directory=True)
        (self.root / 'duplicate').symlink_to(tree / 'data')
        os.mkfifo(self.root / 'fifo')
        report = storage.analyze(self.root)
        self.assertEqual(report.rows, (storage.StorageRow('nested', 6, True),
                                       storage.StorageRow('small', 3, False)))
        self.assertEqual((report.entries, report.total, report.incomplete), (6, 9, False))

    def test_symlink_root_and_ancestors_are_refused(self):
        folder = self.root / 'folder'
        folder.mkdir()
        (folder / 'subfolder').mkdir()
        link = self.root / 'link'
        link.symlink_to(folder, target_is_directory=True)
        for path in (link, link / 'subfolder'):
            with self.assertRaises(OSError):
                storage.analyze(path)

    def test_bounded_visits_and_independent_top_results(self):
        for size in range(1, 6):
            (self.root / str(size)).write_bytes(b'x' * size)
        limited = storage.analyze(self.root, max_entries=3)
        self.assertTrue(limited.incomplete)
        self.assertEqual(limited.entries, 3)
        with patch.object(storage, 'MAX_RESULTS', 2):
            report = storage.analyze(self.root)
        self.assertEqual([row.size for row in report.rows], [5, 4])
        self.assertEqual(report.total, 15)

    def test_cancel_and_depth_bound_report_partial_results(self):
        top = self.root / 'nested'
        top.mkdir()
        (top / 'child').mkdir()
        (top / 'child' / 'file').write_bytes(b'payload')
        report = storage.analyze(self.root, max_depth=1)
        self.assertTrue(report.incomplete)
        self.assertEqual(report.total, 0)
        steps = iter((False, True))
        stopped = storage.analyze(self.root, cancelled=lambda: next(steps, True))
        self.assertTrue(stopped.cancelled)
        self.assertTrue(stopped.incomplete)
        self.assertEqual(stopped.entries, 1)
