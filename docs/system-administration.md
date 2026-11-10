# Standalone users and clock settings

Open **Settings → System tools → Tools → Users and passwords** or **Date and
time**. These pages use AccountsService and systemd-timedated directly rather
than opening another desktop environment's control center. They read only when
opened/refreshed and use a bounded worker for service calls. Authorization uses
the distribution's ordinary polkit agent.

The complete installation needs `accountsservice`, `python3-gi`, and systemd's
timedated service. Network time additionally needs `systemd-timesyncd` or another
time service recognized by timedated. A missing service produces an error; no
system configuration or working network setup is silently replaced.

## Accounts

- View regular AccountsService accounts and their administrator/locked state.
- Change display names and another user's account type. The signed-in user's
  own role cannot be changed here, and the last known unlocked administrator is
  protected.
- Create standard or administrator accounts with a password. Passwords are
  checked and hashed locally using the distribution's libcrypt SHA-512 crypt
  implementation before AccountsService receives them. No password is placed
  in command arguments, logs, public state, or files. Password fields clear as
  soon as a request is submitted or the page closes.
- A newly created account is locked before password setup. If setup fails, it
  is kept locked and shown for repair; its home directory is never removed as
  compensation. An uncertain service failure is reported as uncertain.
- **Change my password** opens the system `passwd` prompts in the installed
  terminal. PAM checks the old password and applies the distribution's own
  password policy. Mellipi does not read those terminal prompts.
- Setting another account's password requires administrator authorization and
  unlocks that account, as specified by AccountsService. Encrypted keyrings keep
  their old password.
- Removing an account requires a separate confirmation and always keeps its
  files. The signed-in account, system users, users with logind sessions, and
  the last known unlocked administrator cannot be removed. Deletion fails
  closed if active sessions cannot be checked.

AccountsService exposes cached accounts; a remote or uncached directory account
may not appear. This is not an enterprise directory administration tool.

## Date and time

Choose from the system's installed time zones, enable/disable network time, or
set a UTC date and time explicitly. Manual time changes require automatic time
to be turned off first; Mellipi never turns it off as a side effect. UTC entry
avoids ambiguous or nonexistent local times around daylight-saving changes.
The display updates when the page is refreshed or a change completes.

The backend follows the installed AccountsService D-Bus interfaces
`org.freedesktop.Accounts.xml` and `org.freedesktop.Accounts.User.xml`, logind's
`ListSessions`, and the [systemd timedate1 interface](https://www.freedesktop.org/software/systemd/man/latest/org.freedesktop.timedate1.html).
Service authorization, account/password policy and clock operations remain owned
by the distribution. Tests substitute fake services; read-only API probes do
not certify real administrative changes on every distribution.
