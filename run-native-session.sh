#!/usr/bin/env bash
# Independent native login entry. Existing Orbit/Sway/Mint sessions stay available.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
exec /usr/bin/python3 session/native_session.py "$@"
