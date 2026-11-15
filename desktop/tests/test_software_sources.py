"""First-run APT discovery and refresh use the native package manager."""
import unittest
from unittest.mock import patch

from software_sources import APT_CACHE, APT_GET, DPKG_QUERY, PKEXEC, apt_search, refresh_apt


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


class InstalledSoftwareTests(unittest.TestCase):
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
