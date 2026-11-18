# Fewer buttons and better drag targets — Mellipi 0.1.30

This review covers the desktop and native apps after the 0.1.30 drag changes. The
guideline is to put the action on the thing it acts on: click to open, drag to
move or reorder, and use a context action for less common operations. Keep an
obvious keyboard route and a way to undo reversible moves. Leave actions that
can lose data explicit.

| Priority | Surface | What to change | Acceptance |
| --- | --- | --- | --- |
| High, reproduced | Desktop icons | Arrow keys follow list order after icons have been dragged into a custom layout. In an isolated fixture, Right selected an icon to the left, Down reached a clipped icon, and Enter opened it. Multi-select followed by F2 renamed the first selected item instead of the focused one. | Navigate between visible positions; Enter never opens a clipped tile. Disable ambiguous multi-item rename or require an explicit focused target, and make the keyboard context menu agree with its anchor. |
| High | Desktop group drag | Pressing an already selected icon resets the selection before the drag starts. Desktop drops also update separate positions one at a time. | Keep the whole selection until a pending click commits, anchor the group at the icon actually grabbed, and preview one atomic placement that keeps the spacing between icons. |
| High | Space Map | The card selects a space, Enter opens it, but the pointer needs a separate **Open space** button. Make the whole card select on click and open on double-click, then remove the separate button. Keep the name pencil and window drag surfaces distinct. | Clicking previews without switching; double-click, Enter and a disclosed non-drag action can open it. A miniature drag never switches spaces, and the action remains available to keyboard users. |
| High | Quick Settings | Four permanent grips use a column of space in a panel people open for volume, network and brightness. Try one compact **Reorder** entry that reveals grips and drop cues in the same panel; repeat it nowhere else. Keep genuine no-op drops from displaying a misleading insertion line. | Normal controls get the full width and no extra grip tab stops. In arrange mode, pointer and keyboard can reorder, reset, save on drop and cancel without opening another panel. Volume and brightness sliders never initiate the reorder. |
| Medium | Files | Dropping on folders works in the main file list, but the sidebar and tab shortcuts users can navigate to are not drop targets. Start with writable local bookmarks such as Downloads, keeping device rows and Trash outside this change. | Destination and Copy/Move are visible before release; invalid destinations reject the drop. The existing transfer pipeline handles errors and conflicts; Paste remains available. |
| Medium | Media | A queue row already starts playback when activated, but a separate Play button duplicates that action and treats the currently playing item differently. The queue itself cannot be reordered. Make rows reorderable and give rare row actions a context menu. | Drag and keyboard reorder the underlying queue, including duplicate tracks, without restarting playback or losing the current track. After reorder, Next and Previous follow what is on screen. Accept dropped files into the queue without replacing it. |
| Medium | Launcher | Search results can add both a pin button and overflow control to each result. Use one contextual action per active row, with Pin/Unpin in the existing menu. Keep right-click and Shift+F10. | Result columns stay aligned and keyboard users can open row actions without tabbing through several controls for every result. |
| Medium | Notifications | Notification cards use a permanent dismiss button and a full-width row per action. Promote one main action, put additional actions in overflow and keep keyboard and touch dismissal. | Multiple actions remain reachable; clicking blank space does not accidentally dismiss or run an action. |
| Medium | Calendar and Recorder | Use one Open/Edit command for Calendar event activation, including read-only imported events. Put Recorder’s Rename, Export and Trash commands on the recording row menu. | Recurring events keep their edit dialog. Recorded audio remains playable, with named keyboard actions for rename and delete. |
| Low | Launcher footer | Space Map is already in the workspace strip and searchable; remove the extra launcher footer shortcut. Show Desktop also has a desktop context action. Place file mode next to the search it changes. | Space Map is still reachable from the desktop and search, and switching file mode never clears useful text unexpectedly. |
| Keep explicit | Disks and file replacement | Keep the confirmation for formatting, writing an image to a drive, deleting a saved layout, and replacing file contents. Do not make these default drop actions. | Wrong targets never lead straight to a destructive action; confirmations identify the exact destination. |

The desktop keyboard issues were reproduced in an isolated Qt fixture. The remaining entries are source review findings or design recommendations. No desktop package or running session was changed.

The 0.1.31 follow-up implements the desktop navigation and group placement
changes, simplifies Space Map and Quick Settings, and updates Super,
Notifications, Files, Media, Calendar and Recorder. It preserves the existing
confirmation paths for destructive operations. The desktop keyboard and Space
Map checkpoint focus reproductions were rerun in isolated fixtures; the full
suite had 384 passes and one skip.
