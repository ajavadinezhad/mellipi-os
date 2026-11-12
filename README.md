# Mellipi OS

**Mellipi** is a lightweight native Wayland desktop for Linux, designed around a compact spine, smooth workspaces and direct access to everyday controls.

[Website](https://ajavadinezhad.github.io/mellipi-os/) · [Install and update](docs/update-repository.md) · [Downloads](https://github.com/ajavadinezhad/mellipi-os/releases) · [Issues](https://github.com/ajavadinezhad/mellipi-os/issues)

The current binary release is **0.1.20**, targeting **Ubuntu 24.04 (noble), amd64, systemd/logind**. Mellipi installs on a Linux base; other distributions and architectures are not yet certified. Hardware compatibility and performance depend on the distribution, driver and applications.

## Install

The [live USB installer](docs/live-iso.md) combines a minimal Ubuntu base with Mellipi as its only desktop, plus a terminal and essential applications. The 0.1.20 image uses Ubuntu-signed shim, GRUB and kernel; firmware trust and hardware limits are documented in [Secure Boot](docs/secure-boot.md). Download images and their checksums from [GitHub Releases](https://github.com/ajavadinezhad/mellipi-os/releases).

Follow the [signed APT setup](https://ajavadinezhad.github.io/mellipi-os/#install), then install `mellipi-desktop` on a supported minimal base. Existing desktops can install or update only `mellipi-shell`. Updates do not force a logout; compositor changes activate at the next normal login. Read the [clean-install and recovery guide](docs/clean-install-acceptance.md) before trying a new session.

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

`website/` is the editable site; `public/` is the explicit deployment boundary. Do not deploy the working tree or put private signing keys, user data, VM credentials or build caches there. Bundled-component notices and matching release sources are listed in the [0.1.20 source manifest](public/sources/0.1.20/manifest.json). Earlier release archives remain unchanged when the working source layout changes.

## Rename compatibility

Mellipi was previously released as Abstract. Version 0.1.8 introduces the
`mellipi-shell` and `mellipi-desktop` packages and `mellipi-session` / `mellipictl`
commands. Small transitional packages preserve the signed upgrade path.
Existing private XDG state, login-entry IDs, policy IDs and the installed runtime
directory retain their legacy identifiers so settings, saved layouts and running
applications survive the rename. Their visible names are Mellipi. Published
0.1.7 packages, source archives and signatures remain unchanged.


## Recovery and system essentials

Version 0.1.9 adds native Users/passwords and Date/time pages, explicit file
and settings backups, a saved working-version recovery helper, and a small
Mellipi Recovery login option independent of the native compositor. Find these
under Settings → System tools, or search Super for Users, Date and time, or
Backups and recovery. Backup tools and file pickers start only on demand.

See [backups and recovery](docs/backups-and-recovery.md),
[system administration](docs/system-administration.md),
[secure unlocking and accessibility limits](docs/secure-unlocking.md), and
[hardware validation](docs/hardware-validation.md). The signed installer chain
and its acceptance boundary are described in [Secure Boot](docs/secure-boot.md).
