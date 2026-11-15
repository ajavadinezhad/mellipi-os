#!/bin/sh
set -eu
desktop=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
binary=$(realpath "${1:?Pass the Qt 6 binary}")
prefix=$(realpath "${2:?Pass the private LayerShellQt prefix}")
output=$(realpath -m "${3:?Pass the output .deb}")
stage=$(mktemp -d)
trap 'rm -rf -- "$stage"' EXIT
lib="$stage/usr/lib/mellipi-qt6"
mkdir -p "$lib"
# Ship the existing shell and QML, not the prototype executable.
for source in "$desktop"/src/*.py; do install -m644 "$source" "$lib/"; done
cp -R "$desktop/native" "$desktop/themes" "$lib/"
ln -s /usr/lib/abstract/.lock-runtime "$lib/.lock-runtime"
ln -s /usr/lib/abstract/.tray-runtime "$lib/.tray-runtime"
ln -s /usr/lib/abstract/tools "$lib/tools"
ln -s /usr/lib/abstract/session "$lib/session"
install -Dm644 "$prefix/lib/x86_64-linux-gnu/libLayerShellQtInterface.so.5" "$lib/libLayerShellQtInterface.so.5"
install -Dm644 "$prefix/lib/x86_64-linux-gnu/plugins/wayland-shell-integration/liblayer-shell.so" "$lib/plugins/wayland-shell-integration/liblayer-shell.so"
python3 - "$desktop/src/session/native_session.py" "$lib/native_login.py" <<'PY'
from pathlib import Path
import sys
source = Path(sys.argv[1]).read_text()
old = "lambda:launch([str(ROOT/'run-native-shell.sh')],environment=environment)"
assert source.count(old) == 1
source = source.replace(old, "lambda:launch(['/usr/lib/mellipi-qt6/launch-shell'],environment=environment)")
source = source.replace('sys.path.insert(0,str(Path(__file__).resolve().parents[1]))', 'sys.path.insert(0,"/usr/lib/abstract")')
Path(sys.argv[2]).write_text(source)
PY
cat > "$lib/launch-shell" <<'SCRIPT'
#!/bin/sh
# On shell startup failure, fall back inside the same compositor.
if env LD_LIBRARY_PATH=/usr/lib/mellipi-qt6 QT_PLUGIN_PATH=/usr/lib/mellipi-qt6/plugins \
    ORBIT_QT=6 QT_QPA_PLATFORM=wayland QT_WAYLAND_SHELL_INTEGRATION=layer-shell \
    MELLIPI_QT6_LAYER_LIBRARY=/usr/lib/mellipi-qt6/libLayerShellQtInterface.so.5 \
    /usr/bin/python3 /usr/lib/mellipi-qt6/native_app.py; then
    exit 0
fi
exec /usr/lib/abstract/run-native-shell.sh
SCRIPT
chmod 755 "$lib/launch-shell"
mkdir -p "$stage/usr/bin" "$stage/usr/share/wayland-sessions" "$stage/DEBIAN"
cat > "$stage/usr/bin/mellipi-qt6-session" <<'SCRIPT'
#!/usr/bin/python3
import os
import sys
from pathlib import Path
sys.path.insert(0, "/usr/lib/abstract")
from installed_launcher import user_environment
env = user_environment()
env.update(ORBIT_INSTALLED_SESSION="1", MELLIPI_QT6_LOGIN="1")
env.pop("ORBIT_NESTED", None)
for path in (Path(env["ORBIT_DATA"]), Path(env["ORBIT_SETTINGS_FILE"]).parent):
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
os.execve("/usr/bin/python3", ["/usr/bin/python3", "/usr/lib/mellipi-qt6/native_login.py", *sys.argv[1:]], env)
SCRIPT
chmod 755 "$stage/usr/bin/mellipi-qt6-session"
cat > "$stage/usr/share/wayland-sessions/mellipi-qt6.desktop" <<'DESKTOP'
[Desktop Entry]
Name=Mellipi (Qt 6)
Comment=Experimental native Qt 6 desktop shell
Exec=/usr/bin/mellipi-qt6-session
TryExec=/usr/bin/mellipi-qt6-session
Type=Application
DesktopNames=Orbit;
DESKTOP
cat > "$stage/DEBIAN/control" <<'CONTROL'
Package: mellipi-qt6-session
Version: 0.1.0~preview2
Architecture: amd64
Maintainer: Mellipi OS project
Depends: python3-pyqt6.qtquick, libqt6svg6, mellipi-shell (>= 0.1.21~local12), libqt6quick6 (= 6.4.2+dfsg-4build3), libqt6quickcontrols2-6, qt6-wayland (= 6.4.2-5build3), qml6-module-qtquick, qml6-module-qtquick-controls, qml6-module-qtquick-templates, qml6-module-qtquick-layouts, qml6-module-qtquick-window, qml6-module-qtqml-workerscript
Description: Experimental Qt 6 login option for Mellipi
 Adds a separate login entry and retains the original desktop.
CONTROL
chmod 755 "$stage"
dpkg-deb --root-owner-group -Zgzip --build "$stage" "$output"
