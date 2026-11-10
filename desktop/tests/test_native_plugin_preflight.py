"""A missing Qt shell integration must fail before acquiring the graphical seat."""
import json,os,unittest
from unittest.mock import Mock,patch
from session import native_session
class NativePluginPreflightTest(unittest.TestCase):
    def test_missing_plugin_is_actionable_and_prevents_compositor_spawn(self):
        replies=[Mock(returncode=1,stdout=b'',stderr=b'layer-shell plugin absent'),Mock(returncode=0,stdout=json.dumps(dict(compiled=True,cards=['/dev/dri/fixture'])))]
        with patch.dict(os.environ,{},clear=True),patch.object(native_session.Path,'is_file',return_value=True),patch.object(native_session.os,'access',return_value=True),patch.object(native_session.subprocess,'run',side_effect=replies),patch('session.preflight.inspect',return_value=dict(issues=[],warnings=[])),patch.object(native_session.subprocess,'Popen') as spawn:
            with self.assertRaisesRegex(RuntimeError,'layer-shell-qt'):native_session.run()
            spawn.assert_not_called()
