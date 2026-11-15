# Mellipi desktop source

This directory contains the desktop shell, native Wayland compositor, services, themes and application build tools. The top-level [project README](../README.md) covers installation and downloads; shared technical guides live in [docs](../docs).

Run application tools **from this directory**, so their relative runtime and configuration paths stay together:

```sh
cd desktop
python3 tools/build-desktop-package.py --help
```

A source checkout does not include the prebuilt private runtime binaries. Follow the [source-build baseline](../docs/source-build-baseline.md) before building a package. On the validated build host, build the native components with:

```sh
./tools/build-core.sh
./tools/build-native-compositor.sh --release --features drm
```

After preparing the locker, portal and other required runtimes described in that guide:

```sh
python3 tools/build-desktop-package.py --with-desktop
```

The package builder stages files in temporary directories; it does not install packages or stop a desktop. `run-native-session.sh` starts a real desktop session and should only be used from the intended login environment, not inside an existing desktop terminal. Use the packaged login entry for ordinary use.

Run the isolated application unit checks from this directory with the source modules on Python’s import path:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests
```

Source launchers resolve `src/` automatically. Packaged installations keep their stable program layout under `/usr/lib/abstract`; this repository change does not require moving installed files.

Open **Mellipi Software** from Super or use **Settings → System tools → Tools → Install applications**. Search can include system APT packages, apps from configured Flatpak remotes such as Flathub, and the Snap Store on systems with snapd. Software shows the source and installation scope before asking you to confirm. System updates still use the distribution's update manager.

The native app suite includes **Photos**, **PDF Viewer**, **Media**, and **Disks**. Files can create ZIP archives and extract ZIP or TAR archives into a new folder. Disks lists and mounts volumes; formatting and writing images require selecting a removable USB device and confirming the operation. Media exposes playback controls to the taskbar through MPRIS.

The Qt apps share a live appearance layer and title bar. Settings and the VTE-based Terminal use the same palette and window-control artwork through their existing toolkits.

The installer image ships one everyday app where Mellipi already provides a replacement. The ISO builder checks for competing packages in reused build roots and rejects leftovers before packaging. Recovery uses the VTE terminal engine in a minimal Xorg session. The distribution update backend stays accessible through the desktop's Updates action without a separate launcher entry on the image. This build policy does not uninstall apps from existing systems.

Directory guide:

- `native/`: QML interface, assets and workspace surfaces.
- `compositor/`: Rust Wayland compositor and vendored Smithay changes.
- `backend/`: Rust application-data core.
- `src/`: Python application modules and entrypoints.
- `src/session/`: startup, preflight and session configuration.
- `themes/`, `patches/`, `packaging/`: appearance data, runtime patches and package assets.
- `tools/`: application builds and isolated QA utilities. Public-repository and release tools remain in the repository’s top-level `tools/`.

Mellipi includes a local Text Editor, Calculator and Calendar. In Super, type
an expression and press Enter to copy its result. Open Calendar from the
taskbar clock to import local .ics files, including simple daily and weekly
repeats. Calendar reports unsupported recurrence rules and exceptions. Photos
accepts a pasted screenshot and exports edits as a PNG copy.

The taskbar usage icon opens **System Monitor**. It shows CPU, RAM, and
processes, and pauses sampling when minimized. In **Files**, use the menu’s
**Analyze Storage** action to see what takes up space in a folder.
**Calendar → Clocks** has a timer, one-shot alarm, and stopwatch; leave Calendar
open (it can be minimized) for alerts. **Sound Recorder** lets you pick a
microphone and saves WAV files in Music/Recordings. In **PDF Viewer**, use
highlight or note, then **Save annotated copy** to keep the original unchanged.

The optional browser is built with `build-desktop-package.py --with-browser`.
It uses the distribution's Qt WebEngine and leaves your default browser alone.
Its engine updates come from the distribution. The standalone ISO includes
Mellipi Browser as its only default browser; the shell package does not
require it on an existing Linux installation.
