"""First-run APT discovery and refresh use the native package manager."""
import unittest
from unittest.mock import patch

from software_sources import (APPSTREAM_CLI, APT_CACHE, APT_GET, DPKG_QUERY, PKEXEC,
                              apt_search, browse_system_apps, refresh_apt)


class AptFirstRunTests(unittest.TestCase):
    @patch('software_sources.executable', return_value=True)
    @patch('software_sources.run', return_value='Package files:\n 100 /var/lib/dpkg/status\n')
    def test_missing_index_offers_refresh_without_searching(self, run, _):
        result = apt_search('galculator')
        self.assertTrue(result.needs_refresh)
        self.assertEqual(result.packages, [])
        run.assert_called_once_with([APT_CACHE, 'policy'])

    @patch('software_sources.executable', side_effect=lambda path: path != PKEXEC)
    @patch('software_sources.run', return_value='Package files:\n 100 /var/lib/dpkg/status\n')
    def test_missing_authorization_helper_does_not_offer_refresh(self, _, __):
        self.assertFalse(apt_search('').needs_refresh)

    @patch('software_sources.executable', return_value=True)
    @patch('software_sources.run', side_effect=[
        'Package files:\n 500 https://archive.ubuntu.com/ubuntu noble/universe amd64 Packages\n',
        '',
        'galculator - scientific calculator\n',
    ])
    def test_populated_index_returns_installable_matches(self, run, _):
        result = apt_search('galculator')
        self.assertFalse(result.needs_refresh)
        self.assertEqual([package.identifier for package in result.packages], ['galculator'])
        self.assertEqual(run.call_args_list[1].args[0][0], DPKG_QUERY)

    @patch('software_sources.run')
    def test_refresh_requires_authorization_and_reports_partial_errors(self, run):
        refresh_apt()
        run.assert_called_once_with(
            [PKEXEC, APT_GET, '-o', 'APT::Update::Error-Mode=any', 'update'],
            timeout=None,
        )


class AppCatalogTests(unittest.TestCase):
    @patch('software_sources.executable', return_value=True)
    @patch('software_sources.run', side_effect=[
        'Package files:\n 500 https://example.org/ubuntu noble/universe amd64 Packages\n',
        '\n---\n'.join([
            'Identifier: a.desktop [desktop-application]\nName: A drawing app\nPackage: drawing',
            'Identifier: b.desktop [desktop-application]\nName: An editor\nSummary: Draw pictures\nPackage: editor',
            'Identifier: c.desktop [desktop-application]\nName: Duplicate editor\nPackage: editor',
            'Identifier: flatpak.desktop [desktop-application]\nName: Draw Flatpak\nBundle: flatpak:app/test',
            'Identifier: addon [addon]\nName: Draw Addon\nPackage: addon',
            'Identifier: bad.desktop [desktop-application]\nName: Draw bad\nPackage: ../bad',
            'Identifier: player.desktop [desktop-application]\nName: Music Player\nPackage: player',
        ]),
        'editor:amd64\tinstalled\t1.0\tImage editor\n',
    ])
    def test_category_shows_only_system_apps_and_filters_local_metadata(self, run, _):
        result = browse_system_apps('Graphics', 'DRAW')['apt']
        self.assertEqual([(p.identifier, p.installed, p.version) for p in result.packages],
                         [('drawing', False, ''), ('editor', True, '1.0')])
        self.assertEqual(run.call_args_list[1].args[0], [APPSTREAM_CLI, 'list-categories', 'Graphics'])

    @patch('software_sources.executable', return_value=True)
    @patch('software_sources.run', return_value='Package files:\n 100 /var/lib/dpkg/status\n')
    def test_category_without_apt_index_offers_existing_refresh(self, run, _):
        self.assertTrue(browse_system_apps('Office')['apt'].needs_refresh)
        run.assert_called_once_with([APT_CACHE, 'policy'])


