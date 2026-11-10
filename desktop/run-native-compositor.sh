#!/usr/bin/env bash
# Development-only nested compositor. Never replaces or logs out the active session.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ -z "${WAYLAND_DISPLAY:-}" && -z "${DISPLAY:-}" ]]; then
  echo 'Run this nested preview from an existing graphical session.' >&2
  exit 1
fi
if [[ ! -x compositor/target/debug/orbit-compositor ]]; then
  echo 'Build first: ./tools/build-native-compositor.sh' >&2
  exit 1
fi
export LD_LIBRARY_PATH="$PWD/.native-drm-runtime/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export ORBIT_NATIVE_PROFILE="${ORBIT_NATIVE_PROFILE:-economy}"
if [[ "${1:-}" == --demo ]]; then
  exec .venv/bin/python tools/preview-native-workspaces.py
fi
if [[ -x .native-runtime/bin/orbit-compositor ]]; then
  exec .native-runtime/bin/orbit-compositor "$@"
fi
exec compositor/target/debug/orbit-compositor "$@"
