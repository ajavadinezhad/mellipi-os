# Mellipi native app feature audit

This is a source and test inventory. A feature appearing in the source does not guarantee that it works on hardware. The list prioritizes gaps in everyday workflows before adding new surfaces.

| App | Highest value follow-up |
| --- | --- |
| Files | Expose progress and cancellation for large jobs. The transfer backend already supports both. Add bookmarks and tabs after the job UI. |
| Terminal | Add tests for session handling, tabs and close confirmation. Consider profiles or splits once those paths are covered. |
| Settings | Exercise display apply, rollback and monitor reconnect on real hardware before adding more controls. |
| Software | Let users update and remove packages with a review of affected dependencies. Test on a disposable installation. |
| Photos | Add rotation and explicit export options. Preserve originals by default. |
| PDF Viewer | Report malformed documents clearly. Test markup export and reopening in another viewer. |
| Media | Add audio and subtitle track selection, then resume playback. Add playback and queue tests. |
| Disks | Add read-only image verification and better progress diagnostics for existing operations. |
| Text Editor | Handle encoding and line endings explicitly. Prevent saving content the editor cannot reopen, such as text containing NUL characters. |
| Calculator | Verify history at 150% text scaling before expanding it. |
| Calendar | Add event creation, editing, deletion and export, including clear treatment of imported events. |
| Browser (optional) | Add permission review and recovery workflows, with saved sessions only by choice. Extend tests beyond bookmarks. |

A second workflow pass found these reproducible problems:

- Files: copy or cut several entries, then remove a source before pasting. The batch can publish earlier items and stop on the missing one; the only visible outcome is a transient error. Report what succeeded and what remains so a retry does not produce duplicates. Multi-item Trash has the same early-stop behavior.
- Software: installation and refresh can leave the window waiting indefinitely for an authentication prompt or helper. Separate cancellation before authorization from a status view after package changes begin; killing the package manager mid-transaction can damage its state.
- Terminal: closing a fresh shell uses the same destructive prompt as closing a session with a running job. Distinguish active processes and use explicit action labels.
- Settings: switching away from Displays hides the Keep/Revert preview and countdown. The watchdog still rolls back, but the decision needs to stay visible during that preview.
- Editor: pasted NUL characters can be saved, but the resulting file is refused as binary on reopen.
- Disks: a completed format or image write may be reported as failed when refreshing the device list fails. Report the operation and refresh separately.
- Media: the queue stops on an unreadable item without offering a recovery action in the error. Browser: concurrent downloads share one status line and lack per-download controls.