class InstalledSoftwareTests(unittest.TestCase):
    @patch('software_sources.executable', return_value=True)
    def test_mellipi_migration_is_hidden_from_inventory_but_still_updates(self, _):
        from software_sources import apt_installed, apt_updates
        with patch('software_sources.run', return_value=(
            'abstract-shell\tinstalled\t0.1.20\tOld migration package\n'
            'mellipi-shell\tinstalled\t0.1.35\tMellipi desktop\n'
        )):
            self.assertEqual([p.identifier for p in apt_installed().packages], ['mellipi-shell'])
        with patch('software_sources.run', side_effect=[
            '500 Local main amd64 Packages\n',
            'Inst abstract-shell [0.1.20] (0.1.36 Local [all])\n',
        ]):
            row, = apt_updates().packages
            self.assertEqual(row.identifier,'abstract-shell')
            self.assertEqual(row.name,'Mellipi Shell compatibility')

    @patch('software_sources.executable', side_effect=lambda path: path == DPKG_QUERY)
    @patch('software_sources.run', return_value=(
        'hello:amd64\tinstalled\t2.10\tGreeter app\n'
        'hello:i386\tinstalled\t2.10\tGreeter app\n'
        'removed\tconfig-files\t1.0\tUninstalled\n'
        'other\tinstalled\t1.0\tAnother utility\n'
    ))
    def test_apt_inventory_needs_no_index_and_filters_local_metadata(self, run, _):
        from software_sources import installed_software
        result = installed_software('GREETER', ('apt',))['apt']
        self.assertEqual([p.identifier for p in result.packages], ['hello:amd64', 'hello:i386'])
        self.assertTrue(all(p.installed and p.version == '2.10' for p in result.packages))
        self.assertFalse(result.needs_refresh)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][:2], [DPKG_QUERY, '-W'])

    @patch('software_sources.executable', return_value=True)
    @patch('software_sources.run', side_effect=[
        'org.example.App\tExample App\t1.2\tstable\tflathub\n',
        RuntimeError('Inventory unavailable'),
    ])
    def test_flatpak_inventory_preserves_working_scope_when_other_fails(self, run, _):
        from software_sources import FLATPAK, installed_software
        seen = []
        result = installed_software('example', ('flatpak',), lambda *row: seen.append(row))['flatpak']
        self.assertEqual([(p.identifier, p.scope, p.branch) for p in result.packages],
                         [('org.example.App', 'user', 'stable')])
        self.assertIn('System Flatpak: Inventory unavailable', result.status)
        self.assertEqual(seen, [('flatpak', result)])
        self.assertEqual([call.args[0][:4] for call in run.call_args_list],
                         [[FLATPAK, '--user', 'list', '--app'],
                          [FLATPAK, '--system', 'list', '--app']])

    @patch('software_sources.executable', return_value=True)
    @patch('software_sources.SNAP_SOCKET')
    @patch('software_sources.snap_request', return_value=[
        {'name': 'hello-world', 'title': 'Hello World', 'version': '1.0'},
        {'name': '../../bad'},
    ])
    def test_snap_inventory_reads_only_local_snaps_endpoint(self, request, socket, _):
        from software_sources import installed_software
        socket.is_socket.return_value = True
        result = installed_software('', ('snap',))['snap']
        self.assertEqual([p.identifier for p in result.packages], ['hello-world'])
        request.assert_called_once_with('/v2/snaps')


