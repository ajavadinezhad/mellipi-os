#!/usr/bin/env bash
# Sway is retained solely as an isolated development/QA parent compositor.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
orbit_source_root="$PWD"
if [[ -d "$PWD/src" ]]; then orbit_source_root="$PWD/src"; fi
source tools/wayland-env.sh
orbit_is_test=false
for orbit_argument in "$@"; do
  if [[ "$orbit_argument" == --nested || "$orbit_argument" == --headless ]]; then orbit_is_test=true;fi
  if [[ "$orbit_argument" == --check ]]; then exec /usr/bin/python3 "$orbit_source_root/run-wayland-session.py" "$@";fi
done
if [[ "$orbit_is_test" == false ]]; then
  echo 'The old Orbit/Sway login session is retired. Use ./run-native-session.sh.' >&2
  exit 1
fi
# Never inherit a running native session's control channel into a Sway fixture.
unset ORBIT_NATIVE_CONTROL ORBIT_NATIVE_NESTED_BUS
exec dbus-run-session -- /usr/bin/python3 "$orbit_source_root/run-wayland-session.py" "$@"
