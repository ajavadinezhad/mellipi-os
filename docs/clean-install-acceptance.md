# Clean Ubuntu installation acceptance

The supported binary target for this test is Ubuntu24.04/Noble amd64. A passing
host test or nested compositor test is not proof that an otherwise minimal Linux
installation can log in, authenticate and run this desktop. Other distributions
and architectures require their own builds and acceptance.

## Install the supported profile

On Ubuntu 24.04 amd64, install the two release files together with apt. It resolves
the required libraries, login screen, hardware services and applications:

```
sudo apt install ./mellipi-shell_0.1.9_amd64.deb ./mellipi-desktop_0.1.9_all.deb
```

On a machine that already has a desktop/login manager, install only the core
file. The complete profile is an explicit choice of LightDM plus its small
Mellipi greeter configuration. Standard dpkg conffile handling preserves local
edits; the existing main greeter configuration and distro PAM files are not
rewritten. Select Mellipi at the next normal login. Run it as the desktop user,
never through sudo. For a local TTY start, first log in through the distribution's
normal PAM getty and run `exec mellipi-session` when no other graphical session
is active. A working text login remains the recovery path.

`mellipi-session --check` is a read-only installation check, including the actual
Qt layer-shell plugin. `mellipi-session --check-login` additionally checks this
login's private runtime, buses and active local seat. Root installation and SSH
are not graphical login contexts. Neither diagnostic creates a profile or starts
a compositor. Driver metadata and a PAM-file check do not certify actual graphics
scanout or password authentication.

Existing networking is preserved. Ubuntu Server/cloud installations can retain
Netplan/networkd ownership even with NetworkManager installed; Internet access
can work while the desktop correctly reports an unmanaged wired interface. To
move that interface under desktop control, explicitly select NetworkManager in
the existing Netplan configuration, preserving addresses/routes and any
per-interface renderer choices. Use `sudo netplan try --timeout 120` from a
recoverable local console to confirm or automatically roll back the change.
Installing this desktop never silently replaces a working network configuration.

The complete profile includes optional screen-reader, input-method and on-screen
keyboard tools, but they do not start merely because they are installed. Enable
them in Settings when needed. The secure lock provides its own pointer/touch on-screen keyboard for printable
ASCII; physical keyboards retain XKB/Unicode input. It still has no AT-SPI
password control. See [secure unlocking](secure-unlocking.md) for hardware and
output-mapping limits. DDC
brightness still needs a supported monitor and the distribution's I2C access
policy; a VM cannot validate physical display or headset hardware.

## Disposable VM runner

`desktop/tools/qa-clean-install-vm.py` owns a fresh qcow2 overlay and its processes. It
never installs host software, starts a host login manager or acquires a host seat.
Its guest has two virtual CPUs,4096MiB RAM and a24GiB virtual disk. QEMU uses
virtio-vga with guest software rendering; it does not require host virgl or pass
through a host GPU. KVM is selected when accessible; TCG is an explicit slower
fallback. The NoCloud seed is attached as a read-only virtio block device: the minimal cloud kernel may omit SATA/CD drivers. An explicit NoCloud SMBIOS hint makes discovery independent of hypervisor heuristics. SSH is forwarded only to127.0.0.1. QMP and VNC use private Unix sockets.

Run all commands in this VM-runner section from `desktop/` (`cd desktop`
from the repository root). The runner and its guest probes live in
`desktop/tools/`; package paths such as `dist/` are relative to `desktop/`.

Host prerequisites: `qemu-system-x86_64`, `qemu-img`, `genisoimage`, `ssh`,
`ssh-keygen`, `openssl`, `gpgv`, `dpkg-deb`, and the distribution's trusted Ubuntu
cloud-image keyring. Check them without changing the host:

```
python3 tools/qa-clean-install-vm.py check-tools
```

Download the official Ubuntu Minimal Noble image with its detached signed
manifest, or reuse a previously verified local cache:

```
python3 tools/qa-clean-install-vm.py fetch-image --cache-dir .clean-install-cache
```

The runner verifies `SHA256SUMS.gpg` with
`/usr/share/keyrings/ubuntu-cloudimage-keyring.gpg`, then checks the exact image
filename against that signed manifest and hashes the complete image. It refuses
an unsigned manifest, a missing trusted keyring or mismatched content. It does
not import a key downloaded alongside an untrusted image. `--sha256sums`,
`--signature` and `--keyring` allow explicit local paths.