class UpdateDiscoveryTests(unittest.TestCase):
    @patch('software_sources.executable', return_value=True)
    @patch('software_sources.run', side_effect=[
        'Package files:\n 500 https://example.org stable/main amd64 Packages\n',
        'Inst mellipi-shell [0.1.22] (0.1.23 Mellipi:stable [amd64])\n'
        'Inst libsample:i386 [1.0] (2.0 stable [i386])\n'
        'Inst new-package (1.0 stable [amd64])\n'
        'Conf mellipi-shell (0.1.23 stable [amd64])\n',
    ])
    def test_apt_update_check_is_read_only_and_preserves_architecture(self, run, _):
        from software_sources import apt_updates
        result = apt_updates()
        self.assertTrue(result.checked)
        self.assertFalse(result.check_failed)
        self.assertEqual([(p.identifier, p.version, p.update_version) for p in result.packages],
                         [('mellipi-shell', '0.1.22', '0.1.23'), ('libsample:i386', '1.0', '2.0')])
        self.assertEqual(run.call_args.args[0],
                         [APT_GET, '--simulate', '--no-remove',
                          '-o', 'APT::Get::Show-User-Simulation-Note=false', 'upgrade'])
        self.assertIn('local index', result.status)

    @patch('software_sources.executable', return_value=True)
    @patch('software_sources.run', return_value='100 /var/lib/dpkg/status\n')
    def test_missing_index_is_not_reported_as_no_updates(self, run, _):
        from software_sources import apt_updates
        result = apt_updates()
        self.assertTrue(result.needs_refresh)
        self.assertTrue(result.check_failed)
        self.assertFalse(result.checked)
        run.assert_called_once_with([APT_CACHE, 'policy'])

    @patch('software_sources.executable', return_value=True)
    @patch('software_sources.run', side_effect=[
        'org.example.App\tExample\t2.1\tstable\tflathub\n'
        'org.example.App\tExample\t2.1\tstable\tflathub\n',
        RuntimeError('Could not reach remote'),
    ])
    def test_flatpak_partial_failure_preserves_successful_updates(self, run, _):
        from software_sources import FLATPAK, flatpak_updates
        result = flatpak_updates()
        self.assertTrue(result.checked)
        self.assertTrue(result.check_failed)
        self.assertEqual([(p.identifier, p.scope, p.update_version) for p in result.packages],
                         [('org.example.App', 'user', '2.1')])
        self.assertIn('System Flatpak: Could not reach remote', result.status)
        self.assertEqual([call.args[0][:5] for call in run.call_args_list],
                         [[FLATPAK, '--user', 'remote-ls', '--app', '--updates'],
                          [FLATPAK, '--system', 'remote-ls', '--app', '--updates']])

    @patch('software_sources.executable', return_value=True)
    @patch('software_sources.SNAP_SOCKET')
    @patch('software_sources.snap_request', return_value=[
        {'name': 'example', 'title': 'Example', 'version': '2.0'}, {'name': '../bad'},
    ])
    def test_snap_refresh_listing_never_starts_an_update(self, request, socket, _):
        from software_sources import snap_updates
        socket.is_socket.return_value = True
        result = snap_updates()
        self.assertTrue(result.checked)
        self.assertEqual([(p.identifier, p.update_version) for p in result.packages],
                         [('example', '2.0')])
        request.assert_called_once_with('/v2/find', select='refresh')

    @patch('software_sources.apt_updates', side_effect=RuntimeError('APT failed'))
    @patch('software_sources.snap_updates')
    def test_one_source_failure_does_not_discard_the_other_result(self, snap, _):
        from software_sources import SourceResult, available_updates
        snap.return_value = SourceResult(status='Snap: 0 available.', checked=True)
        result = available_updates(('apt', 'snap'))
        self.assertTrue(result['apt'].check_failed)
        self.assertIn('System packages: APT failed', result['apt'].status)
        self.assertTrue(result['snap'].checked)


