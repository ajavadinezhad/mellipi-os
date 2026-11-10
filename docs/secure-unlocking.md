# Secure unlocking

The Mellipi locker owns its password field and optional on-screen keyboard.
Choose **Keyboard** on the lock screen, then use a mouse or touchscreen. Shift,
Symbols, Back, Space and Unlock provide all printable ASCII characters. A physical
keyboard continues to support the configured XKB layout and Unicode input.
The on-screen layout is a fixed US layout; its printed key labels are the text it
enters. It does not change the user's configured keyboard layout.

The keyboard is drawn in the existing session-lock client. It does not start an
external keyboard or give another application permission to inject lock input.
Clicks and completed taps go through upstream swaylock's existing key handler.
Drag, cancelled and additional concurrent touch sequences do not activate keys.
Password storage, clearing, authentication IPC and PAM remain unchanged upstream
sources and are hash-checked during every local locker build. Neither keyboard
rendering nor metadata collection reads password bytes.

Native touch uses the first mapped output, matching the current absolute-pointer
policy. Per-device output assignment/calibration is not yet available. Lock,
unlock, output removal, input-device removal and VT loss cancel old touch streams
so a contact cannot cross into another security domain. No unlocked application
receives lock touch events. Display and touch changes require the updated native
compositor at the next ordinary login; installing packages never logs users out.

The password control is still a Cairo control, not an AT-SPI object. Full screen
reader access to the secure password field is **not implemented**. Do not claim
Orca/AT-SPI certification based on the pointer keyboard or ordinary Settings
accessibility. Touchscreen hardware, output mapping and actual password entry
must also be exercised on target devices before claiming hardware support.

## Validation

- `python3 desktop/tools/check-lock-keyboard.py`: compiles the real keyboard
  geometry, complete printable-ASCII mapping, cancellation/multitouch state and
  four Cairo presentations without a Wayland display, password or PAM process.
- `python3 desktop/tools/prepare-screen-lock.py --offline`: applies both reviewed
  patches to pinned upstream 1.8.6, verifies protected source hashes, builds PAM,
  and runs the rendering/status/keyboard regressions. It never installs a host
  PAM file or binary.
- `ORBIT_QT=5 python3 desktop/tools/qa-lock-keyboard-native.py`: owned headless
  Sway plus nested native compositor, actual locker, pointer show/hide, one
  synthetic letter and Back, Shift and Symbols. It checks pixels and continuous
  lock ownership; it never submits a password or touches the physical session.
- Native `touch_input` tests reject malformed coordinates. A real touchscreen
  and a disposable installed-system password test remain separate acceptance
  gates; a synthetic nested lock is not a PAM or hardware certificate.

## Suspend recovery

The existing event-driven idle helper listens for logind's after-resume event.
It asks the native compositor to synchronously reset KMS, retire lost page-flip
queues, redraw existing outputs and re-arm input. This operation preserves the
same session-lock owner and application processes; it cannot unlock the session.
Transient inactive-seat errors have a bounded retry window, not a polling service.
The idle child receives the actual Settings file so automatic and manual locks
use the same theme. Provider and unrelated internal environment variables are
not forwarded.

An installed disposable UEFI guest additionally passed real PAM rejection and
successful pointer-keyboard unlocking. These checks used a generated private QA
account and no physical host input. They do not establish AT-SPI or touchscreen
hardware support.

### Current virtual-machine limit

In the QEMU 8.2.2 q35/virtio-vga test guest running Ubuntu kernel
6.8.0-149-generic, S3/deep sleep returned to an inactive virtual display.
The same failure occurred in an independent Xorg-only Recovery session with no
Mellipi compositor running. Kernel display state reported an enabled output;
that alone was not a visible-resume pass. The native candidate retained its
applications, settings and session lock, but visual S3 resume is **not certified**
by this test. Physical suspend/lid-close testing remains separate. The recovery
hooks and a successful virtual-terminal return must not be presented as proof
that suspend works on every graphics driver.
