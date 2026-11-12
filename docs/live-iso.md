# Mellipi live USB and installer image

The image is built from a **fresh Ubuntu 24.04 (noble) amd64 minbase** using
Ubuntu's signed package repositories. Mellipi is the only desktop environment. A small Xorg Recovery terminal is also available at sign-in.
It is not a remastered Mint, Xfce, GNOME or Plasma desktop image. LightDM is the
login greeter; the included file manager and other applications do not install
another desktop environment.

The image contains the Linux kernel and firmware, Mellipi, Foot terminal,
Thunar, Mousepad, Epiphany, package management and hardware services, plus the
Calamares graphical installer. Installation copies the packaged filesystem
locally and does not require downloading the desktop again.

## Try and install

1. Download the ISO and its matching `.iso.sha256` file into the same directory,
   then run `sha256sum -c mellipi-0.1.20-noble-amd64.iso.sha256`. The release's
   signed `mellipi-0.1.20-SHA256SUMS` also covers the ISO and all four packages.
2. Use a trusted USB image writer to select the ISO and the intended USB drive.
   Review the drive carefully: writing an image replaces that drive's contents.
3. Boot the USB and choose **Try or install Mellipi**. The live desktop opens
   automatically. It is temporary; changes are lost when the machine restarts.
   Press **Super+Enter** to open the included Foot terminal.
4. Open **Install Mellipi** from the desktop or launcher. Choose language,
   keyboard, target disk/partitioning, user name and password. For manual
   partitioning, use ext4 for the root (`/`) partition. No disk operation
   begins until the summary and final installation confirmation are accepted.
5. Remove the USB when installation is complete and reboot into the installed
   system. The installed account uses the password chosen in the installer.

The live user is created by Ubuntu Casper at boot. No developer account,
password, SSH server, SSH key or private archive-signing key is embedded in the
image. Locking is unavailable in the password-free live session, including
before suspend; an installed user receives the ordinary password-protected
desktop lock defaults. The 0.1.20 builder uses Ubuntu-signed shim, GRUB and kernel.
See [Secure Boot](secure-boot.md) for the installed boot chain, exact-image
acceptance requirements and firmware/third-party-driver limits. The older 0.1.8
ISO remains unsigned and requires Secure Boot disabled.

## Build boundary

`tools/build-live-iso.py` runs **only as root inside the named disposable QEMU
QA guest**. Its guard checks the guest marker, VM type and dedicated work path.
It refuses a workstation and accepts no block-device argument. Do not bypass
that guard or run a host chroot to build an image.

Required guest build tools include `debootstrap`, `squashfs-tools`, `xorriso`,
`grub-pc-bin`, `grub-efi-amd64-bin`, `mtools`, `dosfstools`, `rsync`, `gnupg` and
`ca-certificates`. Kernel/live/installer dependencies are installed into the
fresh target by the builder. A larger build disk and sufficient free space are
needed for the target filesystem, package downloads and compressed image.

After transferring the verified Mellipi `.deb` pair and **public** archive
keyring and sibling `secure-boot-image.py` helper into the guest, run inside that VM:

```sh
sudo python3 build-live-iso.py \
  --version 0.1.20 \
  --workdir /home/abstract/abstract-iso/build \
  --core-deb /path/to/mellipi-shell_0.1.20_amd64.deb \
  --desktop-deb /path/to/mellipi-desktop_0.1.20_all.deb \
  --keyring /path/to/mellipi-archive-keyring.gpg \
  --calamares-partition-module /path/to/reviewed-partition.so \
  --calamares-partition-sha256 SHA256_FROM_REVIEWED_MODULE_REPORT \
  --calamares-partition-provenance /path/to/reviewed-partition.so.json
```

The builder supports `--phase bootstrap`, `install`, and `image` for inspected
retries. It refuses to silently overwrite an existing squashfs or ISO.
`--mirror` and `--security-mirror` may point to a guest-only package cache while
building; package signatures remain enforced. The final image always restores
Ubuntu's official HTTPS sources and rejects leaked build-cache addresses.

Output includes the ISO, its SHA256 checksum and `iso-build-report.json`.
Calamares requires an explicit partitioning choice and final confirmation.
The installer removes Casper and live-only installer components from its
selected target, creates the chosen account, regenerates initramfs and installs
GRUB. The build tool itself never partitions a disk.

### Installer partition module

Noble's Calamares 3.3.5 partition module needs two targeted corrections: use
KPMCore's usable partition-table boundary rather than the physical disk end,
and initialize Ubuntu's encryption-only partition flag. The image builder
requires the reviewed module and its provenance, verifies the exact amd64 ABI,
checksum and geometry regression, and replaces only that live-installer module.
The installed desktop removes Calamares and the live helpers.

`tools/build-calamares-partition.py` builds the module without installing host
packages or touching a disk. Supply pristine upstream 3.3.5 source, the exact
Ubuntu encryption patch from its Debian source archive, and matching Noble
Qt 5.15.13 / KPMCore 23.08.5 development inputs. These can live in extracted
private SDK directories or in a disposable Noble build VM. For example:

```sh
python3 tools/build-calamares-partition.py \
  --source-dir /path/to/calamares-3.3.5 \
  --ubuntu-encryption-patch /path/to/debian/patches/enable-only-present-with-encryption-partitions.patch \
  --calamares-prefix /path/to/extracted-calamares/usr \
  --development-prefix /path/to/noble-development-sdk/usr \
  --qt-prefix /path/to/noble-qt5-sdk/usr \
  --build-dir /path/to/new-private-build \
  --output /path/to/reviewed-partition.so
```

The helper pins the upstream source and Ubuntu patch, applies the two reviewed
patches under `desktop/patches/`, and runs the retained geometry/constructor
fixture against the actual compiled module. It uses an in-memory fake device.
The `.so.json` output records the module digest and patch hashes. Calamares's
upstream and Ubuntu source archives accompany the release's corresponding
sources. This regression does not replace a real UEFI installation test.

## Acceptance and publication

Keep candidate ISOs private until a disposable VM demonstrates:

- BIOS boot and a visible Mellipi desktop;
- UEFI boot tested separately;
- working terminal, installer entry and ordinary application launch;
- GUI installation to a **private virtual disk**, with explicit disk selection;
- reboot from that virtual disk without the ISO, followed by password login;
- open Updates, complete ordinary graphical authentication and reach the package manager;
- lock through the desktop interface, reject a wrong password and unlock with the correct one;
- no other desktop session, developer credentials or private signing material.

A successful ISO creation or an El Torito table is not proof of a successful
boot or installation. Record actual results and limits in the release notes.
Large ISO files belong in release assets or suitable image hosting, not the
GitHub Pages `public/` directory. Keep the package archive and its immutable
released sources unchanged.

## Upstream references

- [Ubuntu Casper manual](https://manpages.ubuntu.com/manpages/noble/en/man7/casper.7.html)
- [Ubuntu Calamares package](https://packages.ubuntu.com/noble/calamares)
- [Calamares 3.3.5 configuration](https://github.com/calamares/calamares/tree/v3.3.5/src/modules)
- [Calamares settings](https://github.com/calamares/calamares/blob/v3.3.5/settings.conf)

The initial configuration was checked against the actual Ubuntu Noble
`calamares` 3.3.5-0ubuntu4 and `casper` 1.498 packages, including their modules,
schemas and initramfs hooks. Package versions and hardware behavior can change;
release acceptance, rather than a presumed configuration, determines support.

The live filesystem uses Zstandard level 6 with one compression worker and a 512 MiB memory limit. This keeps the build bounded and decompression inexpensive on modest PCs. The kernel and installer both support this format.
