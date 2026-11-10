#!/usr/bin/env bash
# Session-local environment; system Mint packages are preferred over the dev fallback.
orbit_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
orbit_runtime="${ORBIT_WAYLAND_RUNTIME:-auto}"
if [[ "$orbit_runtime" == auto ]]; then
  if [[ -x /usr/bin/sway ]] && /usr/bin/python3 -c 'from PyQt5 import QtCore,QtQuick,QtWidgets; import gi,ctypes;ctypes.CDLL("libLayerShellQtInterface.so.5")' >/dev/null 2>&1; then
    orbit_runtime=system
  else
    orbit_runtime=private
  fi
fi
if [[ "$orbit_runtime" != system && "$orbit_runtime" != private ]]; then
  echo 'ORBIT_WAYLAND_RUNTIME must be auto, system or private' >&2
  return 1
fi
export ORBIT_WAYLAND_RUNTIME="$orbit_runtime"
if [[ "$orbit_runtime" == private ]]; then
  export PATH="$orbit_root/.wayland-runtime/usr/bin:$PATH"
  export LD_LIBRARY_PATH="$orbit_root/.wayland-runtime/compositor-lib:$orbit_root/.runtime/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  export XDG_DATA_DIRS="$orbit_root/.wayland-runtime/usr/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
  export XDG_DESKTOP_PORTAL_DIR="$orbit_root/.wayland-runtime/usr/share/xdg-desktop-portal/portals"
else
  # Explicitly selecting system after a private test must not mix Qt libraries.
  orbit_prune_private() {
    local orbit_key="$1" orbit_piece orbit_joined
    local -a orbit_parts=() orbit_kept=()
    IFS=: read -r -a orbit_parts <<< "${!orbit_key-}"
    for orbit_piece in "${orbit_parts[@]}"; do
      if [[ -n "$orbit_piece" && "$orbit_piece" != "$orbit_root/.wayland-runtime"* && "$orbit_piece" != "$orbit_root/.runtime"* ]]; then orbit_kept+=("$orbit_piece");fi
    done
    if [[ ${#orbit_kept[@]} -gt 0 ]]; then
      orbit_joined="$(IFS=:;printf '%s' "${orbit_kept[*]}")";printf -v "$orbit_key" '%s' "$orbit_joined";export "$orbit_key"
    else unset "$orbit_key";fi
  }
  for orbit_key in PATH LD_LIBRARY_PATH PYTHONPATH QT_PLUGIN_PATH QML2_IMPORT_PATH XDG_DATA_DIRS; do orbit_prune_private "$orbit_key";done
  if [[ "${QT_QUICK_CONTROLS_STYLE:-}" == "$orbit_root/.wayland-runtime"* ]]; then unset QT_QUICK_CONTROLS_STYLE;fi
  unset -f orbit_prune_private
  # This variable is a portal test override and bypasses normal config lookup.
  unset XDG_DESKTOP_PORTAL_DIR
fi
export XDG_CONFIG_DIRS="$orbit_root/session/configs:${XDG_CONFIG_DIRS:-/etc/xdg}"
