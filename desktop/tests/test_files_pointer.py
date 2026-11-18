"""Exercise mouse delivery through the real Qt Files event filter."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PyQt6.QtCore import QPoint, QSettings, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from mellipi_files import Files


class FilesPointerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_drop_on_inactive_folder_tab_uses_that_folder(self):
        from PyQt6.QtCore import QMimeData, QPointF, QUrl
        from PyQt6.QtGui import QDropEvent
        with TemporaryDirectory() as directory:
            root=Path(directory)
            one,two=root/'one',root/'two'
            one.mkdir()
            two.mkdir()
            source=two/'note.txt'
            source.write_text('example')
            window=Files(one)
            try:
                window.show()
                window.new_folder_tab()
                window.navigate(two)
                self.application.processEvents()
                mime=QMimeData()
                mime.setUrls([QUrl.fromLocalFile(str(source))])
                tabs=window.folder_tabs
                event=QDropEvent(QPointF(tabs.tabRect(0).center()),Qt.DropAction.CopyAction,
                                 mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
                with patch.object(window,'transfer_paths') as transfer:
                    window.eventFilter(tabs,event)
                    self.assertTrue(event.isAccepted())
                    transfer.assert_called_once_with([source],one,False)
                self.assertEqual(window.folder,two)
            finally:
                window.close()

    def test_folder_tabs_keep_location_search_and_selection_and_skip_deleted_history(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            one, two, three = (root / name for name in ('one', 'two', 'three'))
            for path in (one, two, three):
                path.mkdir()
            match = one / 'report.txt'
            match.write_text('sample')
            window = Files(one)
            try:
                window.show()
                window.show_search()
                window.search.setText('report')
                QTest.qWait(150)
                index = window.proxy.mapFromSource(window.model.index(str(match)))
                self.assertTrue(index.isValid())
                window.view.setCurrentIndex(index)
                self.assertEqual(window.selected(), [match])
                window.new_folder_tab()
                self.assertTrue(window.navigate(two))
                self.assertTrue(window.navigate(three))
                two.rmdir()
                window.step(-1)
                self.assertEqual(window.folder, one)
                self.assertFalse(window.search_row.isVisible())
                window.step(1)
                self.assertEqual(window.folder, three)
                window.folder_tabs.setCurrentIndex(0)
                self.assertEqual(window.folder, one)
                self.assertEqual(window.search.text(), 'report')
                self.assertEqual(window.selected(), [match])
                window.close_folder_tab(0)
                self.assertEqual(window.folder_tabs.count(), 1)
                self.assertEqual(window.folder, three)
            finally:
                window.close()
                self.application.processEvents()

    def test_deleted_history_is_removed_when_no_folder_remains_in_that_direction(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first, current, last = (root / name for name in ('first', 'current', 'last'))
            for folder in (first, current, last):
                folder.mkdir()
            window = Files(first)
            try:
                window.navigate(current)
                window.navigate(last)
                window.step(-1)
                first.rmdir()
                last.rmdir()
                window.back.click()
                self.assertEqual(window.folder, current)
                self.assertFalse(window.back.isEnabled())
                self.assertTrue(window.forward.isEnabled())
                window.forward.click()
                self.assertEqual(window.folder, current)
                self.assertFalse(window.forward.isEnabled())
                self.assertEqual(window.history, [current])
            finally:
                window.close()
                self.application.processEvents()

    def test_rename_does_not_move_a_replacement_created_during_confirmation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            selected, incoming = root / 'selected.txt', root / 'incoming.txt'
            selected.write_text('original')
            incoming.write_text('written by another app')
            window = Files(root)
            def prompt(*_):
                incoming.replace(selected)
                return 'renamed.txt'
            try:
                with patch.object(window, 'selected', return_value=[selected]), \
                     patch.object(window, 'ask_name', side_effect=prompt), \
                     patch.object(window, 'run_job', side_effect=lambda operation: operation()):
                    with self.assertRaisesRegex(ValueError, 'changed'):
                        window.rename()
                self.assertEqual(selected.read_text(), 'written by another app')
                self.assertFalse((root / 'renamed.txt').exists())
            finally:
                window.close()
                self.application.processEvents()

    def test_trash_does_not_start_when_a_selected_file_was_replaced(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first, selected, incoming = root / 'first.txt', root / 'selected.txt', root / 'incoming.txt'
            first.write_text('keep first file')
            selected.write_text('original')
            incoming.write_text('written by another app')
            window = Files(root)
            def prompt(*_):
                incoming.replace(selected)
                return True
            try:
                with patch.object(window, 'selected', return_value=[first, selected]), \
                     patch('mellipi_files.themed_prompt', side_effect=prompt), \
                     patch('mellipi_files.Gio.File.new_for_path') as gio, \
                     patch.object(window, 'run_job', side_effect=lambda operation: operation()):
                    with self.assertRaisesRegex(ValueError, 'changed'):
                        window.trash()
                gio.assert_not_called()
                self.assertEqual(first.read_text(), 'keep first file')
                self.assertEqual(selected.read_text(), 'written by another app')
            finally:
                window.close()
                self.application.processEvents()

    def test_moves_and_clicks_including_resize_margin_do_not_raise(self):
        with TemporaryDirectory() as directory:
            window = Files(Path(directory))
            window.show()
            central = window.centralWidget()
            # SIP reports Python event filter exceptions to sys.excepthook.
            with patch.object(sys, 'excepthook') as exception:
                QTest.mouseMove(central, QPoint(2, 2))
                QTest.mouseClick(central, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
                QTest.mouseMove(central, QPoint(75, 50))
                QTest.mouseClick(central, Qt.MouseButton.LeftButton, pos=QPoint(75, 50))
                QTest.mouseClick(window.places[Path.home()], Qt.MouseButton.LeftButton)
                exception.assert_not_called()
            self.assertEqual(window.folder, Path.home())
            window.close()
            self.application.processEvents()

    def test_folder_search_stays_over_results_and_closes_on_navigation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            child = root / 'Subfolder'
            child.mkdir()
            window = Files(root)
            try:
                window.show()
                window.show_search()
                for width, places in ((800, window.places_panel), (430, window.places_button)):
                    window.resize(width, 350)
                    self.application.processEvents()
                    self.assertTrue(places.isVisible())
                    self.assertTrue(window.search.isVisible())
                    self.assertEqual(window.search_row.x(), window.view.x())
                    self.assertGreater(window.search_row.x(), places.geometry().right())
                    self.assertEqual(window.search_row.width(), window.view.width())
                window.search.setText('Subfolder')
                self.assertTrue(window.navigate(child))
                self.assertFalse(window.search_row.isVisible())
                self.assertEqual(window.search.text(), '')
            finally:
                window.close()
                self.application.processEvents()

    def test_compact_places_can_navigate_without_the_sidebar(self):
        with TemporaryDirectory() as directory:
            window = Files(Path(directory))
            try:
                window.resize(430, 350)
                window.show()
                self.application.processEvents()
                self.assertTrue(window.places_panel.isHidden())
                window.places_menu.popup(window.places_button.mapToGlobal(window.places_button.rect().bottomLeft()))
                self.assertTrue(window.places_menu.isVisible())
                QTest.keyClick(window.places_menu, Qt.Key.Key_Down)
                QTest.keyClick(window.places_menu, Qt.Key.Key_Return)
                self.assertEqual(window.folder, Path.home())
            finally:
                window.close()
                self.application.processEvents()

    def test_subfolder_search_finds_nested_name_without_following_directory_symlink(self):
        from threading import Event
        from mellipi_files import find_nested_names
        with TemporaryDirectory() as directory, TemporaryDirectory() as outside:
            root = Path(directory)
            project = root / 'Project'
            project.mkdir()
            match = project / 'Meeting.TXT'
            match.touch()
            (Path(outside) / 'Meeting outside.txt').touch()
            (root / 'Linked').symlink_to(outside, target_is_directory=True)
            stop = Event()
            self.assertEqual(find_nested_names(root, 'meeting', stop), ([match], False, 0))
            stop.set()
            self.assertEqual(find_nested_names(root, 'meeting', stop), ([], False, 0))
            window = Files(root)
            try:
                window.show()
                window.show_search()
                window.search.setText('meeting')
                window.nested_button.click()
                for _ in range(100):
                    if window.nested_results.topLevelItemCount():
                        break
                    QTest.qWait(10)
                self.assertEqual(window.nested_results.topLevelItemCount(), 1)
                self.assertEqual(window.nested_results.topLevelItem(0).text(1), 'Project')
                window.view.setCurrentIndex(window.proxy.index(0, 0, window.view.rootIndex()))
                picked = window.nested_results.topLevelItem(0)
                window.nested_results.setCurrentItem(picked)
                open_action = next(action for action in window.actions if action.text() == 'Open')
                with patch('mellipi_files.QDesktopServices.openUrl', return_value=True) as opening:
                    open_action.trigger()
                    self.assertEqual(opening.call_args.args[0].toLocalFile(), str(match))
                    picked.setSelected(False)
                    opening.reset_mock()
                    open_action.trigger()
                    opening.assert_not_called()
                self.assertEqual(window.folder, root)
                self.assertTrue(window.navigate(project))
                self.assertFalse(window.nested_results.isVisible())
            finally:
                window.close()
                self.application.processEvents()

    def test_bookmarks_are_shared_and_disambiguate_matching_folder_names(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / 'Work' / 'Reports', root / 'Personal' / 'Reports'
            for folder in (first, second):
                folder.mkdir(parents=True)
            first_window, second_window = Files(root), Files(root)
            try:
                for window in (first_window, second_window):
                    window.bookmark_settings = QSettings(str(root / 'files.ini'), QSettings.Format.IniFormat)
                first_window.add_bookmark(first)
                second_window.add_bookmark(second)
                first_window.add_bookmark(first)
                first_window.render_bookmarks()
                action, = [item for item in first_window.bookmark_menu.actions() if str(first.parent) in item.text()]
                self.assertIn(str(second.parent), ' '.join(item.text() for item in first_window.bookmark_menu.actions()))
                action.trigger()
                self.assertEqual(first_window.folder, first)

                second_window.change_bookmark(str(first), 'Work reports')
                self.assertEqual(first_window.read_bookmarks(), {str(first): 'Work reports', str(second): 'Reports'})
                first_window.change_bookmark(str(first))
                self.assertEqual(second_window.read_bookmarks(), {str(second): 'Reports'})
                self.assertTrue(first.is_dir())
            finally:
                first_window.close()
                second_window.close()
                self.application.processEvents()

    def test_file_actions_are_owner_bounded_and_keyboard_traversable(self):
        with TemporaryDirectory() as directory:
            window = Files(Path(directory))
            try:
                window.resize(494, 240)
                window.show()
                QTest.qWait(60)
                window.open_file_actions()
                QTest.qWait(30)
                overlay = window.action_sheet
                rows = [row for row in overlay.buttons if row.isEnabled()]
                self.assertIs(self.application.focusWidget(), rows[0])
                self.assertTrue(window.centralWidget().rect().contains(overlay.panel.geometry()))
                self.assertGreater(overlay.scroll.verticalScrollBar().maximum(), 0)
                QTest.keyClick(rows[0], Qt.Key.Key_Backtab)
                self.assertIs(self.application.focusWidget(), rows[-1])
                QTest.keyClick(rows[-1], Qt.Key.Key_Tab)
                self.assertIs(self.application.focusWidget(), rows[0])
                window.resize(530, 230)
                QTest.qWait(30)
                self.assertTrue(window.centralWidget().rect().contains(overlay.panel.geometry()))
                QTest.keyClick(rows[0], Qt.Key.Key_Escape)
                self.assertFalse(overlay.isVisible())
                self.assertIs(self.application.focusWidget(), overlay.anchor)
            finally:
                window.close()
                self.application.processEvents()
