import importlib.util,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
path=Path(__file__).resolve().parents[1]/'tools/qa-hardware-readiness.py';spec=importlib.util.spec_from_file_location('hardware_report',path);hardware=importlib.util.module_from_spec(spec);spec.loader.exec_module(hardware)

class HardwareReadinessTests(unittest.TestCase):
    def test_connected_display_observation_does_not_certify_hotplug_or_suspend(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);card=root/'class/drm/card0';card.mkdir(parents=True);connector=root/'class/drm/card0-HDMI-A-1';connector.mkdir();(connector/'status').write_text('connected');(connector/'modes').write_text('1920x1080\n1280x720\nmalformed\n');(connector/'enabled').write_text('enabled')
            commands=[]
            def run(command,**kwargs):
                commands.append(command)
                return SimpleNamespace(returncode=0,stdout='s "yes"\n' if command[0]=='busctl' else '[{"name":"bluez_input.PRIVATE-MAC","monitor_of_sink":4294967295}]')
            result=hardware.collect({},root,run,lambda env:{'status':'observed','capabilities':{'session_lock':True}})
            self.assertEqual(result['observations']['drm']['connected_count'],1);self.assertEqual(result['observations']['drm']['connectors'][0]['modes'],['1920x1080','1280x720'])
            self.assertEqual(result['acceptance']['suspend_resume']['status'],'not_tested');self.assertFalse(result['all_hardware_certified']);self.assertNotIn('PRIVATE-MAC',json.dumps(result));self.assertEqual([c[0] for c in commands],['busctl','pactl']);self.assertFalse(any('Suspend' in c for c in commands))
    def test_missing_services_and_sysfs_are_not_a_false_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            def run(command,**kw):raise FileNotFoundError()
            report=hardware.collect({},Path(temporary),run,lambda env:{'status':'unavailable'})
            self.assertEqual(report['observations']['drm']['status'],'unavailable');self.assertEqual(report['observations']['audio']['status'],'unavailable');self.assertTrue(all(r['status']=='not_tested' for r in report['acceptance'].values()));self.assertFalse(report['changed_system_settings'])
    def test_monitor_sources_not_reported_as_physical_microphones(self):
        def run(command,**kw):return SimpleNamespace(returncode=0,stdout='[{"name":"output.monitor","monitor_of_sink":2},{"name":"input","monitor_of_sink":4294967295}]')
        result=hardware.audio_observations({},run);self.assertEqual(result['microphone_source_count'],1);self.assertFalse(result['physical_recording_tested'])

if __name__=='__main__':unittest.main()
