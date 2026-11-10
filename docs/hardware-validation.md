# Hardware acceptance and lifecycle testing

Run the read-only collector from `desktop/`:

```
python3 tools/qa-hardware-readiness.py --output /tmp/mellipi-hardware-report.json
```

Run it as the logged-in desktop user so it can query that user's private native
control socket and audio service. The collector never requests a seat, changes
an output, writes brightness, records sound, suspends, reboots or unlocks a
machine. It does not capture EDID blobs, device serials, Bluetooth addresses,
user names, window titles or full process environments. Output files are private
and created exclusively; existing files are never overwritten.

The observations distinguish **available capabilities** from **tested user
workflows**. One connected HDMI monitor is not a mixed-monitor test. A source
reported by PipeWire is not a recording test, and monitor sources are not counted
as physical microphones. `CanSuspend=yes` does not prove successful wake-up.
Every physical acceptance item remains `not_tested` until its procedure has
actually been performed and recorded in a separate versioned acceptance report.

## Minimum acceptance matrix

| Workflow | Required evidence |
| --- | --- |
| Suspend/resume | Lock before sleep; wake to locked display; correct password unlock; original apps, keyboard, pointer, audio and networking still work. Test lid close separately on a laptop. |
| Mixed monitors | Two physical monitors, different scales and refresh rates; window movement, fullscreen, focus, disconnect/reconnect and display-confirmation rollback. |
| GPU support | Actual native logins and workloads on named Intel, AMD, NVIDIA and hybrid configurations, recording kernel/driver versions. A virtio VM does not certify those drivers. |
| Wired/Bluetooth headset | Real device connected; input/output profile selection, record/playback, mute/media keys, disconnect/reconnect, and battery when available. |
| HDMI brightness | Real DDC-capable monitor and correct I2C policy; physical change and reconnection confirmed. No gamma approximation counted as DDC. |
| Touch unlocking | Physical touch coordinates, keyboard selection, incorrect/correct password, output rotation and lock preservation. A synthetic protocol test is a separate gate. |
| Installation/recovery | Owned VM or backed-up disk only: install, normal password login, reboot, signed update, exact-version package recovery, settings restore and retained user data. |

On a working daily-use session, collect read-only observations first. Physical
suspend, monitor disconnection and installation require an explicit test window
and saved work. Keep a recovery TTY available. Tests must never silently close
applications, replace the host display manager, disable authentication or claim a
synthetic VM result as physical-device certification.

## Virtual-machine suspend acceptance

Use only the guarded harness's owned disposable guest and private disk. Verify
that the **guest** actually enters S3 (QEMU reports suspended), then wake that
same owned guest through its QMP connection. Never substitute a physical-host
suspend command or a compositor display-power toggle for this test.

After wake, a live control socket or an old screenshot is insufficient. Require a
freshly rendered change and keyboard/pointer interaction, the original desktop
and application processes, continued lock ownership, rejection of a wrong
password and successful normal unlocking. Record the exact package/ISO/kernel
and the guest evidence. A passed guest S3 workflow still does not certify a
laptop lid, physical GPU firmware, audio hardware or monitor hotplug.

## Current physical observation

The read-only observation on 2026-11-10 found an Intel i915 GPU and one connected
HDMI display; the running native session reported 1920×1080 at 60 Hz, scale 1.
The audio service exposed only a monitor source, so this did not verify a physical
microphone. DDC tooling was installed and logind offered suspend. Physical
hotplug, mixed-monitor behavior, actual suspend/resume, physical DDC changes,
microphone recording and other GPU families were not exercised. These results
describe the installed baseline session, not acceptance of a pending release.

## Observed virtual S3 limitation

The private QEMU 8.2.2 q35/virtio-vga guest with Ubuntu kernel
6.8.0-149-generic reached S3/deep sleep and resumed its kernel, but its virtual
display remained inactive. Both a native Mellipi candidate and an independent
Xorg-only Recovery session reproduced this result. No physical host suspend was
attempted. This is a failed visual-resume test for that virtual graphics stack,
not a native compositor pass or a physical-hardware certificate. Existing apps,
settings and lock ownership survived in the native candidate; those are separate
observations from successful scanout and input recovery.
