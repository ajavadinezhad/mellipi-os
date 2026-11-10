#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
export RUSTUP_HOME="$PWD/.toolchain/rustup"
export CARGO_HOME="$PWD/.toolchain/cargo"
# Local development headers/runtime only; no apt installation or global linker edit.
if [[ -d "$PWD/.native-drm-runtime/usr/lib/x86_64-linux-gnu/pkgconfig" ]]; then
  export PKG_CONFIG_PATH="$PWD/.native-drm-runtime/usr/lib/x86_64-linux-gnu/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
  export LD_LIBRARY_PATH="$PWD/.native-drm-runtime/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
nice -n 15 .toolchain/cargo/bin/cargo build --locked -j 1 --manifest-path compositor/Cargo.toml "$@"

orbit_build_profile=debug
for orbit_build_argument in "$@"; do
  if [[ "$orbit_build_argument" == --release ]]; then orbit_build_profile=release; fi
done
mkdir -p .native-runtime/bin
orbit_binary_temp=$(mktemp .native-runtime/bin/.orbit-compositor.XXXXXX)
trap 'rm -f "$orbit_binary_temp"' EXIT
install -m 755 "compositor/target/$orbit_build_profile/orbit-compositor" "$orbit_binary_temp"
if command -v strip >/dev/null 2>&1; then strip "$orbit_binary_temp"; fi
mv -f -- "$orbit_binary_temp" .native-runtime/bin/orbit-compositor
