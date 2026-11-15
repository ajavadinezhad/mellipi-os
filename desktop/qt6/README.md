# Mellipi Qt 6 experiment

This is a compiled Qt Quick window used to verify the runtime and first-frame
instrumentation. It is not installed as a session, and does not change Mellipi
preferences. A second mode provides a real taskbar and launcher in nested Wayland.

Build with Qt 6 Base and Declarative development packages and the Qt Quick,
Controls, Templates, Layouts, Window and QtQml WorkerScript runtime modules:

```sh
cmake -S desktop/qt6 -B /tmp/mellipi-qt6 -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/mellipi-qt6 -j2
ctest --test-dir /tmp/mellipi-qt6 --output-on-failure
```

For the nested shell, build KDE's layer-shell plugin in a private prefix:
`desktop/qt6/build-layer-shell.sh /tmp/mellipi-qt6-layer-work`. It needs ECM,
Qt 6 Wayland/Base/Declarative private development headers, and Wayland
development tools. Configure Mellipi with
`-DCMAKE_PREFIX_PATH=/tmp/mellipi-qt6-layer-work/install`.

Set `LD_LIBRARY_PATH` to the private prefix's library directory and
`QT_PLUGIN_PATH` to its plugins directory. The private library path matters
because this version shares a library soname with the distro's Qt 5 build.
Run `python3 desktop/qt6/check-nested.py /path/to/mellipi-qt6` to verify the
bottom work area and click/Escape behavior in a disposable compositor.

The launcher currently has a fixed list of four installed apps. The shell is
nested-only; a production login still needs secure lock, logout, and recovery
integration before it can replace Qt 5.

For the main Mellipi package, use the existing Python/QML desktop and the
matching Qt 6 plugin rather than the C++ experiment above. After building the
plugin, pass its library directory to the package builder:

```sh
export MELLIPI_QT6_RUNTIME=/tmp/mellipi-qt6-layer-work/install/lib/x86_64-linux-gnu
python3 desktop/tools/build-desktop-package.py --version 0.1.21~qt6.2 --with-desktop
```

The regular package owns the Mellipi (Qt 6) login entry and supersedes the
separate preview package. It does not fall back to the Qt 5 desktop.
Run `mellipi-session --check` and then
`dbus-run-session -- /usr/bin/python3 desktop/qt6/check-nested.py --installed`
to verify the installation and private Wayland startup before a real login.
