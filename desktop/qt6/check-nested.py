#!/usr/bin/env python3
"""Verify the Qt 6 panel against a disposable headless compositor."""
import json
import os
from pathlib import Path
import subprocess
import sys
import struct
from io import BytesIO
from PIL import Image
import tempfile
import time

desktop = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(desktop / "src"))
from native_compositor import NativeCompositor
sys.path.insert(0, str(desktop / "tools"))
from qa_wayland_input import VirtualPointer


def wait(predicate):
    for _ in range(200):
        if result := predicate():
            return result
        time.sleep(.1)
    raise RuntimeError("Timed out waiting for private Qt 6 compositor state")


with tempfile.TemporaryDirectory(prefix="mellipi-qt6-qa-") as directory:
    root = Path(directory)
    env = dict(os.environ, XDG_RUNTIME_DIR=directory, ORBIT_NESTED="1", ORBIT_QA="1",
               ORBIT_SETTINGS_FILE=str(root / "settings.json"))
    visual_check = "--saved-spaces" in sys.argv
    if visual_check:
        from theme_catalog import theme
        preset = theme(os.environ.get("MELLIPI_QA_THEME", "lavender"))
        (root / "settings.json").write_text(json.dumps(dict(
            mode=preset["mode"], darkLevel=preset["darkLevel"], accent=preset["accent"],
            themePreset=preset["id"], themeContrast={preset["id"]: os.environ.get("MELLIPI_QA_CONTRAST") == "1"},
            textScale=float(os.environ.get("MELLIPI_QA_SCALE", "1")))))
        area = dict(x=0, y=0, width=1200, height=800)
        fixture = root / "layouts.json"
        fixture.write_text(json.dumps(dict(version=1, layouts=[
            dict(id="a"*32, name="Coding", windows=[
                dict(app="mellipi-files.desktop", klass="mellipi-files", area=area,
                     rect=dict(area, width=600), desktop=1, output="", snap=None,
                     fullscreen=False, floating=True)])])))
        fixture.chmod(0o600)
    else:
        (root / "settings.json").write_text('{"mode":"light"}')
    for key in ("DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET", "SWAYSOCK", "ORBIT_NATIVE_CONTROL"):
        env.pop(key, None)
    config = root / "sway.conf"
    config.write_text("output HEADLESS-1 mode 1280x800\nseat seat0 fallback true\n")
    children = []

    def start(command, child_env, name):
        with (root / name).open("w") as log:
            children.append(subprocess.Popen(command, env=child_env, stdout=log, stderr=log))

    def ready():
        for line in (root / "native").read_text().splitlines():
            try:
                row = json.loads(line)
                if isinstance(row, dict) and row.get("ready"):
                    return row
            except ValueError:
                pass

    try:
        start(["sway", "-c", str(config)], dict(env, WLR_BACKENDS="headless", WLR_RENDERER="pixman",
              WLR_LIBINPUT_NO_DEVICES="1"), "sway")
        outer = wait(lambda: next((p.name for p in root.glob("wayland-*") if p.is_socket()), None))
        start([str(desktop / ".native-runtime/bin/orbit-compositor")],
              dict(env, WAYLAND_DISPLAY=outer, LIBGL_ALWAYS_SOFTWARE="1"), "native")
        status = wait(ready)
        client = NativeCompositor(status["control"])
        installed = "--installed" in sys.argv[1:]
        full = installed or "--full" in sys.argv[2:]
        command = ["/usr/bin/python3", str(desktop / "src/native_app.py")] if full else [sys.argv[1], "--nested-shell"]
        if installed:
            command = ["/usr/lib/abstract/run-native-shell.sh"]
        start(command, dict(env, QT_QPA_PLATFORM="wayland", ORBIT_QT="6", ORBIT_DATA=str(root / "data"),
              QT_WAYLAND_SHELL_INTEGRATION="layer-shell",
              QT_QUICK_BACKEND="software", WAYLAND_DISPLAY=status["wayland_display"],
              ORBIT_NATIVE_CONTROL=status["control"]), "shell")

        def reserves_bottom():
            if children[-1].poll() is not None: raise RuntimeError("Shell exited before mapping")
            for output in client.snapshot()["outputs"]:
                rect, work = output["rect"], output["workarea"]
                if (work["x"] > rect["x"] if full else rect["height"] - work["height"] == 48 and rect["y"] == work["y"]):
                    return True

        wait(reserves_bottom)
        if full:
            from control import socket_path
            import socket
            os.environ.update(XDG_RUNTIME_DIR=directory, WAYLAND_DISPLAY=status["wayland_display"])
            def query(command="status"):
                try:
                    with socket.socket(socket.AF_UNIX) as connection:
                        connection.settimeout(1)
                        connection.connect(socket_path())
                        connection.sendall((command+"\n").encode())
                        with connection.makefile() as response:
                            data=response.read()
                        return json.loads(data) if data else None
                except OSError:
                    return None
            shell_status = query
            state = wait(shell_status)
            assert not state["qml_errors"], state["qml_errors"]
            time.sleep(2)
            assert children[-1].poll() is None and shell_status(), "Qt 6 shell stopped after mapping"
            if "--launcher-timing" in sys.argv:
                def until(predicate, timeout=4):
                    deadline=time.monotonic()+timeout
                    while time.monotonic()<deadline:
                        if predicate():return
                        time.sleep(.008)
                    raise AssertionError(("Launcher never became ready", samples, children[-1].poll(), (shell_status() or {}).get("panel"),
                                          query("qa-shell-item:foldAppSearch")))
                samples=[]
                for _ in range(7):
                    began=time.monotonic()
                    query("launcher")
                    until(lambda:(query("qa-shell-item:foldAppSearch") or {}).get("activeFocus"))
                    samples.append(round((time.monotonic()-began)*1000))
                    query("launcher")
                    until(lambda:(shell_status() or {}).get("panel")=="")
                    # Allow the close animation to finish between trials.
                    time.sleep(.27)
                print("Launcher request to focused search (ms):",samples,flush=True)
            if visual_check:
                query("launcher")
                wait(lambda: (query("qa-shell-item:foldAppSearch") or {}).get("activeFocus"))
                query("quick")
                wait(lambda: (shell_status() or {}).get("panel") == "quick")
                query("launcher")
                wait(lambda: (query("qa-shell-item:foldAppSearch") or {}).get("activeFocus"))
                print("PASS keyboard focus starts in Super search on open and after switching panels")
                card = wait(lambda: query("qa-shell-item:launcherSavedSpaces"))
                assert card["height"] > 0 and card["width"] > 100, card
                assert not shell_status()["qml_errors"], shell_status()["qml_errors"]
                print("PASS saved layout preview visible in Super")
                if "--calculator" in sys.argv:
                    from contextlib import closing
                    with closing(VirtualPointer(dict(env, WAYLAND_DISPLAY=outer))) as keyboard:
                        for key in (9, 12, 3):  # 8-2
                            stamp=int(time.monotonic()*1000)&0xffffffff
                            for pressed in (1,0):
                                keyboard.send(keyboard.keyboard_id,1,struct.pack("=III",stamp,key,pressed))
                            keyboard.roundtrip()
                        result=wait(lambda:query("qa-shell-item:launcherCalculationResult"))
                        assert result.get("text")=="6", result
                        print("PASS Super calculates 8-2 from keyboard input")
            if "--utility-icons" in sys.argv:
                for panel, item in (("quick","systemSettingsLink"),("notifications","notificationDndToggle"),
                                    ("screenshot","screenshotPanel")):
                    query(panel)
                    control=wait(lambda:query("qa-shell-item:"+item))
                    assert control["width"]>0 and control["height"]>0, control
                    assert not shell_status()["qml_errors"], shell_status()["qml_errors"]
                print("PASS Quick Settings, Notifications and Screenshot icon controls load")
            if "--settings" in sys.argv:
                query("system-settings")
                settings = wait(lambda: (value := (shell_status() or {}).get("settings_window",{})) and value["ready"] and value)
                assert not settings["errors"], settings["errors"]
                wait(lambda: any(w["klass"]=="orbit-settings" for w in client.windows()))
                assert not shell_status()["settings_window"]["errors"]
                print("PASS Settings opens as a separate Qt 6 window with no QML errors")
                row = next(w for w in client.windows() if w["klass"] == "orbit-settings")
                client.request("minimize", id=int(row["id"]))
                wait(lambda: any(w["id"] == row["id"] and w["minimized"] for w in client.windows()))
                client.request("close", id=int(row["id"]))
                wait(lambda: not any(w["id"] == row["id"] for w in client.windows()))
                query("system-settings")
                wait(lambda: any(w["klass"] == "orbit-settings" and w["id"] != row["id"] for w in client.windows()))
                print("PASS minimized Settings closes and reopens as a fresh window")
            print("PASS existing Mellipi shell reserves its Wayland taskbar and stays running under Qt 6")
            raise SystemExit(0)
        print("PASS Qt 6 Wayland panel reserves 48 pixels along the bottom edge")
        rect = client.snapshot()["outputs"][0]["rect"]
        inner = dict(env, WAYLAND_DISPLAY=status["wayland_display"])
        outer_input = VirtualPointer(dict(env, WAYLAND_DISPLAY=outer))
        try:
            def center():
                image = Image.open(BytesIO(subprocess.check_output(
                    ["grim", "-"], env=inner, timeout=5))).convert("RGB")
                return image.getpixel((image.width // 2, image.height // 2))
            before = center()
            outer_input.click(44, rect["height"] - 22, rect["width"], rect["height"])
            wait(lambda: center() == (250, 249, 253))
            for state in (1, 0):
                outer_input.send(outer_input.keyboard_id, 1, struct.pack("=III", 100 + state, 1, state))
            outer_input.roundtrip()
            wait(lambda: center() == before)
            print("PASS launcher opens from the real panel and Escape dismisses it")
        finally:
            outer_input.close()
    except Exception:
        for name in ("sway", "native", "shell"):
            if (root / name).exists():
                print(name, (root / name).read_text()[:8500] if name == "shell" else (root / name).read_text()[-900:], file=sys.stderr)
        raise
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
