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

            # Save and restore a real maximized state while its workspace
            # is hidden, then verify the client's later Unmaximize geometry.
            output=client.snapshot()['outputs'][0]
            area=output['workarea']
            normal=dict(x=area['x']+72,y=area['y']+76,width=415,height=260)
            for title in ('map-wayland-fixture','map-x11-fixture'):
                ident=window(title)['id']
                client.move(ident,2)
                client.request('snap',id=ident,side='maximize',output=output['name'],restore_rect=normal)
                qa.wait(lambda:window(title)['maximized'])
                assert window(title)['desktop']==1, window(title)
                assert window(title)['restore_rect']==normal, window(title)
                client.switch_workspace(2)
                qa.wait(lambda:client.status()['workspace']==2)
                client.request('maximize',id=ident,restore=True)
                qa.wait(lambda:not window(title)['maximized'] and window(title)['rect']==normal)
                client.move(ident,1)
                client.switch_workspace(1)
                qa.wait(lambda:client.status()['workspace']==1)
            print('PASS hidden-workspace maximize and exact normal restore geometry for Wayland and Xwayland',flush=True)

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
                    row=qa.wait(lambda:current if (current:=item(name))['enabled'] else None, 5)
                    pointer.click(offset_x+row['x']+row['width']/2, offset_y+row['y']+row['height']/2,
                                  outer['width'], outer['height'])

                def drag(source, target, screenshot=None, cancel=False):
                    def center(name):
                        row=item(name)
                        assert row['visible'], (name, row)
                        return offset_x+row['x']+row['width']/2, offset_y+row['y']+row['height']/2

                    sx, sy=center(source)
                    tx, ty=center(target)

                    def button(pressed):
                        stamp=int(time.monotonic()*1000)&0xffffffff
                        pointer.send(5, 2, struct.pack('=III', stamp, 272, pressed))
                        pointer.send(5, 4)
                        pointer.roundtrip()

                    pointer.move(sx, sy, outer['width'], outer['height'])
                    time.sleep(.10)
                    button(1)
                    try:
                        for step in range(1, 11):
                            ratio=step/10
                            pointer.move(sx+(tx-sx)*ratio, sy+(ty-sy)*ratio,
                                         outer['width'], outer['height'])
                            time.sleep(.025)
                        qa.wait(lambda:qa.control('qa-shell-item:spaceMapDragPreview'), 2)
                        if cancel:
                            key(1)  # Cancel while still holding the pointer over a valid target.
                            qa.wait(lambda:not qa.control('qa-shell-item:spaceMapDragPreview'),2)
                        if screenshot:
                            subprocess.run(['grim', screenshot], env=child, check=True, timeout=5)
                    finally:
                        button(0)
                    time.sleep(.20)

                def key(code):
                    stamp=int(time.monotonic()*1000)&0xffffffff
                    pointer.send(pointer.keyboard_id, 1, struct.pack('=III', stamp, code, 1))
                    pointer.send(pointer.keyboard_id, 1, struct.pack('=III', stamp+1, code, 0))
                    pointer.roundtrip()
                    time.sleep(.12)

                def checkpoints():
                    return qa.control('qa-arrangement-state')['checkpoints']

                def wait_for_checkpoint(previous):
                    qa.wait(lambda: bool(rows:=checkpoints()) and rows[0]['id']!=previous,5)

                click('spineSpaceMap')
                qa.wait(lambda:qa.control('status')['panel']=='space-map')
                for index in range(4):
                    item(f'spaceMapTile{index}')
                qa.wait(lambda:item('spaceMapTile0').get('activeFocus'),5)
                key(106)  # Right
                qa.wait(lambda:item('spaceMapTile1').get('activeFocus'),5)
                key(28)  # Enter opens the space selected by the arrow key.
                qa.wait(lambda:client.status()['workspace']==2)
                qa.control('workspace:1')
                qa.wait(lambda:client.status()['workspace']==1)
                print('PASS opens from workspace strip, arrow navigation, and switch at 150% text size', flush=True)

                if qa.control('status')['panel']!='space-map':
                    qa.control('space-map')
                click('spaceMapTile0')
                click('spaceMapRename')
                qa.wait(lambda:item('spaceMapNameField').get('activeFocus'),5)
                for code in (31,20,22,32,21):  # study
                    key(code)
                key(28)
                qa.wait(lambda:json.loads(settings.read_text()).get('spaceNames',{}).get('0')=='study',5)
                assert client.status()['workspace']==1
                print('PASS keyboard workspace rename persists without switching or moving a window',flush=True)
                qa.wait(lambda:item('spaceMapTile0').get('activeFocus'),5)
                qa.control('space-map')
                qa.wait(lambda:qa.control('status')['panel']=='',5)

                # A real pointer gesture, rather than invoking the QML slot,
                # verifies the nested compositor seat, pointer grab and drop.
                for title, source_name in (('map-wayland-fixture', 'spaceMapWindow'),
                                           ('map-x11-fixture', 'spaceMapDiagramWindow')):
                    before=window(title)
                    qa.control('space-map')
                    source=source_name+before['id']
                    history=checkpoints()
                    if title=='map-wayland-fixture':
                        drag(source, 'spaceMapCheckpoints')
                        drag(source, 'spaceMapTile0')
                        drag(source, 'spaceMapTile1', cancel=True)
                        assert window(title)['id']==before['id']
                        assert window(title)['desktop']==0, window(title)
                        assert qa.control('status')['panel']=='space-map'
                        assert checkpoints()==history
                        print('PASS invalid, same-space, and Escape-canceled drops leave windows and history intact', flush=True)
                    capture=os.environ.get('MELLIPI_SPACE_MAP_DRAG_SCREENSHOT') if title=='map-wayland-fixture' else None
                    drag(source, 'spaceMapTile1', screenshot=capture)
                    qa.wait(lambda:window(title)['desktop']==1,5)
                    wait_for_checkpoint(history[0]['id'] if history else None)
                    assert window(title)['id']==before['id']
                    assert client.status()['workspace']==1, 'Drop should not switch away from the current space'
                    click('spaceMapCheckpoints')
                    item('spaceCheckpoint0')
                    checkpoint_id=checkpoints()[0]['id']
                    time.sleep(.18)  # Allow the scrolling viewport to finish relayout.
                    click('spaceCheckpoint0')
                    assert item('restoreSpaceCheckpoint')['enabled']
                    click('restoreSpaceCheckpoint')
                    qa.wait(lambda:window(title)['desktop']==0,5)
                    click('spaceMapUndo')
                    qa.wait(lambda:window(title)['desktop']==1,5)
                    assert window(title)['id']==before['id']
                    print('PASS pointer drag, checkpoint restore and undo for '+title, flush=True)

                    # Restore and move from the focused row without a Move button.
                    click('restoreSpaceCheckpoint')
                    qa.wait(lambda:window(title)['desktop']==0,5)
                    key(1)  # Close the checkpoint first, returning to its row.
                    def checkpoint_returned():
                        names=['spaceCheckpoint'+str(i) for i,row in enumerate(checkpoints()) if row['id']==checkpoint_id]
                        return bool((qa.control('qa-shell-item:'+(names[0] if names else 'spaceMapCheckpoints')) or {}).get('activeFocus'))
                    qa.wait(checkpoint_returned,5)
                    key(1)  # Now dismiss Space Map.
                    qa.wait(lambda:qa.control('status')['panel']=='')
                    qa.control('space-map')
                    row='spaceMapWindow'+before['id']
                    history=checkpoints()
                    assert not qa.control('qa-shell-item:spaceMapMove'+before['id'])
                    for _ in range(20):
                        if item(row).get('activeFocus'):break
                        key(15)  # Tab
                    assert item(row).get('activeFocus')
                    key(106)  # Right on the focused window row
                    qa.wait(lambda:window(title)['desktop']==1,5)
                    wait_for_checkpoint(history[0]['id'] if history else None)
                    assert window(title)['id']==before['id']
                    key(1)  # Escape
                    qa.wait(lambda:qa.control('status')['panel']=='')
                    print('PASS keyboard fallback move for '+title, flush=True)
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
