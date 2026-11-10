# Backups and desktop recovery

Settings → System tools → Backups & recovery offers three on-demand workflows.
No backup daemon, file watcher or recurring scan runs in the background.

Browse opens a separate ordinary desktop file-picker window on demand, using the
same private home/profile as Settings. The panel stays responsive while choosing;
Cancel stops only that owned picker window. Closing the picker without selecting
anything keeps the previous destination and file selection.

## Back up

Choose a destination, preferably a separate trusted drive. Desktop settings are
included by default: appearance, pinned apps, layouts, display choices and the
small desktop data JSON files. Documents are included **only** when explicitly
selected with Add files or Add folder. Application profiles, passwords, cookies,
SSH keys, logs and the entire home directory are not automatically included.

The result is a private `Mellipi-backup-...` folder with ordinary files and a
SHA256 manifest. Version 2 also records empty folders, file/folder modification
times, and the owner-executable bit. Version 1 backups remain readable with their
original metadata defaults. It is portable but **not encrypted**. Keep it on trusted storage
or an encrypted volume. Symlinks, sockets, devices and FIFOs are rejected rather
than followed; select the actual files when needed. Limits are 50,000 entries (files and folders) and
32 GiB per backup to bound desktop resource use. This is a lightweight document
and desktop-settings backup, not a complete system image or database snapshot.

## Restore

Select a backup and choose Verify backup. Every recorded file is checked before
restoration. Restore to new folder creates a fresh `Mellipi-restored-...` folder
under the chosen destination and never replaces existing documents. Empty folders
and modification timestamps are restored. Personal files are owner-readable and
writable (600), with owner-execute preserved when present (700); folders use 700.
Setuid/setgid, group/world permissions, ownership, ACLs and extended attributes
are not restored. Choose a Linux filesystem for restoring these permissions;
the operation fails safely if the destination cannot enforce them. Move chosen
documents back with Files after reviewing them.

Restore desktop settings requires a second explicit Schedule settings restore
action. The desired JSON is copied into a private bounded request; changes apply
before the shell starts at the next real installed login. Your current apps stay
open. Every destination is fingerprinted when scheduling. A subsequent edit wins
over the restore, and pre-restore files are retained under
`~/.local/share/abstract/before-settings-restore-...`. Cancel scheduled settings
restore removes the pending request. The request contains only allowlisted JSON
settings, no executable configuration, application data or arbitrary paths.

## Last working desktop

After checking the installed desktop works, choose Save this working version.
The record includes both Mellipi packages and installed transition packages so
their dependencies can be restored together. It can also be saved from a normal
user terminal with:

```
mellipi-recover --save-working
```

If an update prevents graphical login, press Ctrl+Alt+F3 and sign in normally.
Run `mellipi-recover` to display the saved exact-version recovery command. For
example, a core-only installation may show:

```
sudo mellipi-recover --restore mellipi-shell=0.1.8 abstract-shell=0.1.8
```

The helper accepts only the four known desktop package names with validated exact
versions. It invokes APT with normal signature verification, shows its proposed
changes, and asks for confirmation. It never installs an arbitrary local `.deb`,
executes a saved command, forces a downgrade without review, or restarts a session.
The trusted configured repository must retain the requested versions and be
reachable. This is not an offline rescue partition, boot-time rollback menu,
kernel rollback or filesystem snapshot. Those remain separate system-level work.
Save any open documents before a normal logout/login activates restored binaries.


## Recovery at the sign-in screen

The complete desktop profile adds **Mellipi Recovery** to the session chooser.
It uses the normal LightDM password login, then opens a small Xorg terminal
without starting the Wayland compositor, panels, user shell startup files or
startup applications. This lets you run `mellipi-recover` even when the compositor
or shell fails. Type `exit` to return to sign-in. It is a repair session rather
than a replacement desktop and does not lock; sign out before leaving it.
Core-only installations retain their existing distribution recovery sessions and
the TTY helper. This fallback still needs the distribution's Xorg/LightDM stack;
it cannot repair a machine that cannot boot or whose login authentication fails.

The full profile's vendor LightDM fragment uses an isolated session dispatcher.
Only the exact Recovery entry is routed directly to the recovery launcher,
before the normal LightDM wrapper sources `.profile`, `.xprofile` or
`.xsessionrc`. Other sessions retain the stock `/usr/sbin/lightdm-session`
startup path and arguments. No user startup files are edited or renamed.
An administrator's higher-priority `/etc/lightdm` `session-wrapper` setting
continues to take precedence. Such a custom wrapper can run its own startup
scripts before Recovery; use the recovery TTY or adapt that administrator-owned
wrapper if it prevents the recovery session from starting.
