#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
orbit_source_root="$PWD"
if [[ -d "$PWD/src" ]]; then orbit_source_root="$PWD/src"; fi
# Native sessions already own their shell. A desktop shortcut only opens it.
if [[ -n "${ORBIT_NATIVE_CONTROL:-}" ]]; then
  exec /usr/bin/python3 "$orbit_source_root/orbitctl.py" launcher
fi
# This launcher is retained for explicitly requested X11 development previews.
if [[ -n "${WAYLAND_DISPLAY:-}" || -n "${SWAYSOCK:-}" ]]; then
  echo 'Use the registered Orbit Native login session; this preview is X11 only.' >&2
  exit 1
fi
if [[ ! -x .venv/bin/python ]]; then
  echo 'Qt runtime missing. Set up a venv and install requirements-native.txt.' >&2
  exit 1
fi
if [[ ! -x backend/target/release/orbit-core ]]; then
  echo 'Rust core missing. Build it with ./tools/build-core.sh first.' >&2
  exit 1
fi
export LD_LIBRARY_PATH="$PWD/.runtime/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec .venv/bin/python "$orbit_source_root/supervise.py" "$@"
