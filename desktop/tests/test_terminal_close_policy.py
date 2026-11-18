from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mellipi_terminal import idle_shell


class TerminalClosePolicyTests(unittest.TestCase):
    def test_idle_shell_closes_without_prompt_but_job_and_reused_pid_do_not(self):
        with TemporaryDirectory() as directory:
            proc = Path(directory) / '37'
            task = proc / 'task' / '37'
            task.mkdir(parents=True)
            children = task / 'children'
            children.write_text('')
            terminal = SimpleNamespace(child_pid=37, child_generation=100, interactive_shell=True)
            fields = ['S', '1', '37', '37', '1', '37']
            with patch('mellipi_terminal.terminal_process', return_value=(proc, 100, fields)):
                self.assertTrue(idle_shell(terminal))
                children.write_text('98 ')
                self.assertFalse(idle_shell(terminal))
                children.write_text('')
                fields[5] = '98'
                self.assertFalse(idle_shell(terminal))
            fields[5] = '37'
            with patch('mellipi_terminal.terminal_process', return_value=(proc, 101, fields)):
                self.assertFalse(idle_shell(terminal))
            terminal.interactive_shell = False
            with patch('mellipi_terminal.terminal_process', return_value=(proc, 100, fields)):
                self.assertFalse(idle_shell(terminal))
