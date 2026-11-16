# Mellipi: next desktop design pass

This is a read-only product and engineering audit. It separates improvements to the daily workflow from the feature that could give Mellipi a recognizable identity.

## Lead with Space Map and Checkpoints

Turn the existing workspace strip into the entry point for a map of the four workspaces. A tile shows its name, app icons and the arrangement of windows. The user can focus a window, move it to a different space, or preview and undo a layout change. Ordinary Super typing still opens search immediately; the map has its own clear keyboard and pointer access. Keep the existing fast path for people who switch spaces by number.

Start from the native workspace/window state and the existing drag-to-space behavior in [OrbitSpine.qml](../../desktop/native/OrbitSpine.qml). Mellipi already saves named layouts, previews geometry, matches live windows, can open missing apps at the user's request, and exposes Undo. Reuse [arrangements.py](../../desktop/src/arrangements.py), [LayoutsPanel.qml](../../desktop/native/LayoutsPanel.qml), and the geometry-only cards in [UnifiedLauncher.qml](../../desktop/native/UnifiedLauncher.qml). Give the feature one home and have launcher search link to the same action and state.

Build the first slice in two steps:

1. **See and move:** four stable tiles; switch or move with pointer and keyboard; a clear current workspace marker; sensible empty and overflow states.
2. **Preview and undo:** first surface history for arrangements Mellipi already owns. A preview lists which live windows will move, which have closed and which no longer match. Undoing a restore restores the prior window positions where possible. Never close or launch an app during a checkpoint restore; explicit saved-layout Resume remains the action that may launch apps. Do not promise document, tab or app-session recovery. Keep automatic history bounded and in memory.

Prior art includes [GNOME's workspace overview](https://help.gnome.org/gnome-help/shell-workspaces-switch.html), [COSMIC's workspace tiling](https://system76.com/support/pop-basics), [KDE Activities](https://docs.kde.org/stable_kf6/en/plasma-desktop/kcontrol/kcmactivities/kcmactivities.pdf), and [PowerToys Workspaces](https://learn.microsoft.com/en-us/windows/powertoys/workspaces). The opportunity is making live desktop changes visible, previewable and reversible in a single everyday view.

Use simple rectangles and icons for previews. Keep models unloaded when closed; use existing events while open. No screenshots, background service, or compositor migration in the first slice. Compare median and 95th-percentile input-to-visible latency against the existing workspace switcher, and compare idle shell/compositor memory and CPU with the map closed. Set numeric budgets only after capturing the baseline on the target hardware. Check 150% text, reduced motion, mixed-scale outputs, minimized and floating windows, and windows that close mid-preview.

Current arrangement restore uses multiple window queries and a per-window delay. Keep preview building to one cached snapshot, measure restore separately, and add a native-compositor test with Wayland and XWayland windows next to the legacy arrangement fixture. A later phase can record native title-bar drags once at gesture completion.

## Make the common paths predictable

| Priority | Change | Acceptance |
| --- | --- | --- |
| P0 | Keep display preview confirmation outside the page loader in [SystemPanel.qml](../../desktop/native/SystemPanel.qml). [DisplayPanel.qml](../../desktop/native/DisplayPanel.qml) already has a countdown and rollback, but can be navigated away from. | Keep/Revert stays reachable by keyboard from another setting or search. Timeout restores the prior mode. Verify HDMI reconnect and suspend on physical hardware. |
| P1 | Give Quick Settings a status-first view: sound and brightness are direct, connection and device details open from their current status, and session commands have a stable location. Use [QuickPanel.qml](../../desktop/native/QuickPanel.qml) and retain direct entry from existing indicators. | Volume/mute on the first screen; Wi-Fi and audio output reachable from named status controls. Keyboard focus returns from details. Fit at 150% text with disabled, loading and error states. |
| P1 | Give Files a transfer receipt. Keep the current conflict and cancellation handling, expose completed/failed/pending items from [file_transfers.py](../../desktop/src/file_transfers.py), and let the user retry what remains. | When USB disappears after an earlier item completed, the app makes the partial result explicit. Retry does not recopy or lose completed items. |
| P1 | Show distinct authorization, applying and finished states in [Software](../../desktop/src/mellipi_software.py). Allow leaving the view while a safe owner tracks a transaction; distinguish canceling an authorization request from interrupting package writes. | Verify canceled authorization, offline errors, package conflicts and successful updates in a disposable VM. |
| P1 | Replace the stock administrator authorization prompt with a Mellipi dialog. Build this as a session-wide polkit agent so Software, Disks and other polkit requests get the same prompt. | The dialog identifies the action and account, uses the active theme, and handles keyboard navigation, retries and cancellation. Verify fallback and login isolation before enabling it by default. |
| P2 | Give [Appearance](../../desktop/native/AppearancePanel.qml) a preview of the wallpaper, taskbar, and a native window together. Use theme tokens and assets, and scope changes to the preview until applied. | Show contrast, icon scale, positioning and text together. Preview and Reset remain reachable on narrow screens. Lock screen should reuse visual tokens while keeping the existing authentication path. |

The practical order is display confirmation first, then Space Map and Quick Settings for a visible desktop change, then checkpoint preview and the two transaction improvements. Keep the toolkit and native compositor. The first demonstration should be: open the map, move a window, see where it went, preview a previous arrangement, and restore it with no app closed.

One smaller visual defect to reproduce before changing the launcher: a prior private 856 px capture shows the **Layouts** and **Files & notes** footer labels overlapping. Check the current packaged build at that width and at 150% before calling it fixed.

## Administrator authorization

Today [session/assistive.py](../../desktop/src/session/assistive.py) selects an installed desktop authentication agent; [session/autostart.py](../../desktop/src/session/autostart.py) makes sure a second agent does not start in the same login. Keep that behavior while adding a native option. This is a separate surface from logging in or unlocking.

Use a compact centered dialog: **Administrator permission**, the action description from polkit, the authorized account, a focused password field, **Cancel**, and **Authenticate**. Offer an account selector only when polkit supplies more than one eligible identity. Show retry and alternate authentication prompts in place. Render authority messages as plain text and follow the active theme, including high contrast and large text. Software can say “Waiting for authorization” while the system dialog is open; apps should not collect credentials themselves.

The implementation uses the public [AuthenticationAgent interface](https://www.freedesktop.org/software/polkit/docs/latest/eggdbus-interface-org.freedesktop.PolicyKit1.AuthenticationAgent.html) and [PolkitAgentSession](https://www.freedesktop.org/software/polkit/docs/latest/PolkitAgentSession.html). It accepts requests only from the current unique system bus owner of polkitd and registers only for its own graphical login. Polkit and PAM handle verification and policy. The program does not persist, log, copy, or forward password text to an app, and does not alter policy rules.

The custom dialog is opt-in via `MELLIPI_NATIVE_AUTH=1` in the Mellipi session launch environment. The distro agent is the default and is also the startup fallback when the experimental agent is selected. Before flipping the default, verify wrong and correct credentials, authority cancellation, duplicate requests, multiple identities, lock and logout, another login and agent startup failure in a disposable VM.
