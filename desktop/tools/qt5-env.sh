#!/usr/bin/env bash
# Native shell only: never export private Qt paths to launched applications.
export ORBIT_QT=5
if [[ "${ORBIT_WAYLAND_RUNTIME:-private}" == private ]]; then
  export PYTHONPATH="$orbit_root/.wayland-runtime/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
  export QT_PLUGIN_PATH="$orbit_root/.wayland-runtime/usr/lib/x86_64-linux-gnu/qt5/plugins"
  export QML2_IMPORT_PATH="$orbit_root/.wayland-runtime/usr/lib/x86_64-linux-gnu/qt5/qml"
  export LD_LIBRARY_PATH="$orbit_root/.wayland-runtime/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  export QT_QUICK_CONTROLS_STYLE="$orbit_root/.wayland-runtime/usr/lib/x86_64-linux-gnu/qt5/qml/QtQuick/Controls.2"
fi

# Scope the compatibility module to this Qt process and recheck after Qt updates.
# Private fallback runtimes discard any inherited system-only compatibility path.
if [[ -f "$orbit_source_root/qt5_a11y_runtime.py" ]]; then
  orbit_a11y_library_path="$(/usr/bin/python3 "$orbit_source_root/qt5_a11y_runtime.py" --library-path)"
  if [[ -n "$orbit_a11y_library_path" ]]; then
    export LD_LIBRARY_PATH="$orbit_a11y_library_path"
  else
    unset LD_LIBRARY_PATH
  fi
  unset orbit_a11y_library_path
fi
