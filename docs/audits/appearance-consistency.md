# Mellipi appearance consistency audit

Scope: native applications, Files and its chooser, Terminal, the shell and Settings, and login, lock and installer surfaces. This pass records fixes to make; it does not change the desktop.

The theme palette is a solid shared base. All eight shipped presets kept their accent and surface colors with high contrast enabled during testing. The QML text-field tests passed across the eight presets and 18 custom light, dark and black variants, with high contrast both on and off. The tested Qt palette pairs also cleared 4.5:1 for selected text and 3:1 for focus and control borders. Those checks cover palette values and the tested text field; they do not certify the appearance of every Qt or GTK widget.

| Priority | Area | Finding and recommended correction |
| --- | --- | --- |
| 1 | Qt fields and dropdowns | Recorder input, Software source, and Photos pen color use the generic button style for their dropdowns. The resting edge is transparent, including in high contrast, unlike text fields. Calendar alarm/time and resize/number dialogs use spin/date fields with no shared field styling. Give typed fields, steppers and selects the same visible boundary, keyboard focus treatment, disabled state, and popup selection style. Existing selectors are in `desktop/src/qt_app.py`. |
| 1 | Shell and Settings dropdowns | Settings theme, general choices, and audio/display device selectors have different resting borders and row heights; Layouts still uses a stock Qt ComboBox. Share one control appearance and text-scaled row sizing while keeping inline expansion where it aids the workflow. See `ThemePicker.qml`, `SettingsChoice.qml`, `AudioDevicePicker.qml`, and `LayoutsPanel.qml`. |
| 1 | Files and chooser high contrast | Their view rules explicitly remove the outline even when the shared high-contrast style asks for one. Files and the chooser use a full accent fill for selection; generic Qt lists use a softer selected surface. Preserve required outline and focus in all modes; define one list/menu selection treatment with the correct foreground and icon colors. See `mellipi_files.py` and `file_chooser.py`. |
| 2 | In-app dialogs and text areas | Files rename/restore, PDF notes/go-to-page/print, and Photos resize use several dialog styles. Editor's document uses a separator border with no explicit focus treatment. Route simple inputs through a shared themed dialog and field style. Retain the document canvas's low visual noise. |
| 2 | Browser, Editor, Calendar, Terminal | Browser and Editor use independent selected-tab spacing and backgrounds; Calendar Clocks inherits stock tab and input styles; Terminal has its own GTK tab and menu styling. Match the visual meaning of selected tabs and keyboard focus across toolkits. Terminal can keep ANSI colors and the terminal canvas unchanged. |
| 2 | Small status and action controls | Keep the new semantic app colors as identity cues. Apply theme accent consistently to selected/primary actions and use an on-accent foreground for every label and glyph on a solid accent background. Keep label and state indicators for actions such as Record, mute and destructive disk operations. |
| 3 | Login and installer | The installer currently uses a fixed Forest visual preset, while the LightDM greeter is fixed Adwaita-dark with static artwork. Match their shared branding and form hierarchy while keeping their independent pre-login configuration model. The live user's theme is not a safe dependency for a greeter. |

Other concrete findings:

- Shell fields leave text selection colors to the toolkit. Segmented controls and device selection checks use the raw accent where the contrast-adjusted focus color is needed. General dropdown rows should expose an accessible name and explicit selection mark.
- A white custom accent on the light lock surface measured 1.00:1, and black on the dark lock surface measured 1.28:1. Keep lock authentication unchanged and use contrast-adjusted color for the entry indicator.
- Terminal's resting Find outline measured 1.80–2.54:1 against its surface across the eight presets. The shared control-border token would improve that to 3.78–4.46:1. Its menu should also give keyboard selection the same clear state as hover.
- Media's start icon uses a hardcoded corner radius even under Square. Ordinary application outer borders already belong to the compositor; align internal dialogs without adding a duplicate outer frame.
- The chooser's filename and dropdown controls fit in offscreen checks at 85%, 100%, and 150% text sizes in all three density modes. Preserve that behavior during the redesign.

Recommended order: unify Qt and QML input specifications, fix the missing high-contrast outlines, then migrate app-specific dialogs and tabs. Verify screenshot and keyboard behavior at 100% and 150% text size in light, dark, black and high contrast.