Build the release packages first. Use the SHA256 printed for the verified image
and the actual release filenames in the following command:

```
python3 tools/qa-clean-install-vm.py run \
  --image .clean-install-cache/ubuntu-24.04-minimal-cloudimg-amd64.img \
  --sha256 IMAGE_SHA256 \
  --workdir /tmp/abstract-vm-full-minimal \
  --package dist/mellipi-shell_0.1.9_amd64.deb \
  --package dist/mellipi-desktop_0.1.9_all.deb \
  --profile full --no-install-recommends --start-desktop --keep-running
```

Use a **new empty work directory for each case**. Run cases sequentially on a
low-memory host. The full profile requires both `mellipi-shell` and
`mellipi-desktop`; the core profile requires only `mellipi-shell`.

| Case | Packages | APT behavior |
| --- | --- | --- |
| Core minimum | mellipi-shell | `--no-install-recommends` |
| Core normal | mellipi-shell | normal recommendations |
| Full minimum | mellipi-shell + mellipi-desktop | `--no-install-recommends` |
| Full normal | mellipi-shell + mellipi-desktop | normal recommendations |

The script waits up to10minutes for first boot/cloud-init and20minutes for APT.
Both bounds can be explicitly changed. It uploads packages using its own SSH key,
installs them inside the guest, and runs the uploaded guest probe. Before any QA
helpers are installed in the guest, baseline checks cover every packaged ELF (including the tray helper, portal and private Qt libraries),
rendered Qt SVG, fallback icons, themed Cairo/librsvg lock artwork, required
commands and PAM policy presence. They distinguish optional services from core
requirements.

`--start-desktop` intentionally configures a guest-only tty1 automatic login.
That login passes through the guest's getty/PAM session setup as its normal
`abstract` user, and starts the real DRM compositor. It uses the PAM-provided
user bus when present. A separate `dbus-run-session` is used only when no user bus
exists. This tests TTY session startup, **not** greeter selection or password
entry. The session probe requires a real DRM login, a private runtime directory,
a ready shell, no QML errors and the secure-lock capability. A separate QMP
pixel gate rejects black/cursor-only startup frames; a healthy control socket
alone is insufficient. The baseline also loads the actual Qt layer-shell plugin,
not merely its interface library.

The private work directory contains `report.json`, package/image identities,
`install.log`, `serial.log`, `qemu.log`, an SSH key and `credentials.json`. The
last file holds the disposable VM password and must stay private. Never paste it
into reports. The runner does not print it. `--keep-running` retains only this
owned VM for interactive acceptance; without it the runner stops its VM.

## Interactive VM acceptance

Inspect and operate only the isolated VM with QMP:

```
python3 tools/qa-clean-install-vm.py qmp --workdir /tmp/abstract-vm-full-minimal status
python3 tools/qa-clean-install-vm.py qmp --workdir /tmp/abstract-vm-full-minimal screenshot
python3 tools/qa-clean-install-vm.py qmp --workdir /tmp/abstract-vm-full-minimal key --keys meta_l
```

`screenshot` writes `screen.ppm` inside the private work directory. `key` takes
QEMU qcode names, with chord members separated by hyphens. `password` types the
private generated VM password followed by Enter, without printing its value.
Use it only after confirming the VM's password prompt with a screenshot.
`powerdown` requests shutdown of this VM; it does not touch the host.

Required acceptance beyond automated startup:

1. Open Super and Settings; launch the installed terminal and file manager.
   Check readable fonts, fallback icons, pointer, window controls, clipboard,
   workspace shortcuts and application focus. Confirm settings persist after a
   normal guest logout/login.
2. Trigger Lock through the guest UI. Confirm password input and keyboard-layout
   feedback, rejection of one wrong password, then unlock using the generated
   account password. Record actual compositor locked/unlocked state as well as
   screenshots. PAM-file existence alone does not pass this test.
3. In a separate fresh snapshot, install a supported display manager **inside the
   VM only**, select Mellipi at its greeter, and perform a real password login.
   Start with LightDM; GDM and SDDM are additional compatibility cases. Do not
   claim a tty1 autologin as greeter acceptance.
