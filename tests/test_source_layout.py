"""Protect both checkout resources and the flat installed module layout."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import json
import os
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

def load(path):
    spec = importlib.util.spec_from_file_location('abstract_path_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class SourceLayoutTest(unittest.TestCase):
    def test_source_entries_and_assets_have_distinct_roots(self):
        paths = load(ROOT / 'desktop/src/project_paths.py')
        self.assertEqual(paths.PROJECT_ROOT, ROOT / 'desktop')
        self.assertTrue(paths.module_path('native_app.py').is_file())
        self.assertTrue(paths.session_path('native_session.py').is_file())
        self.assertTrue((paths.PROJECT_ROOT / 'native/Desktop.qml').is_file())

    def test_native_owner_bootstraps_from_source_and_flat_install(self):
        source = ROOT / 'desktop/src'
        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory) / 'abstract'; (installed / 'session').mkdir(parents=True)
            shutil.copy2(source / 'project_paths.py', installed / 'project_paths.py')
            for name in ('native_session.py', 'child_events.py'):
                shutil.copy2(source / 'session' / name, installed / 'session' / name)
            for base, expected in ((source, ROOT / 'desktop'), (installed, installed)):
                env = dict(os.environ, PYTHONPATH=str(base))
                code = "import json; from session import native_session as n; print(json.dumps({'project':str(n.ROOT),'source':str(n.SOURCE_ROOT),'binary':str(n.BINARY)}))"
                result = json.loads(subprocess.check_output([sys.executable, '-c', code], env=env, cwd=directory, text=True))
                self.assertEqual(result['project'], str(expected))
                self.assertEqual(result['source'], str(base))
                self.assertEqual(result['binary'], str(expected / '.native-runtime/bin/orbit-compositor'))

    def test_installed_flat_layout_resolves_without_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            installed = Path(directory) / 'abstract'; installed.mkdir()
            shutil.copy2(ROOT / 'desktop/src/project_paths.py', installed / 'project_paths.py')
            paths = load(installed / 'project_paths.py')
            self.assertEqual(paths.PROJECT_ROOT, installed)
            self.assertEqual(paths.SOURCE_ROOT, installed)
            self.assertEqual(paths.module_path('native_app.py'), installed / 'native_app.py')
            self.assertEqual(paths.session_path('native_session.py'), installed / 'session/native_session.py')

if __name__ == '__main__': unittest.main()
