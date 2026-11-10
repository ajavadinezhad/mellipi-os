#!/usr/bin/env bash
# Independent native login entry. Existing Orbit/Sway/Mint sessions stay available.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
orbit_source_root="$PWD"
if [[ -d "$PWD/src" ]]; then orbit_source_root="$PWD/src"; fi
exec /usr/bin/python3 "$orbit_source_root/session/native_session.py" "$@"
