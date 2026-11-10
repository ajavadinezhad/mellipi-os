#!/usr/bin/env python3
"""Finite screenshots QA in an isolated headless desktop containing one test app.

Never routes capture commands to the physical/user desktop. All preferences,
context data, Pictures, and user-dir configuration live in a temporary directory.
"""
import json
import os
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from screenshots import PNG


def wait(check, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = check()
        except (OSError, ValueError):
            value = None
        if value:
            return value
        time.sleep(.04)
    raise AssertionError('Timed out waiting for private screenshot QA')


def native_process(settings):
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():continue
        try:
            if str(ROOT / 'native_app.py').encode() not in (proc / 'cmdline').read_bytes().split(b'\0'):continue
            entries = dict(item.split(b'=', 1) for item in (proc / 'environ').read_bytes().split(b'\0') if b'=' in item)
            if entries.get(b'ORBIT_SETTINGS_FILE') == str(settings).encode() and entries.get(b'ORBIT_NESTED') == b'1' and b'SWAYSOCK' in entries:
                return int(proc.name), {key.decode(): value.decode() for key, value in entries.items()}
        except OSError:pass


def control(command):
    from control import socket_path
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(3)
        connection.connect(socket_path())
        connection.sendall((command + '\n').encode())
        response = bytearray()
        while True:
            part = connection.recv(32768)
            if not part:break
            response.extend(part)
    return json.loads(response) if response else None


def fixture_windows(node):
    result = [node] if node.get('app_id') == 'orbit-screenshot-fixture' else []
    for child in node.get('nodes', []) + node.get('floating_nodes', []):
        result.extend(fixture_windows(child))
    return result


fixture_code = '''from PyQt5.QtWidgets import QApplication,QWidget,QVBoxLayout,QLabel
from PyQt5.QtCore import QTimer
app=QApplication([]);app.setApplicationName('orbit-screenshot-fixture');app.setDesktopFileName('orbit-screenshot-fixture')
window=QWidget();window.setWindowTitle('Orbit disposable screenshot fixture');window.resize(360,220)
window.setStyleSheet('QWidget { background:#f0f4f5; color:#223b42; }')
layout=QVBoxLayout(window);layout.addWidget(QLabel('Disposable screenshot test window'));window.show()
QTimer.singleShot(60000,app.quit);app.exec()
'''


def main():
    session = fixture = None
    routed = False
    captures = []
    with tempfile.TemporaryDirectory(prefix='orbit-screenshot-qa-') as temporary:
        directory = Path(temporary)
        settings = directory / 'settings.json'
        settings.write_text(json.dumps({'profile': 'economy', 'reducedMotion': True}))
        configuration = directory / 'config'
        configuration.mkdir()
        pictures = directory / 'Pictures'
        (configuration / 'user-dirs.dirs').write_text('XDG_PICTURES_DIR="' + str(pictures) + '"\n')
        environment = os.environ.copy()
        environment.update(ORBIT_SETTINGS_FILE=str(settings), ORBIT_DATA=str(directory / 'data'), ORBIT_QA='1', XDG_CONFIG_HOME=str(configuration))
        with open('/tmp/orbit-screenshot-qa.log', 'w') as log:
            try:
                session = subprocess.Popen([str(ROOT / 'run-wayland-session.sh'), '--headless'], cwd=ROOT, env=environment, stdout=log, stderr=log, start_new_session=True)
                pid, native_environment = wait(lambda:native_process(settings), 30)
                # Every routed command below targets this exact temporary session.
                for key in ('SWAYSOCK', 'WAYLAND_DISPLAY', 'DISPLAY', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS'):
                    if key in native_environment:os.environ[key] = native_environment[key]
                routed = True
                status = wait(lambda:control('status'))
                assert status['wayland'] and status['screen_geometry']['width'] == 1280, status
                assert not status['qml_errors'], status['qml_errors']
                fixture_environment = native_environment.copy()
                fixture_environment['QT_WAYLAND_SHELL_INTEGRATION'] = 'xdg-shell'
                interpreter = '/usr/bin/python3' if native_environment.get('ORBIT_WAYLAND_RUNTIME') == 'system' else str(ROOT / '.venv/bin/python')
                fixture = subprocess.Popen([interpreter, '-c', fixture_code], cwd=ROOT, env=fixture_environment, stdout=log, stderr=log)
                import sway_events
                view = wait(lambda:next(iter(fixture_windows(sway_events.request(4))), None))
                wait(lambda:any(row['windows'] and 'orbit-screenshot-fixture' in row['name'] for row in control('status')['dock']))
                sway_events.command('[app_id="orbit-screenshot-fixture"] focus')
                time.sleep(.15)  # Allow the shell's coalesced window event to arrive.
                for kind, command in [('screen', 'qa-shot-screen'), ('window', 'qa-shot-window'), ('area', 'qa-shot-area')]:
                    previous = control('status')['screenshots']['lastPath']
                    control(command)
                    def completed():
                        snapshot = control('status')
                        shot = snapshot['screenshots']
                        if shot['error']:raise AssertionError(shot['error'])
                        return snapshot if not shot['busy'] and shot['lastPath'] != previous else None
                    captured = wait(completed)
                    assert not captured['qml_errors'], captured['qml_errors']
                    path = Path(captured['screenshots']['lastPath'])
                    assert path.parent == pictures / 'Screenshots', path
                    data = path.read_bytes()
                    assert data.startswith(PNG) and len(data) > 256 and data[12:16] == b'IHDR', path
                    dimensions = struct.unpack('>II', data[16:24])
                    if kind == 'screen':expected = (1280, 720)
                    elif kind == 'area':expected = (180, 120)
                    else:
                        geometry = fixture_windows(sway_events.request(4))[0]['rect']
                        expected = (geometry['width'], geometry['height'])
                    assert dimensions == expected, (kind, dimensions, expected)
                    assert stat.S_IMODE(path.stat().st_mode) == 0o600, path.stat().st_mode
                    captures.append(dict(kind=kind, width=dimensions[0], height=dimensions[1], bytes=len(data), mode='0600'))
                control('qa-shot-select')
                wait(lambda:control('status')['screenshots']['selecting'])
                control('qa-shot-cancel')
                canceled = wait(lambda:(snapshot if not (snapshot:=control('status'))['screenshots']['selecting'] else None))
                assert not canceled['qml_errors'], canceled['qml_errors']
                assert len(list((pictures / 'Screenshots').glob('*.png'))) == 3
                control('quit')
                session.wait(timeout=12)
                assert session.returncode == 0, session.returncode
                print(json.dumps({'headless_only': True, 'runtime': native_environment.get('ORBIT_WAYLAND_RUNTIME'), 'captures': captures, 'selection_cancel': True, 'qml_errors': []}), flush=True)
            finally:
                if fixture and fixture.poll() is None:
                    fixture.terminate()
                    fixture.wait(timeout=5)
                if session and session.poll() is None and routed:
                    import sway_events
                    try:sway_events.command('exit')
                    except Exception:pass
                if session and session.poll() is None:
                    try:session.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        session.terminate()
                        session.wait(timeout=5)
    return 0


if __name__ == '__main__':sys.exit(main())
