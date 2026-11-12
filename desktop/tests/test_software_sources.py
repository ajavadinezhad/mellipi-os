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
