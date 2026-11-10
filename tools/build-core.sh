#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ -x .toolchain/cargo/bin/cargo ]]; then
  export RUSTUP_HOME="$PWD/.toolchain/rustup"
  export CARGO_HOME="$PWD/.toolchain/cargo"
  cargo_bin="$PWD/.toolchain/cargo/bin/cargo"
else
  cargo_bin=cargo
fi
# Mint supplies the SQLite runtime; use its SONAME without compiling a second copy.
if [[ -f /usr/lib/x86_64-linux-gnu/libsqlite3.so.0 ]]; then
  mkdir -p .runtime/sqlite
  ln -sf /usr/lib/x86_64-linux-gnu/libsqlite3.so.0 .runtime/sqlite/libsqlite3.so
  export SQLITE3_LIB_DIR="$PWD/.runtime/sqlite"
fi
exec "$cargo_bin" build --release --locked -j 2 --manifest-path backend/Cargo.toml
