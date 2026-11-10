#!/usr/bin/env python3
"""Private regression checks for Quick Settings over maximized applications.

Uses disposable Qt Wayland, GTK Xwayland and Chrome Xwayland windows. No physical
input, user browser profiles, audio changes or real-session controls are used.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


qa = module('quick_qa_helpers', 'qa-screenshots-wayland.py')
inputs = module('quick_qa_inputs', 'qa_wayland_input.py')
import sway_events
from window_actions import find_window
from xwayland_controls import load_xlib


def views(node):
    result = [node] if node.get('app_id') or node.get('window') else []
    for child in node.get('nodes', []) + node.get('floating_nodes', []):
        result.extend(views(child))
    return result


def main():
    session = pointer = connection = None
    children = []
    routed = False
    results = []
    with tempfile.TemporaryDirectory(prefix='orbit-quick-max-') as temporary, open('/tmp/orbit-quick-maximized-qa.log', 'w') as log:
        directory = Path(temporary)
        settings = directory / 'settings.json'
        settings.write_text(json.dumps({'profile': 'economy', 'reducedMotion': False, 'workspaceMotion': True, 'desktopIcons': False}))
        environment = os.environ.copy()
        environment.update(ORBIT_SETTINGS_FILE=str(settings), ORBIT_DATA=str(directory / 'data'), ORBIT_QA='1', XDG_CONFIG_HOME=str(directory / 'config'))
        try:
            session = subprocess.Popen([str(ROOT / 'run-wayland-session.sh'), '--headless'], cwd=ROOT, env=environment, stdout=log, stderr=log, start_new_session=True)
            _, native = qa.wait(lambda: qa.native_process(settings), 30)
            assert native.get('ORBIT_NESTED') == '1'
            for key in ('SWAYSOCK', 'WAYLAND_DISPLAY', 'DISPLAY', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS'):
                if key in native: os.environ[key] = native[key]
            routed = True
            qa.wait(lambda: qa.control('status'))
            pointer = inputs.VirtualPointer(native)
            load_xlib()
            from Xlib import X, display
            connection = display.Display()
            state_atom = connection.intern_atom('_NET_WM_STATE')
            max_atoms = {connection.intern_atom('_NET_WM_STATE_MAXIMIZED_VERT'), connection.intern_atom('_NET_WM_STATE_MAXIMIZED_HORZ')}
            page = directory / 'fixture.html'
            page.write_text('<title>OrbitQuickMotionChrome</title><body style="background:#339955">Disposable Quick Settings test</body>')
            cases = [('Qt Wayland', ['/usr/bin/python3', '-c', qa.fixture_code], lambda n: n.get('app_id') == 'orbit-screenshot-fixture', {'QT_QPA_PLATFORM': 'wayland'})]
            if shutil.which('xfce4-terminal'):
                cases.append(('GTK Xwayland', ['xfce4-terminal', '--disable-server', '--title=OrbitQuickMotionGTK', '--geometry=70x20'], lambda n: n.get('window') and n.get('name') == 'OrbitQuickMotionGTK', {'GDK_BACKEND': 'x11'}))
            if shutil.which('google-chrome'):
                cases.append(('Chrome Xwayland', ['google-chrome', '--ozone-platform=x11', '--user-data-dir=' + str(directory / 'chrome'), '--no-first-run', '--no-default-browser-check', '--disable-extensions', page.as_uri()], lambda n: n.get('window') and 'OrbitQuickMotionChrome' in (n.get('name') or ''), {}))
            for label, command, matches, additions in cases:
                child = native.copy()
                child.pop('QT_WAYLAND_SHELL_INTEGRATION', None)
                child.update(additions)
                process = subprocess.Popen(command, cwd=ROOT, env=child, stdout=log, stderr=log)
                children.append(process)
                node = qa.wait(lambda: next((n for n in views(sway_events.request(4)) if matches(n)), None), 20)
                ident, xid = node['id'], node.get('window')
                time.sleep(.5)  # Let the app's initial titlebar/configure negotiation finish.
                sway_events.command(f'[con_id={ident}] focus')
                if label == 'Chrome Xwayland':
                    # Fresh Chrome profiles can use client-side decorations,
                    # so their own maximize protocol has no Orbit frame button.
                    subprocess.run(['wmctrl', '-ir', hex(xid), '-b', 'add,maximized_vert,maximized_horz'], env=native, check=True)
                    qa.wait(lambda: find_window(sway_events.request(4), ident)[0]['_outer_rect']['width'] >= 1270, 5)
                else:
                    frame = qa.wait(lambda: (s if (s := qa.control('status'))['frame_controls'].get('id') == str(ident) else None), 5)['frame_controls']
                    # Exercise Orbit's real maximize button and Xwayland route.
                    pointer.click(frame['x'] + 42, frame['y'] + frame['height'] / 2)
                    qa.wait(lambda: qa.control('status')['frame_controls'].get('maximized'), 5)
                time.sleep(.7)
                before = find_window(sway_events.request(4), ident)[0]['_outer_rect']
                generation = qa.control('status')['transition']['generation']
                samples = 0
                def check():
                    nonlocal samples
                    state = qa.control('status')
                    actual = find_window(sway_events.request(4), ident)[0]['_outer_rect']
                    assert actual == before, (label, before, actual)
                    assert not state['transition']['visible'] and state['transition']['generation'] == generation, (label, state['transition'])
                    assert not state['qml_errors'], state['qml_errors']
                    if xid:
                        prop = connection.create_resource_object('window', xid).get_full_property(state_atom, X.AnyPropertyType)
                        assert prop is not None and max_atoms.issubset(set(map(int, prop.value))), (label, list(prop.value) if prop else None, state['panel'], actual)
                    samples += 1
                for cycle in range(3):
                    qa.control('quick')
                    for _ in range(16): check(); time.sleep(.025)
                    assert qa.control('status')['panel'] == 'quick'
                    qa.control('quick')
                    for _ in range(10): check(); time.sleep(.025)
                results.append({'app': label, 'stable_geometry_and_state_samples': samples})
                sway_events.command(f'[con_id={ident}] kill')
                qa.wait(lambda: find_window(sway_events.request(4), ident) is None, 5)
            # An async workspace capture must never remap its old desktop image
            # above a utility panel opened while the capture/action is pending.
            for cycle in range(3):
                qa.control('workspace:2')
                qa.control('quick')
                destination = 3 if cycle == 2 else 2
                if destination == 3: qa.control('workspace:3')
                for _ in range(30):
                    state = qa.control('status')
                    assert state['panel'] == 'quick', state['panel']
                    assert not state['transition']['visible'], state['transition']
                    assert not state['qml_errors'], state['qml_errors']
                    time.sleep(.025)
                workspace = next(w for w in sway_events.request(1) if w['focused'])
                assert workspace['num'] == destination, workspace
                qa.control('quick')
                qa.control('workspace:1')
                qa.wait(lambda: next(w for w in sway_events.request(1) if w['focused'])['num'] == 1, 5)
                qa.wait(lambda: not qa.control('status')['transition']['visible'], 5)
                time.sleep(.3)
            print(json.dumps({'headless_only': True, 'applications': results, 'workspace_quick_races': 3, 'qml_errors': []}), flush=True)
            qa.control('quit')
            session.wait(timeout=12)
        finally:
            if pointer: pointer.close()
            if connection:
                try: connection.close()
                except Exception: pass
            for child in children:
                if child.poll() is None:
                    child.terminate()
                    try: child.wait(timeout=5)
                    except subprocess.TimeoutExpired: child.kill(); child.wait(timeout=5)
            if session and session.poll() is None and routed:
                try: sway_events.command('exit')
                except Exception: pass
            if session and session.poll() is None:
                try: session.wait(timeout=5)
                except subprocess.TimeoutExpired: session.terminate(); session.wait(timeout=5)
    return 0


if __name__ == '__main__':
    sys.exit(main())
