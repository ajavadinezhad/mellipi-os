# Abstract OS

**Abstract** is a lightweight native Wayland desktop for Linux, designed around a compact spine, smooth workspaces and direct access to everyday controls.

[Website](https://ajavadinezhad.github.io/abstract-os/) · [Install and update](docs/update-repository.md) · [Downloads](https://github.com/ajavadinezhad/abstract-os/releases) · [Issues](https://github.com/ajavadinezhad/abstract-os/issues)

The current binary release is **0.1.7**, targeting **Ubuntu 24.04 (noble), amd64, systemd/logind**. Abstract installs on a Linux base; other distributions and architectures are not yet certified. Hardware compatibility and performance depend on the distribution, driver and applications.

## Install

The [live USB installer](docs/live-iso.md) combines a minimal Ubuntu base with Abstract as its only desktop, plus a terminal and essential applications. The current image requires Secure Boot to be disabled. Download images and their checksums from [GitHub Releases](https://github.com/ajavadinezhad/abstract-os/releases).

Follow the [signed APT setup](https://ajavadinezhad.github.io/abstract-os/#install), then install `abstract-desktop` on a supported minimal base. Existing desktops can install or update only `abstract-shell`. Updates do not force a logout; compositor changes activate at the next normal login. Read the [clean-install and recovery guide](docs/clean-install-acceptance.md) before trying a new session.

## Repository layout

```text
desktop/   Desktop source (src/), compositor, themes, packaging and app build/QA tools
tools/     Repository, source-publication and release/deployment tools
tests/     Release-tool tests
docs/      Build, installation, recovery and maintainer guides
website/   Editable static website source
public/    Reviewed deployment output: website, signed APT archive and release sources
.github/   GitHub Actions workflows
```

For application builds and tests, start in [`desktop/`](desktop/README.md) and follow the [source-build baseline](docs/source-build-baseline.md). Run release and publication commands from the repository root using `tools/`; see the [release process](docs/update-repository.md).

`website/` is the editable site; `public/` is the explicit deployment boundary. Do not deploy the working tree or put private signing keys, user data, VM credentials or build caches there. Bundled-component notices and matching release sources are listed in the [0.1.7 source manifest](public/sources/0.1.7/manifest.json). Earlier release archives remain unchanged when the working source layout changes.
