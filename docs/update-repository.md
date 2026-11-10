# Abstract package updates and GitHub Pages

Abstract uses APT's normal signature verification and the installed package
manager. There is no resident Abstract update daemon. The current binary target
is **Ubuntu 24.04 (noble), amd64, systemd/logind**. Other distributions and
architectures need their own builds and acceptance checks.

Canonical publication:

- Project: <https://github.com/ajavadinezhad/abstract-os>
- Website: <https://ajavadinezhad.github.io/abstract-os/>
- APT base: <https://ajavadinezhad.github.io/abstract-os/apt>
- Full signing fingerprint: `7D0FC30A9F2B9957B2970E3BB6B1D6FE6A4682AF`

These addresses describe the configured publication target. A successful remote
Pages deployment and HTTPS APT check establish whether they are live; merely
building local files does not publish them.

## Enable updates

Download and inspect the enrollment helper linked on the website, then run:

```sh
sudo sh install-update-source.sh \
  --url https://ajavadinezhad.github.io/abstract-os/apt \
  --fingerprint 7D0FC30A9F2B9957B2970E3BB6B1D6FE6A4682AF
```

The helper checks the supported OS/architecture, downloads the public key,
checks its complete fingerprint and uses a dedicated `Signed-By` keyring. It
writes only Abstract's source/key files and refreshes package lists. It does
not use `apt-key`, trust unsigned metadata, replace Ubuntu sources or install
another desktop profile implicitly. Then use your normal package manager:

```sh
sudo apt update
sudo apt install abstract-shell
```

For a fresh supported base, opt into the complete greeter/applications profile:

```sh
sudo apt install abstract-desktop
```

Installing the core does not restart the compositor or log you out. Keep apps
open while updating; activate session-level code at the next normal login.
A new version must have a new Debian package version; never replace a released
`.deb` with different bytes under the same name/version.

## Prepare a release locally

Keep the signing home **outside** the source tree and publication directory.
The deployment workflow receives no private key and cannot sign new updates.
Back up the private key and revocation certificate securely outside GitHub.

Build and verify the package pair first. Stage only the static website's named
public files, the enrollment helper and the public APT archive:

```sh
mkdir -p public
cp website/index.html website/style.css website/site.js \
   website/site-config.json website/favicon.svg public/
python3 tools/build-apt-repository.py \
  --output public/apt \
  --packages dist/abstract-shell_0.1.6_amd64.deb \
             dist/abstract-desktop_0.1.6_all.deb \
  --gnupg-home /path/outside-repository/abstract-release-signing \
  --signing-key 7D0FC30A9F2B9957B2970E3BB6B1D6FE6A4682AF \
  --suite noble --valid-days 90
cp tools/install-update-source.sh public/apt/install-update-source.sh
```

Preserve existing `public/apt/pool` files when adding a release so installed
clients and older indexes can still fetch their referenced packages. The
builder rejects a changed package at an existing immutable path. Keep at least
the previous working release available while validating an update.

Stage the matching source material too:

```sh
python3 tools/build-public-sources.py \
  --output public/sources/0.1.6 \
  --cache /path/outside-repository/abstract-source-cache \
  --version 0.1.6 --fetch
```

This creates an explicit project-source snapshot (including modified Smithay,
patches and build scripts), exact-version Ubuntu source archives for bundled
Qt/KF5/tray components, pinned Qt compatibility inputs, locker/portal source,
and checksum-verified Rust crate sources from the lockfiles. Its manifest and
`SHA256SUMS` identify the staged source. Upstream notices remain in the bundled
runtime directories. Do not assign a license to Abstract's own files merely
because an upstream dependency uses that license; project licensing is a
separate maintainer choice.

Do not upload the live developer directory. In particular exclude `data/`,
`.venv/`, toolchains, private signing homes, VM disks and cloud-init credentials,
logs, build outputs, runtime sockets, local screenshots and user settings.
The source helper uses an explicit source allowlist, not a recursive copy of
the working directory.

## Publish

Configure this repository's **Settings → Pages → Source → GitHub Actions**.
The `.github/workflows/pages.yml` workflow is manual (`workflow_dispatch`) and
runs only from the default branch. It validates the staged `public/` boundary,
checks the pinned public-key fingerprint, verifies both release signatures,
and deploys only that directory. The `github-pages` environment can require
maintainer review without giving the workflow a signing key. Its deploy job
has Pages/OIDC permissions; other jobs only read repository contents.

Use the Actions page to run **Publish Abstract website and signed APT archive**
after reviewing the commit. Wait for the deployment result; check the actual
HTTPS website and APT endpoint. In an isolated APT state directory or a test VM,
verify a normal `apt update`, candidate version and download/install with the
scoped keyring before enabling the source on a daily-use machine. A missing or
bad signature, wrong key, expired metadata or modified package must fail rather
than falling back to unauthenticated installation.

GitHub documents a 1 GB published-site limit, a soft 100 GB/month bandwidth
limit and a ten-minute deployment timeout. The site/archive should stay below
the workflow's conservative 900 MB budget. As the archive grows, move large
sources/releases to durable release assets or appropriate package hosting;
preserve the signed APT metadata and immutable package URLs. [GitHub Pages
limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits).
The workflow follows GitHub's supported artifact deployment process. [Custom
Pages workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

## Maintenance and recovery

`Release` metadata expires after **90 days** by default. Publish fresh signed
metadata before it expires, even when the package versions have not changed.
An expired archive should make APT reject its stale indexes; do not tell users
to disable `Check-Valid-Until`. Also track signing-key expiry independently.

For a key rotation, publish the new fingerprint through the existing trusted
release channel, distribute an updated scoped keyring before signing solely
with the new key, and retain a tested recovery path. Never silently trust a
replacement key downloaded from the same failing endpoint.

To disable Abstract updates, remove only the source/key files created by the
enrollment helper. This leaves installed Abstract packages and Ubuntu's own
sources intact. To roll back a bad release, select a retained known-good
version through APT and test it; a repository rollback alone does not downgrade
already installed packages. Keep Mint/Xfce or a working TTY recovery option
while testing session changes.
