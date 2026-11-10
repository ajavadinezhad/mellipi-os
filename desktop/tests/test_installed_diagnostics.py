"""Diagnostic entrypoints never create a user profile, including root checks."""
import unittest
from unittest.mock import patch
import installed_launcher
class InstalledDiagnosticsTest(unittest.TestCase):
    def test_checks_and_help_exec_without_creating_profile_or_preview_state(self):
        for flag in ('--check','--check-login','--help','-h'):
            with self.subTest(flag=flag),patch('installed_launcher.sys.argv',['launcher','session',flag]),patch('installed_launcher.os.environ',{'HOME':'/nonexistent-qa-home'}),patch('installed_launcher.Path.mkdir') as mkdir,patch('installed_launcher.os.execve',side_effect=SystemExit(0)) as execute:
                with self.assertRaises(SystemExit):installed_launcher.main()
                mkdir.assert_not_called();self.assertIn(flag,execute.call_args.args[1])
