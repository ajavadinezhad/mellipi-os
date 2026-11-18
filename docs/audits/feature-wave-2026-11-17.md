# Mellipi feature wave — November 17, 2026

The baseline is Mellipi 0.1.24. Each proposal fills a gap in an existing workflow. Prefer local data, lazy loading and existing processes. **S** means one small surface; **M** means a feature plus persistence or an integration; **L** means multiple coordinated components or safety-specific review.

| App | Proposed addition | Acceptance check | Size |
| --- | --- | --- | --- |
| Files | **Folder tabs.** Keep two locations open without opening separate file windows or replacing the current location. Reuse the tab strip convention from Terminal. | Open two folders; navigation history, selection and search stay with each tab. Switching tabs leaves an active copy running. | L |
| Text Editor | **Compare with Disk.** Offer a local, read-only diff when an external edit conflicts with the current buffer. | Compare a file changed on disk without rewriting either side or dropping a recovery draft. Handle deleted files, CRLF and a UTF-8 BOM. | M |
| Terminal | **Split the current tab.** Put a second terminal next to the first for a command and its logs. | Each pane has its own shell and working directory; only the focused pane receives keystrokes; closing one with a running job uses the existing confirmation. | M–L |
| Browser | **Searchable local history.** Find recently visited pages and forget individual entries or clear the list. | History persists within a bounded limit; private windows, failed loads and non-web URLs never enter it. | M |
| Calendar | **Monthly and yearly repeats.** The current daily and weekly repeat options cannot express bills, birthdays and anniversaries. | An event remains editable and searchable and still schedules its next reminder after restart. Test the 31st, February 29 and a daylight-saving transition. Document when a date is skipped. | M |
| Clocks | **Countdowns that survive closing the app.** Reuse the existing alarm queue for a running timer. | Start a timer, close Clocks, and receive one alarm. Reopening shows the same deadline and a Cancel action. Test resume and expired timers. | M |
| Calculator | **Percentage shortcuts.** Add “percent of” and “percent change” without changing expression syntax. | 15% of 240 returns 36, and a change from 80 to 100 returns +25%. Report a zero starting value clearly; keyboard access and the existing postfix percent both keep working. | S |
| Photos | **Export choices.** Add JPEG and WebP alongside PNG, with size and quality controls. | Export a transparent image to PNG and JPEG with an explicit JPEG background preview. Strip metadata by default and preserve the existing no-overwrite guarantees. | M |
| PDF Viewer | **Extract pages.** Save the current page, selected ranges or a reordered list to a new PDF. | Extract nonadjacent rotated pages from the opened revision; include corresponding markup only if selected, and never replace the original. | M |
| Media | **Save and open local playlists.** Use M3U8 so queues can be reused after closing the player. | A playlist round trip preserves order and duplicate tracks, reports missing files once, and does not fetch remote entries. | M |
| Sound Recorder | **Trim to a new file.** Set start and end markers and export only that stretch of the recording. | A PCM fixture trims at exact frame boundaries, exports the expected duration and leaves its original bytes intact. | M |
| Disks | **Verify a written image.** Report whether the flashed image matches the bytes read back from the device. | Compare only the image-length prefix on the same unmounted USB identity. Show progress, mismatch, and canceled states. Test against a disposable VM disk. | L |
| System Monitor | **Process tree.** Show which processes belong together while retaining the existing flat list. | Handles exited and reparented processes as the data changes. Selecting a row identifies the exact process before signaling. | M |
| Software | **APT dependency preview.** Show what a transaction would add or remove before administrator approval. | An install or update that would unexpectedly remove packages stops and explains why. Changing the selection invalidates the preview. Simulate package transactions before real writes. | M–L |

| Desktop surface | Proposed addition | Acceptance check | Size |
| --- | --- | --- | --- |
| Workspaces and Space Map | **Named spaces.** Share optional labels across Space Map, the workspace strip, the move menu and launcher results, while keeping existing numeric shortcuts. | Rename a space without moving windows or restarting. Persist names across sessions, handle independent outputs, and disambiguate duplicate names by number. | M |
| Settings → Displays | **Visual monitor arrangement.** Add a keyboard-operable output map with snapping and rotation previews alongside exact X/Y coordinates. | Test mixed scaling, rotation and negative origins. A single confirmation applies the complete layout; reverting, timing out or unplugging restores all affected outputs. A compositor transaction is a prerequisite. | L |
| Launcher | **Find files in favorite folders.** Add an explicit file search mode that searches a user-chosen folder on demand using the same bounded search as Files. | Search is cancellable, never crawls the whole home directory by default, supports keyboard activation, and hands the result to Files or its default app. | M |
| Quick Settings | **Choose which controls appear first.** Let users reorder a short list of existing controls without adding duplicate panels. | A keyboard-accessible picker reorders controls; restoring defaults works; narrow layouts and screen readers follow the same order. | M |

