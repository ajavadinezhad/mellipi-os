# Mellipi control placement review

Review each screen by walking through a task: find it, select the target, take the action, and understand the result. Check the screen empty, with content selected, and during or after a failed operation. A control's position should make its scope clear.

The [KDE layout and navigation guidance](https://develop.kde.org/hig/layout_and_nav/) treats navigation, view controls, and app-wide commands as different roles. The [GNOME header bar](https://developer.gnome.org/hig/patterns/containers/header-bars/) and [menu guidelines](https://developer.gnome.org/hig/patterns/controls/menus.html) give a useful distinction between persistent actions and secondary actions. [GNOME's adaptive guidance](https://developer.gnome.org/hig/guidelines/adaptive.html) treats resizing as a layout change rather than an instruction to shrink everything.

Apply these principles in Mellipi:

- Keep mode and destination navigation together. Changing views should leave the navigation recognizable.
- Group actions with the thing they change. View-wide actions can sit at the view heading; selected-item actions belong with the selected item or list. Keep status separate.
- Give the most common next action a stable location and a clear label. Icon-only actions need an accessible name and a tooltip. Keep rare, destructive commands in contextual menus with explicit confirmation.
- At narrow widths or 150% text, let a group stack or collapse into a named control. Keep primary actions reachable without scrolling past an unrelated pane. Preserve keyboard focus and shortcuts when controls move.
- Check the shell along with apps: launcher search and result actions, Quick Settings controls, Settings navigation, taskbar and tray at each supported edge, desktop menus, and the shared chooser.
- Give each setting one place to edit it. Search and related pages can link to that control. Put frequently used actions in Quick Settings; keep reordering and other setup in Settings. Hide advanced options until requested, and omit controls that have no target on the current device.

Calendar is the example for a responsive primary action: **New event** sits with the selected day in a wide window and moves to the toolbar in a narrow one. Disks is the example for scope and safety: the heading names the selected device beside **Open**, **Mount**, and **Details**; **More** exposes maintenance commands only for eligible targets.

| Surface | Result of this pass |
| --- | --- |
| Calendar and Clocks | Stable mode navigation; Today stays by the month; event actions stay with the agenda; clock controls stay with their readout. |
| Disks and Monitor | Drive actions name their current target; End Process sits with the process list. |
| Settings and Quick Settings | Search sits with section navigation; slider values align with their controls; Wi-Fi results use the panel's scroll area. |
| Launcher, taskbar and desktop | Launcher search and secondary controls share space; window counts no longer cover tight task icons. Kept the top strips and desktop icon placement after review. |
| Files and chooser | Compact Places keeps navigation available while freeing list width; chooser metadata yields to filenames in stages. |
| Photos, PDF, Media and Browser | Crop actions stay with the crop tool; optional document controls yield before page navigation; playback actions stay with transport; New Tab sits with the tabs. |
| Software, Recorder, Calculator and Editor | Package actions stay with selection, recording and library actions are separated, copy and clear sit with the expression, and find and go-to-line stay with the editor. |
| Terminal | Kept tab-scoped search after checking focus, query changes and closing search by keyboard. |
