#!/usr/bin/env python3
"""Exercise the Space Map and reversible moves on a disposable native session."""
import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
spec = importlib.util.spec_from_file_location('native_shell_qa', ROOT/'tools/qa-native-shell.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
qa = base.qa
from native_compositor import NativeCompositor


FIXTURE = """import sys
from PyQt6.QtWidgets import QApplication, QWidget
app=QApplication([])
app.setApplicationName(sys.argv[1]); app.setDesktopFileName(sys.argv[1])
window=QWidget(); window.setWindowTitle(sys.argv[1]); window.resize(395, 230); window.show()
raise SystemExit(app.exec())
"""


def main():
    parent = native = None
    fixtures = []
    with tempfile.TemporaryDirectory(prefix='mellipi-space-map-') as temporary:
        directory = Path(temporary)
        settings = directory/'parent.json'
        settings.write_text('{"profile":"economy","desktopIcons":false,"reducedMotion":true}')
        config = directory/'config'
        config.mkdir()
        env = dict(os.environ, ORBIT_QA='1', ORBIT_SETTINGS_FILE=str(settings),
                   ORBIT_DATA=str(directory/'parent-data'), XDG_CONFIG_HOME=str(config),
                   PULSE_SERVER='unix:'+str(directory/'no-audio'), LIBGL_ALWAYS_SOFTWARE='1',
                   GALLIUM_DRIVER='llvmpipe')
        for key in ('SWAYSOCK', 'WAYLAND_DISPLAY', 'DISPLAY', 'ORBIT_NATIVE_CONTROL', 'MESA_LOADER_DRIVER_OVERRIDE'):
            env.pop(key, None)
        try:
            with (directory/'parent.log').open('w') as log:
                parent = subprocess.Popen([str(ROOT/'run-wayland-session.sh'), '--headless'],
                                          env=env, cwd=ROOT, stdout=log, stderr=log, start_new_session=True)
            _, parent_env = qa.wait(lambda:qa.native_process(settings), 30)
            settings = directory/'native.json'
            settings.write_text(json.dumps(dict(profile='economy', desktopIcons=False, reducedMotion=True,
                                                shellLayout='fold', windowPlacementEnabled=False, textScale=1.5)))
            env = dict(parent_env, ORBIT_SETTINGS_FILE=str(settings), ORBIT_DATA=str(directory/'native-data'),
                       ORBIT_FOLD_DIR=str(directory), XDG_CONFIG_HOME=str(config),
                       PULSE_SERVER='unix:'+str(directory/'no-audio'), LIBGL_ALWAYS_SOFTWARE='1',
                       GALLIUM_DRIVER='llvmpipe')
            with (directory/'native.log').open('w') as log:
                native = subprocess.Popen([str(ROOT/'run-native-session.sh'), '--nested'], env=env,
                                          cwd=ROOT, stdout=log, stderr=log, start_new_session=True)
            _, child = qa.wait(lambda:base.process(settings), 40)
            for key in ('SWAYSOCK', 'WAYLAND_DISPLAY', 'DISPLAY', 'XDG_RUNTIME_DIR',
                        'DBUS_SESSION_BUS_ADDRESS', 'ORBIT_NATIVE_CONTROL'):
                os.environ.pop(key, None)
                if key in child:
                    os.environ[key] = child[key]
            client = NativeCompositor(child['ORBIT_NATIVE_CONTROL'])
            qa.wait(lambda:qa.control('status'))

            def window(title):
                return next((w for w in client.windows() if w['title']==title), None)

            for backend, title in (('wayland', 'map-wayland-fixture'), ('xcb', 'map-x11-fixture')):
                display = client.status().get('xdisplay')
                if backend=='xcb' and display is None:
                    raise RuntimeError('Private Xwayland fixture is unavailable')
                fixture_env = dict(child, QT_QPA_PLATFORM=backend, QT_WAYLAND_SHELL_INTEGRATION='xdg-shell')
                if backend=='xcb':
                    fixture_env['DISPLAY'] = ':'+str(display)
                with (directory/f'{backend}.log').open('w') as log:
                    fixtures.append(subprocess.Popen(['/usr/bin/python3', '-c', FIXTURE, title], env=fixture_env,
                                    stdout=log, stderr=log, start_new_session=True))
                qa.wait(lambda:window(title), 10)

            def host_view(node):
                if str(node.get('name','')).startswith('Orbit Native'):
                    return node
                for child_node in node.get('nodes', [])+node.get('floating_nodes', []):
                    child_view=host_view(child_node)
                    if child_view:
                        return child_view

            os.environ['SWAYSOCK'] = parent_env['SWAYSOCK']
            try:
                host = host_view(base.sway_request(4))
                outer = base.sway_request(3)[0]['rect']
            finally:
                os.environ.pop('SWAYSOCK', None)
            assert host, 'Private native compositor is not visible in the fixture parent'
            region, inner = host['rect'], host['window_rect']
            offset_x, offset_y = region['x']+inner['x'], region['y']+inner['y']
            bounds = client.snapshot()['outputs'][0]['rect']
            center_x, center_y = bounds['width']//2, bounds['height']//2
            with closing(base.VirtualPointer(parent_env)) as pointer:
                pointer.move(offset_x+center_x, offset_y+center_y, outer['width'], outer['height'])
                time.sleep(.14)
                point=client.status()['pointer']
                offset_x+=center_x-point['x']; offset_y+=center_y-point['y']

                def item(name):
                    return qa.wait(lambda:qa.control('qa-shell-item:'+name), 5)

                def click(name):
                    row=item(name)
                    pointer.click(offset_x+row['x']+row['width']/2, offset_y+row['y']+row['height']/2,
                                  outer['width'], outer['height'])

                def key(code):
                    stamp=int(time.monotonic()*1000)&0xffffffff
                    pointer.send(pointer.keyboard_id, 1, struct.pack('=III', stamp, code, 1))
                    pointer.send(pointer.keyboard_id, 1, struct.pack('=III', stamp+1, code, 0))
                    pointer.roundtrip()
                    time.sleep(.12)

                click('spineSpaceMap')
                qa.wait(lambda:qa.control('status')['panel']=='space-map')
                for index in range(4):
                    item(f'spaceMapTile{index}')
                qa.wait(lambda:item('spaceMapTile0').get('activeFocus'),5)
                key(106)  # Right
                qa.wait(lambda:item('spaceMapTile1').get('activeFocus'),5)
                click('spaceMapSwitch')
                qa.wait(lambda:client.status()['workspace']==2)
                qa.control('workspace:1')
                qa.wait(lambda:client.status()['workspace']==1)
                print('PASS opens from workspace strip, arrow navigation, and switch at 150% text size', flush=True)

                for title in ('map-wayland-fixture', 'map-x11-fixture'):
                    before=window(title)
                    qa.control('space-map')
                    button='spaceMapMove'+before['id']
                    def laid_out():
                        view, target = item('panelBody'), item(button)
                        return target['x'] > view['x']+view['width']/2
                    qa.wait(laid_out,5)
                    click(button)
                    qa.wait(lambda:item('spaceMapDestination1').get('activeFocus'),5)
                    key(28)  # Enter
                    try:
                        qa.wait(lambda:window(title)['desktop']==1,5)
                    except AssertionError:
                        print('move debug',window(title),qa.control('qa-shell-item:spaceMapMove'+before['id']),
                              qa.control('qa-shell-item:spaceMapDestination1'),file=sys.stderr)
                        raise
                    click('spaceMapCheckpoints')
                    click('spaceCheckpoint0')
                    assert item('restoreSpaceCheckpoint')['enabled']
                    click('restoreSpaceCheckpoint')
                    qa.wait(lambda:window(title)['desktop']==0,5)
                    click('spaceMapUndo')
                    qa.wait(lambda:window(title)['desktop']==1,5)
                    assert window(title)['id']==before['id']
                    key(1)  # Escape
                    qa.wait(lambda:qa.control('status')['panel']=='')
                    print('PASS move, preview, restore and undo for '+title, flush=True)
                errors=qa.control('status')['qml_errors']
                assert not errors, errors
        except Exception:
            for name in ('parent.log', 'native.log', 'native-data/native-session.log', 'wayland.log', 'xcb.log'):
                path=directory/name
                if path.is_file():
                    print(name+':\n'+path.read_text(errors='replace')[-6000:], file=sys.stderr)
            raise
        finally:
            for process in fixtures:
                base.stop(process)
            base.stop(native)
            base.stop(parent)


if __name__=='__main__':
    main()