Suggested build order: **Named spaces**, **Calculator percentage shortcuts**, **Editor Compare with Disk** and **Calendar monthly/yearly repeats** first. Those changes have a clear payoff without depending on hardware or administrator access. Build the alarm-backed Clocks timer and the Software transaction preview next. Keep the multi-output transaction and USB read-back as separate, tightly scoped integrations.

## Verification and separate regressions

All 13 installed Mellipi app launchers and the Calendar `--clocks` entry point mapped Wayland windows and closed on request under a private native compositor. The launcher opened, 14 Settings sections loaded without QML errors, 169 focused tests passed: 31 for shell and Settings, 64 for daily apps, and 74 for media and system apps. This confirms startup and close, not every workflow in each app. Hardware-dependent actions and package transactions were excluded from the smoke run.

| Priority | Reproduced behavior | Repair to queue |
| --- | --- | --- |
| High | **Editor Save As** overwrote bytes written by another process after the filename chooser returned. | Publish to a new path without overwriting; verify the identity again after explicit overwrite consent. |
| High | **Desktop shortcuts:** dropping two URLs from the same host reported two successful transfers, but both shortcuts contained the second URL. | Stage each shortcut at a distinct path while preserving the visible filename, then verify both URLs in the completed transfer. |
| High | **Recorder Rename** renamed a replacement WAV that took the selected file's place while the prompt was open. | Pin the selected file's identity and reject replacement before renaming, as Trash already does. |
| Medium | **Files Back** got stuck after deleting the previous folder in the history; Back remained enabled without leaving the current folder. | Skip unavailable entries and disable the action when no reachable entries remain. |
| Medium | **Browser Reopen Closed Tab** lost a restored tab closed before its first visit. | Capture its deferred URL and position without loading it. |
| Medium | **Calendar** scheduled a reminder one hour early for a UTC event at the second 01:30 during New York's fall-back transition. | Subtract the reminder offset from the original instant for zoned events instead of from the displayed wall-clock time. |
| High | **Clocks** changed the selection from a local-only alarm to a saved alarm during refresh. Cancel then targeted the saved alarm. | Preserve the exact alarm identity, including the local-only entry, and fail safely if the selected alarm no longer exists. |
| Medium | **Software** jumped from the chosen APT search result to the first row when a later Flatpak result arrived, even though the chosen package remained. | Preserve selection by source and package identity across progressive results. |

A separate local WAV fixture ruled out the suspected duplicate-track symptom on the Qt FFmpeg backend: the second queue entry for an identical file started at 0 ms even after the first had advanced. That check did not cover GStreamer.

## Implementation notes

- In **Files**, use Ctrl+T for a new folder tab and Ctrl+Tab to move between tabs. Transfers continue while you browse. In **Terminal**, Ctrl+Shift+E opens a second pane with its own shell. Editor offers **Compare with Disk** on a save conflict; Browser History is stored locally and excludes private visits.
- **Calendar** skips dates that do not exist in a series. It keeps a January 31 series on the 31st and a February 29 series on leap days. **Clocks** uses the existing user alarm queue and shows a local-only fallback if background scheduling is unavailable.
- **Disks → Verify Image** compares the original image with the start of the selected removable device, opens the device read-only, and checks the device identity and mount state. **Software** runs a simulation before requesting administrator access and refuses to proceed if a second simulation produces a changed plan.
- Space Map accepts optional workspace names without changing the numeric shortcuts. Launcher file search only searches an explicitly chosen Files bookmark. Quick Settings can reorder its existing first-page controls and restore the default order. Display arrangement stages logical positions together; changing resolution, rotation or scale remains in the existing separate preview.
- The app redesign introduces a shared tinted title strip, a cleaner tab and action hierarchy, aligned window buttons, simpler modal styling, and a separate navigation row in Files. System Settings and GTK Terminal follow the same visual treatment. Theme palettes remain the source for color and contrast.
- The integrated desktop run passed 367 tests with one skip. All 52 release-tool tests passed, and the private Wayland Settings window passed seven separate interaction checks. The disk tests use fixed files and mocked UDisks identity; they do not write to physical storage.
- All 14 app entry points from the extracted 0.1.25 release packages opened and closed on the packaged compositor. The launcher and 14 Settings sections loaded without QML errors.
- All 52 native compositor tests passed, including simulated multi-output validation, rollback, disconnect, and persistence. Nine private Wayland Space Map checks covered keyboard rename and focus restoration. A physical dual-monitor setup was not changed during verification.
