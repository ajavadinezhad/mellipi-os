#!/usr/bin/env bash
# Qt 6 shell for the standalone compositor; never invokes XFCE panel supervision.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
orbit_source_root="$PWD"
if [[ -d "$PWD/src" ]]; then orbit_source_root="$PWD/src"; fi
if [[ -z "${ORBIT_NATIVE_CONTROL:-}" || -z "${WAYLAND_DISPLAY:-}" ]]; then
  echo 'Native shell requires its compositor control socket and Wayland display.' >&2
  exit 1
fi
export ORBIT_WAYLAND_RUNTIME=system
source tools/wayland-env.sh
orbit_qt6_root="${MELLIPI_QT6_RUNTIME:-$PWD/.qt6-layer-shell}"
export MELLIPI_QT6_RUNTIME="$orbit_qt6_root"
export LD_LIBRARY_PATH="$orbit_qt6_root${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export QT_PLUGIN_PATH="$orbit_qt6_root/plugins"
export MELLIPI_QT6_LAYER_LIBRARY="$orbit_qt6_root/libLayerShellQtInterface.so.5"
export ORBIT_QT=6
export QT_QPA_PLATFORM=wayland
export QT_WAYLAND_SHELL_INTEGRATION=layer-shell
export QT_QUICK_BACKEND="${QT_QUICK_BACKEND:-software}"
exec /usr/bin/python3 "$orbit_source_root/native_app.py" "$@"