class SoftwareManagementTests(unittest.TestCase):
    @patch('software_sources.run', side_effect=['install\tinstalled\t\t\toptional\t1.0\n', '', '1.1'])
    def test_apt_update_never_removes_and_reports_version_change(self, run):
        from software_sources import Package, manage
        package = Package('apt', 'example.app:amd64', 'Example', '', installed=True)
        self.assertTrue(manage(package, 'update'))
        self.assertEqual(run.call_args_list[1].args[0],
                         [PKEXEC, APT_GET, '-y', '--only-upgrade', '--no-remove',
                          'install', '--', 'example.app:amd64'])

    @patch('software_sources.run', side_effect=[
        'install\tinstalled\t\t\toptional\t1.0\n',
        '/usr/share/applications/example.desktop\n', '',
    ])
    def test_apt_removal_targets_one_desktop_package_and_refuses_dependency_breakage(self, run):
        from software_sources import DPKG, Package, manage
        manage(Package('apt', 'example', 'Example', '', installed=True), 'remove')
        run.assert_called_with([PKEXEC, DPKG, '--refuse-depends', '--refuse-remove-essential',
                                '--refuse-remove-protected', '--remove', '--', 'example'], timeout=None)

    @patch('software_sources.run')
    def test_packages_without_desktop_entry_and_held_packages_are_not_removed(self, run):
        from software_sources import Package, manage
        package = Package('apt', 'example', 'Example', '', installed=True)
        run.side_effect = ['install\tinstalled\t\t\toptional\t1.0\n', '/usr/share/doc/example\n']
        with self.assertRaisesRegex(RuntimeError, 'desktop apps only'):
            manage(package, 'remove')
        self.assertEqual(run.call_count, 2)
        run.reset_mock()
        run.side_effect = ['hold\tinstalled\t\t\toptional\t1.0\n']
        with self.assertRaisesRegex(RuntimeError, 'on hold'):
            manage(package, 'remove')
        self.assertEqual(run.call_count, 1)

    def test_source_operations_keep_scope_and_user_data(self):
        from software_sources import FLATPAK, SNAP, Package, manage_arguments
        flatpak = Package('flatpak', 'org.example.App', 'Example', '', scope='user',
                          branch='stable', installed=True)
        command = manage_arguments(flatpak, 'remove')
        self.assertEqual(command[:4], [FLATPAK, '--user', 'uninstall', '--app'])
        self.assertEqual(command[-1], 'org.example.App//stable')
        self.assertNotIn('--delete-data', command)
        snap = Package('snap', 'example-app', 'Example', '', installed=True)
        self.assertEqual(manage_arguments(snap, 'remove'), [PKEXEC, SNAP, 'remove', '--', 'example-app'])

    def test_core_mellipi_and_malformed_ids_are_not_removed(self):
        from software_sources import Package, manage_arguments
        for name in ('mellipi-shell', 'abstract-shell', 'orbit-native', 'app:amd64;'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                manage_arguments(Package('apt', name, name, '', installed=True), 'remove')


class TransactionPhasesTests(unittest.TestCase):
    def test_replacement_search_is_not_blocked_or_overwritten_by_old_search(self):
        from threading import Event
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        from mellipi_software import SoftwareWindow
        from software_sources import Package, SourceResult
        app = self.application = QApplication.instance() or QApplication([])
        entered, hold = Event(), Event()
        def search_for(term, sources, partial):
            if term == 'old':
                entered.set()
                hold.wait(3)
            result = SourceResult([Package('apt', term, term, '')], '')
            partial('apt', result)
            return {'apt': result}
        with patch.object(SoftwareWindow, 'start_search'):
            window = SoftwareWindow()
            app.processEvents()
        with patch('mellipi_software.search', side_effect=search_for):
            try:
                window.query.setText('old')
                window.start_search()
                self.assertTrue(entered.wait(1))
                window.query.setText('new')
                window.start_search()
                for _ in range(100):
                    QTest.qWait(10)
                    if window.job is None:
                        break
                self.assertIsNotNone(window.retired_search)
                self.assertEqual(window.list.topLevelItem(0).text(0), 'new')
                hold.set()
                window.retired_search.wait(3000)
                app.processEvents()
                self.assertEqual(window.list.topLevelItem(0).text(0), 'new')
            finally:
                hold.set()
                for job in (window.retired_search, window.job):
                    if job:
                        job.wait(3000)
                app.processEvents()
                window.close()

    def test_fast_update_source_is_visible_before_slow_source_finishes(self):
        from threading import Event
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        from mellipi_software import SoftwareWindow
        from software_sources import Package, SourceResult

        app = self.application = QApplication.instance() or QApplication([])
        hold = Event()
        result = SourceResult([Package('apt', 'example-one', 'Example', '', installed=True)], 'APT ready', checked=True)
        def check(on_result):
            on_result('apt', result)
            hold.wait(2)
            return {'apt': result}
        with patch('mellipi_software.available_updates', side_effect=check):
            window = SoftwareWindow(show_updates=True)
            window.show()
            try:
                for _ in range(100):
                    if window.list.topLevelItemCount():
                        break
                    QTest.qWait(10)
                self.assertEqual(window.list.topLevelItem(0).text(0), 'Example')
                self.assertIn('Checking remaining', window.status.text())
                self.assertIsNotNone(window.job)
                self.assertTrue(window.list.isEnabled())
            finally:
                hold.set()
                if window.job:
                    window.job.wait(3000)
                app.processEvents()
                window.close()

    def test_multiple_apt_updates_are_one_no_remove_transaction(self):
        from software_sources import Package, manage_updates

        packages = [Package('apt', key, key, '', installed=True) for key in ('example-one', 'example-two')]
        with patch('software_sources.run', return_value='install installed'), patch('software_sources.transaction') as action:
            self.assertEqual(manage_updates(packages), 2)
            action.assert_called_once_with([PKEXEC, APT_GET, '-y', '--only-upgrade', '--no-remove',
                                            'install', '--', 'example-one', 'example-two'], None)

    def test_open_to_updates_skips_catalog_startup(self):
        from PyQt6.QtWidgets import QApplication
        from mellipi_software import SoftwareWindow
        from software_sources import available_updates

        app = self.application = QApplication.instance() or QApplication([])
        with patch.object(SoftwareWindow, 'start_job') as launch, patch.object(SoftwareWindow, 'start_search') as search:
            window = SoftwareWindow(show_updates=True)
            try:
                app.processEvents()
                search.assert_not_called()
                self.assertTrue(window.updates_only)
                self.assertIs(launch.call_args.args[0], available_updates)
            finally:
                window.close()

    def test_distinguishes_declined_authorization_from_package_output(self):
        import sys
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from software_sources import AuthorizationDeclined, transaction

        with TemporaryDirectory() as directory, patch('software_sources.PKEXEC', sys.executable):
            script = Path(directory) / 'fake-package-manager.py'
            script.write_text("import sys; print('canceled', file=sys.stderr); sys.exit(126)")
            phases = []
            with self.assertRaises(AuthorizationDeclined):
                transaction([sys.executable, str(script)], phases.append)
            self.assertEqual(phases, ['authorization'])

            script.write_text("import sys; print('started'); print('network offline', file=sys.stderr); sys.exit(1)")
            phases.clear()
            with self.assertRaisesRegex(RuntimeError, 'network offline'):
                transaction([sys.executable, str(script)], phases.append)
            self.assertEqual(phases, ['authorization', 'applying'])

            script.write_text("print('package changed')")
            phases.clear()
            self.assertEqual(transaction([sys.executable, str(script)], phases.append).strip(), 'package changed')
            self.assertEqual(phases, ['authorization', 'applying'])

    def test_software_can_minimize_during_a_transaction_and_keep_its_receipt(self):
        from threading import Event
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QApplication
        from mellipi_software import SoftwareWindow
        from software_sources import AuthorizationDeclined

        app = self.application = QApplication.instance() or QApplication([])
        release = Event()
        with patch.object(SoftwareWindow, 'start_search'):
            window = SoftwareWindow()
            window.show()
            app.processEvents()
        self.addCleanup(window.close)
        results = []

        def operation(observe):
            observe('authorization')
            if not release.wait(3):
                raise RuntimeError('The test timed out waiting for the simulated prompt.')
            raise AuthorizationDeclined('Administrator authorization was canceled.')

        def wait_for(predicate):
            for _ in range(100):
                if predicate():
                    return
                QTest.qWait(10)
            self.fail('Software did not update the transaction state')

        window.start_job(operation, lambda _value, error: results.append(error), 'Install Example')
        try:
            wait_for(lambda: 'Waiting for administrator authorization' in window.transaction_status.text())
            self.assertFalse(window.close())
            self.assertTrue(window.isMinimized())
            self.assertIsNotNone(window.job)
        finally:
            release.set()
        wait_for(lambda: window.job is None)
        window.showNormal()
        self.assertIn('Authorization not granted', window.transaction_status.text())
        self.assertTrue(window.transaction_details.isVisible())
        self.assertEqual(results, ['Administrator authorization was canceled.'])
