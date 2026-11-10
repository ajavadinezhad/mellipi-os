# Source build baseline

The current packaging/build cache targets Ubuntu24.04/Noble amd64. Source and
binary portability are separate tasks: copying an ELF built on this host to an
older glibc distribution is not a supported installation strategy. The package
builder records the target architecture but does not cross-compile it.

Build as an ordinary user. Release helpers use one low-priority compiler for the
large compositor, locker, portal and Qt compatibility builds. The core helper
currently allows two jobs. Build-time disk and memory use are separate from
running the desktop.

Required host build tools include Python3, a C/C++ compiler, `pkg-config`,
`dpkg-deb`, `patch`, `readelf`, `nm`, `strip`, `ldd`, and a recent Rust/Cargo
compiler with edition2024 support. This checkout was built with
Rust/Cargo1.99.1; it does not yet declare a tested minimum compiler version or a
fully pinned compiler bootstrap. Do not assume Noble's default Rust package is
sufficient. The scripts use `desktop/.toolchain/{cargo,rustup}` relative to the
repository root for the compositor; the core helper can also use `cargo` from PATH. Provision that trusted toolchain
explicitly before a fresh source build.

The application source and its build tools live in `desktop/`. From the repository
root, enter that directory before building:

```sh
cd desktop
python3 tools/prepare-native-drm.py
python3 tools/prepare-screen-lock.py
./tools/build-native-compositor.sh --release --features drm
./tools/build-core.sh
python3 tools/prepare-portal-runtime.py
python3 tools/prepare-qt5-a11y-runtime.py --jobs 1
python3 tools/build-desktop-package.py --version 0.1.6 --with-desktop
```

These commands write packages under `desktop/dist/`. Application unit tests also
run from `desktop/`, for example `python3 -m unittest discover -s tests`. The
repository-level `tools/` directory contains publication tools, not app compilers.

The preparation tools download/extract development inputs into `desktop/`.
They do not install packages on the host or change a running desktop. The locker
and portal verify pinned upstream archives; the portal and Qt compatibility
build also verify their recorded distribution inputs. DRM development packages
use pinned distribution versions and record the resulting archive hashes.
`--offline` is supported by the DRM, locker and portal preparation tools when
all their inputs are already cached. Missing/expired pinned package versions
fail rather than silently selecting a different ABI.

The Qt compatibility builder specifically requires the matching Noble
Qt5.15.13 package versions recorded in its input manifest. It retains the
distribution patch series. The installed selector checks host-library hashes on
each Qt process startup and drops the private override after an incompatible
update. That protects runtime compatibility; it does not prove accessibility on
the new system. Rebuild for the supported updated ABI and repeat real AT-SPI
acceptance rather than copying another system's Qt library.

The resulting `.deb` contains immutable program files under `/usr/lib/abstract`,
a standard Abstract Wayland session entry, private-XDG launchers and narrow
system integrations. It does not contain this checkout's user database,
passwords, private build caches or a Linux kernel. Do not use the experimental
checkout registration helper as the production packaging installer.

Validate the produced packages in the four fresh-VM cases described in
[clean installation acceptance](clean-install-acceptance.md). A cached build,
host APT simulation or host-linked `ldd` pass does not replace a clean build or
clean installation. Record exact source snapshot, compiler version, package
versions, image signature/checksum, installed release versions and test results
before calling a release portable to a new target.
