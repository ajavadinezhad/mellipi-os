#!/usr/bin/env bash
set -euo pipefail
if [[ "${ORBIT_NESTED:-}" != 1 ]]; then
  echo "The old Orbit/Sway shell launcher is retired. Use run-native-session.sh." >&2
  exit 1
fi
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
source tools/wayland-env.sh
source tools/qt5-env.sh
export QT_QPA_PLATFORM=wayland
export QT_WAYLAND_SHELL_INTEGRATION=layer-shell
if [[ "$ORBIT_WAYLAND_RUNTIME" == system ]]; then
  exec /usr/bin/python3 "$PWD/native_app.py" "$@"
else
  exec .venv/bin/python "$PWD/native_app.py" "$@"
fi
