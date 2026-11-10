#!/usr/bin/env bash
# Retired user-facing session; keep Sway only as an isolated QA dependency.
set -euo pipefail
printf '%s\n' 'The old Orbit/Sway login session has been retired.' \
 'Use tools/install-native-session.sh for the native Orbit session.' \
 'Private --headless/--nested Sway QA remains available; Mint/Xfce is unchanged.' >&2
exit 1
