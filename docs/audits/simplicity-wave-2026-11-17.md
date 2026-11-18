# Quick Settings and app simplicity audit — November 17, 2026

This is a follow-up to Mellipi 0.1.28. It records confirmed findings from private fixtures. The earlier [edge-case audit](edge-case-wave-2026-11-17.md) remains separate.

| Priority | Reproduced behavior | Repair and acceptance |
| --- | --- | --- |
| High | **Files Compress archives a replacement file.** If another process replaces the selected path while the ZIP naming dialog is open, the real worker archives the replacement bytes and reports Done. | Pin the source identity before the dialog, verify it when the worker opens the file, and reject a changed source without publishing a misleading archive. |
| High | **Keyboard focus disappears in Quick Settings and its editor.** In a 295×340 Appearance fixture, Tab focused the first Move Down button at y=341 without scrolling. In a 295×202 Quick Settings overview, Tab focused Power at y=191 inside a 157 px viewport; it did not scroll either. | Share a focus-reveal path for the overview and editor. Verify Tab, Shift+Tab, reorder, Restore, and return from a detail page at narrow width and large text. |
| Medium | **Rapid reorder loses the second move.** Before the Settings owner acknowledged the first change, two presses of Connections Up sent the same absolute order. Connections moved one place instead of two. | Send relative moves to the owner or keep an explicitly acknowledged local order. Test Up → Up and Up → Down with delayed snapshots. Keep one editor in Appearance. |
| Medium | **Moved controls are difficult to find.** Settings search returned zero matches for “quick settings”, “arrange controls”, and “high contrast”. For “motion”, it ranked the Accessibility link above the actual control; “text size” also offered the forwarding page. | Index the actual editor and high-contrast toggle. Remove stale forwarding keywords and verify that the first result goes directly to the requested control. |
| Medium | **A saved custom text size says “Choose device”.** With a valid 120% saved preference, the Appearance text-size picker uses the fallback label of its shared audio picker because 120% is missing from the list. | Display the saved size even when it is between presets; use a text-size label and test that opening the menu leaves the preference unchanged. |
| Medium | **Audio pickers can look identical.** With the same device description for input and output, Quick Settings shows the same visible name on both pickers. Their accessible names differ, but sighted users cannot tell which is which. | Label the controls **Output** and **Microphone**, leaving the page heading and device names in place. |
| Low | **Brightness appears twice in Settings search.** “Brightness” returns both the page and “Display brightness”, which opens the same page at its slider. | Prefer the specific destination for a term that matches both; keep the page result for broad searches that do not target the slider. |
| Low | **Photos offers two ways to write an edited PNG.** Save Copy clears the unsaved state; Export can write the same PNG but still prompts to save on close. This is a source-backed UX finding. | Use one visible Save a Copy action with optional export format and quality. Explain when a lossy export leaves edits unsaved. |

18 existing focused regression tests passed. These additional findings were reproduced in disposable fixtures. No desktop package or live session was changed.

All eight findings above were addressed in the 0.1.29 build. Files now also
holds the destination directory open while it writes the archive. Regression
coverage includes replacing a selected file, redirecting the destination,
reordering before Settings receives the updated order, direct Settings search,
a saved 120% text size, and PNG and JPEG copies from the same Photos action.
