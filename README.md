# Abstract OS

**Abstract** is a lightweight native Wayland desktop for Linux, designed around a compact spine, smooth workspaces, and direct access to everyday controls.

[Website](https://ajavadinezhad.github.io/abstract-os/) · [Installation and updates](docs/update-repository.md) · [Downloads](https://github.com/ajavadinezhad/abstract-os/releases)

The current binary release is **0.1.6**, targeting **Ubuntu 24.04 (noble), amd64, systemd/logind**. Abstract is a desktop environment installed on a Linux base, rather than a separate kernel or distribution. Other distributions and architectures are not yet certified.

## Install

Follow the [signed APT setup instructions](https://ajavadinezhad.github.io/abstract-os/#install) to add the repository, then install `abstract-desktop` on a supported minimal base. Existing installations can update `abstract-shell` through their normal package manager. Updates do not force a logout; native compositor changes activate at the next normal login.

See the [clean-install and recovery guide](docs/clean-install-acceptance.md) before testing a new session.

## Source and releases

This repository contains the reviewed desktop source, build tools, static website, and signed APT archive. Bundled-component notices and matching source archives are available under [`public/sources/0.1.6`](public/sources/0.1.6/manifest.json). Private archive-signing keys, user settings, VM credentials and build caches are excluded.

- [Source build baseline](docs/source-build-baseline.md)
- [Repository maintenance and release process](docs/update-repository.md)
- [Report a reproducible issue](https://github.com/ajavadinezhad/abstract-os/issues)

Hardware compatibility and performance depend on the underlying distribution, graphics driver and applications.
