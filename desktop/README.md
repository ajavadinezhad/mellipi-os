# Abstract desktop source

This directory contains the desktop shell, native Wayland compositor, services, themes and application build tools. The top-level [project README](../README.md) covers installation and downloads; shared technical guides live in [docs](../docs).

Run application tools **from this directory**, so their relative runtime and configuration paths stay together:

```sh
cd desktop
python3 tools/build-desktop-package.py --help
```

A source checkout does not include the prebuilt private runtime binaries. Follow the [source-build baseline](../docs/source-build-baseline.md) before building a package. On the validated build host, build the native components with:

```sh
sh tools/build-core.sh
sh tools/build-native-compositor.sh
```

After preparing the locker, portal and other required runtimes described in that guide:

```sh
python3 tools/build-desktop-package.py --with-desktop
```

The package builder stages files in temporary directories; it does not install packages or stop a desktop. `run-native-session.sh` starts a real desktop session and should only be used from the intended login environment, not inside an existing desktop terminal. Use the packaged login entry for ordinary use.

Directory guide:

- `native/`: QML interface, assets and workspace surfaces.
- `compositor/`: Rust Wayland compositor and vendored Smithay changes.
- `backend/`: Rust application-data core.
- `session/`: startup, preflight and session configuration.
- `themes/`, `patches/`, `packaging/`: appearance data, runtime patches and package assets.
- `tools/`: application builds and isolated QA utilities. Public-repository and release tools remain in the repository’s top-level `tools/`.