4. Use Ctrl+Alt+F2 in the VM, sign in normally and confirm a usable recovery TTY.
   Recovery does not assume Xfce or any other desktop. To prevent another
   automatic test login, create `/home/abstract/.abstract-qa-no-start` in the
   guest, then stop only its QA getty/session. The cloud-image SSH channel is a
   separate recovery path.
5. Test reboot, a normal login, package upgrade from a named previous release,
   and package removal/purge in separate snapshots. Check registration files,
   service cleanup and retained private user data. Reinstalling the same version
   is not an upgrade test. Keep the SSH/getty recovery path before removal.
6. Enable Orca/AT-SPI at startup and after login on a supported Qt version. Verify
   actual accessible actions and text. The Cairo lock now has a locker-owned
   pointer/touch keyboard, but no AT-SPI password control. Test actual touch and
   password entry separately; a successful Qt Settings test does not certify
   secure-lock screen-reader access.

The initial JSON report deliberately leaves lock/unlock, accessibility and
lifecycle as **not tested** until their real workflows are exercised. It is not a
blanket pass. VM audio, graphics and synthetic peripherals also do not certify
physical HDMI, headset battery, suspend/resume or mixed-monitor behavior.

## Recorded clean startup acceptance —2026-11-09

The first owned VM exposed a real harness issue: its minimal cloud kernel did
not discover a SATA/CD seed. Its observations were retained. A fresh overlay
with a read-only virtio seed and explicit NoCloud SMBIOS hint completed cloud-init
in54seconds and accepted the generated SSH key.

The full profile0.1.5 then installed on the signed Ubuntu24.04.5 Minimal image
with `--no-install-recommends`:469new packages, zero upgrades/removals,196MB
download and806MB additional disk space. All nine packaged ELF runtimes resolved,
including the XEmbed proxy, private KF/Qt libraries/plugin and portal. Qt SVG,
fallback icons and Cairo/librsvg lock artwork passed. A real VM tty1 PAM session
started the DRM compositor and shell with a private runtime, one output, the
secure-lock capability and no QML errors. Actual QMP pixels then exposed a black
screen: the candidate depended on the layer-shell interface library but omitted
the separate `layer-shell-qt` plugin package. Installing that missing plugin only
in the guest and restarting its empty test session produced the visible taskbar,
desktop icons and wallpaper. This is a prerequisite correction, not an original
clean graphical pass. The mandatory dependency, actual-plugin probe and black-
frame gate must pass on the next fresh candidate.

This recorded result is startup acceptance, not a claim that greeter/password
login, actual lock/unlock, screen-reader behavior, reboot/upgrade/removal or all
four profile cases have passed. Those outcomes must be recorded separately.
The owned run's detailed report is `/tmp/abstract-vm-full-v2/report.json`; it
contains no generated password. The current host desktop was unchanged.

## Fresh corrected full-profile proof —2026-11-09

A separate untouched Minimal-image overlay then installed the frozen corrected
full profile with no recommendations or manual package/service repairs. The
automated run passed actual layer-plugin loading, all nine ELF dependencies,
SVG/icons/lock artwork, a real native DRM login and the QMP pixel gate. Its viewed
startup image shows the taskbar, desktop icons and wallpaper, not merely a ready
control socket.

Before the first diagnostic `pactl` call, PipeWire, PipeWire-Pulse and WirePlumber
were already active from normal desktop startup. The dark greeter configuration,
Adwaita-dark theme and static login wallpaper were installed. Orca, Fcitx5 and
wvkbd-mobintl were available with recommendations disabled. On its4GB virtual
machine, the idle guest reported3378824kB memory available; this is one idle
observation, not a workload benchmark.

Exact package/image hashes, results and scope are recorded in
[the frozen full-minimum certificate](audits/2026-11-09-clean-full-minimum.json).
The core artifact starts `8eb81120…` and the metapackage `c2cc182e…`. A later
clock-format-only package revision is deliberately outside this fresh-bootstrap
certificate and needs its own whole-package upgrade verification. This fresh
guest did not perform the separate password-greeter/lock/lifecycle acceptance
being run in the other owned VM.
