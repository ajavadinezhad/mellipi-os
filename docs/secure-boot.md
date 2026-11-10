# Signed installer boot chain

The 0.1.9 image builder produces a **signed Ubuntu EFI chain** by
default. It uses Ubuntu's `shim-signed`, `grub-efi-amd64-signed` and signed
distribution kernel, obtained through the distribution's signed APT archive.
No Mellipi private key, Machine Owner Key, firmware enrollment or validation
disable switch is included. The archive-signing key is unrelated to UEFI trust.

This build capability is not, by itself, a supported-hardware claim. Record the
exact ISO digest, firmware and actual guest SecureBoot variable for each passed
boot. The existing 0.1.8 published ISO remains unsigned and unsupported with
Secure Boot enabled; its bytes and signatures are unchanged.

## Build and installed-system behavior

Copy `tools/secure-boot-image.py` beside `build-live-iso.py` in the named
disposable build guest. The usual guarded builder creates a private unsigned
intermediate, then installs a signed shim/CD-GRUB/MokManager EFI FAT partition
using an appended GPT partition. The independently working BIOS boot image is
retained. Structural PE signature checks stop the build for missing/unsigned
EFI components or an unsigned kernel. These checks do **not** certify firmware
trust, revocation policy or end-to-end boot; that is the acceptance test below.

The Calamares installer invokes a narrow helper inside its selected target. On
UEFI it requests `grub-install --uefi-secure-boot` without Calamares's `--force`,
using the technical `EFI/ubuntu` path expected by unmodified signed Ubuntu GRUB.
Normal Ubuntu GRUB/shim package updates maintain that path. The fallback
`EFI/BOOT/bootx64.efi` starts signed shim, with signed GRUB and MokManager beside
it. Calamares's direct-GRUB fallback copy is disabled. The firmware boot entry
may use the underlying Ubuntu identifier; Mellipi remains the installed desktop.
BIOS installations retain the usual selected-disk GRUB installation.
The install-only helper is removed from the target after the bootloader job
succeeds; future bootloader maintenance belongs to Ubuntu's package scripts.

`--unsigned-efi` is an explicit development-only escape for the **image build**.
It never disables firmware validation and its report identifies an unsupported
unsigned image. Do not publish it as Secure Boot capable.

## Acceptance

Use only the owned VM harness, with no host disks or firmware changes:

```sh
python3 tools/qa-live-iso.py start \
  --iso /path/to/candidate.iso --sha256 FULL_REVIEWED_SHA256 \
  --workdir /tmp/abstract-live-secure-candidate \
  --firmware uefi --media usb --secure-boot
```

The harness uses private Microsoft-enrolled OVMF variables, SMM and protected
pflash. Inside the guest verify `mokutil --sb-state` and, independently, the
SecureBoot/SetupMode EFI variables. SecureBoot must be 1 and SetupMode 0. Kernel
lockdown state is useful additional evidence. A visible desktop alone is not
proof that Secure Boot enforcement was enabled.

Required gates:

1. The previous unsigned 0.1.8 image is rejected by the same firmware policy.
2. The exact signed candidate boots, reports enforcement enabled and reaches a
   working Mellipi desktop and terminal.
3. Complete graphical installation onto a private disk; detach the ISO and
   boot that disk with enforcement still enabled. Verify login and enforcement
   again. A live-USB pass does not certify the installed system.
4. Test BIOS boot independently after the hybrid image-layout change.
5. Record kernel/shim/GRUB versions and digests with firmware trust/revocation
   state. Firmware without Microsoft's third-party UEFI CA, different DBX/SBAT
   policy or additional unsigned kernel modules needs separate acceptance.

The initramfs and external GRUB configuration follow Ubuntu's ordinary boot
model. This does not provide a verified root filesystem, measured-boot/TPM
attestation, full-disk encryption certification or unrestricted unsigned DKMS
driver support. No bypass is suggested when firmware rejects a component.

References: [Ubuntu Secure Boot](https://documentation.ubuntu.com/security/security-features/platform-protections/secure-boot/),
[Ubuntu UEFI model](https://wiki.ubuntu.com/UEFI/SecureBoot),
[xorriso hybrid-image options](https://www.gnu.org/software/xorriso/man_1_xorrisofs.html).
