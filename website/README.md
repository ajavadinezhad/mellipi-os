# Abstract website

Framework-free GitHub Pages site. Publish this directory as the root of the Pages artifact; keep its relative paths, and include the generated `apt/` repository alongside it when applicable. No build, external font, analytics, or service worker is required.

Set `site-config.json` at release time:

- `repositoryUrl`: public `https://github.com/OWNER/REPOSITORY` URL.
- `aptUrl`: HTTPS root containing the APT repository, archive key, and setup helper.
- `release`: published release number, without a leading `v`.
- `signingFingerprint`: full archive-key fingerprint; compare this to the actual exported key before publishing.
- `signingKeyPath`: exported public archive-key filename (informational configuration).
- `installerPath`: setup helper path relative to `aptUrl`; defaults to `install-update-source.sh`.

The page does not show actionable repository setup until a valid HTTPS address and full fingerprint are present. GitHub release and support links appear only after a real repository is configured. The desktop illustration is HTML/CSS and contains no user data; it is explicitly labeled as an illustration for assistive technology.

Serve locally with `python3 -m http.server 8765 --directory website` (configuration uses fetch, so opening as `file://` is not supported). View at 1440px, 768px and 375px widths; verify keyboard focus, copy failure feedback and reduced motion.
