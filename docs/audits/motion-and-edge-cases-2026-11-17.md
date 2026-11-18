# Desktop motion and edge-case wave — November 17, 2026

Settings → Appearance → Motion separates workspace slides, window effects, panels and menus, control feedback, and desktop/taskbar feedback. Search for **Desktop animations** in Launcher to open the tab. The shell pace setting applies to panels, controls, and desktop feedback; it does not change the compositor's window or workspace timing.

Reduce Motion overrides the individual switches without changing their saved values. Disabling an effect settles it at its final state without shifting click targets. Economy caps shell durations and avoids extra translation or spinner rotation. Native window effects remain independent of workspace slides.

| Reproduction | Fix and scope |
| --- | --- |
| Display topology changed while its previous snapshot was loading. | Coalesce requests and discard obsolete snapshots so the latest connector state is shown. |
| A favorite was removed, or an ancestor of a found file was replaced with a symlink after searching. | Invalidate results when favorite availability changes and recheck their scope on activation. |
| Closing Settings left Bluetooth discovery or pairing active. | Run page cleanup before changing the Settings host to inactive. |
| A playlist containing a file name with a Unicode line separator or vertical tab reopened incorrectly. | Parse M3U records on LF and CRLF boundaries. |
| Back stayed enabled after the remaining history folders were deleted. | Remove unavailable destinations and reflect the revised history in the navigation controls. |
| Canceling a local-only alarm left a selected but invalid alarm row. | Refresh the alarm list as soon as the local alarm is canceled. |
| Another app replaced a selected file during the Rename or Trash prompt. | Capture the selected file's identity before the prompt and check it again before the file operation. |

Verification was performed in disposable Qt profiles and nested Wayland sessions, without moving physical display outputs or modifying the running desktop.

379 integrated desktop tests passed (one skip), along with ten native compositor checks and seven native Settings checks. A separate native-shell check timed out waiting for Escape to release taskbar focus. The same check fails in a private copy of the unchanged 0.1.26 desktop, so that finding is still open.
