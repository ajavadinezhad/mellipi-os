# Mellipi website

Framework-free website source. Edit files here, then stage them with the signed archive and matching sources in repository-root `public/`. The GitHub Pages workflow deploys only `public/`; do not deploy this source directory or the working tree directly. See [the release guide](../docs/update-repository.md). No build, external font, analytics, or service worker is required.

Set `site-config.json` at release time:

- `repositoryUrl`: public `https://github.com/OWNER/REPOSITORY` URL.
- `aptUrl`: HTTPS root containing the APT repository, archive key, and setup helper.
- `release`: published release number, without a leading `v`.
- `signingFingerprint`: full archive-key fingerprint; compare this to the actual exported key before publishing.
- `signingKeyPath`: exported public archive-key filename (informational configuration).
- `installerPath`: setup helper path relative to `aptUrl` (currently `install-update-source.sh`).

Repository setup is shown only when the publication config contains a valid HTTPS address and full fingerprint.

The hero, app tour, and theme preview use real screenshots from a private Mellipi Wayland session. Capture all views (launcher, Files, Quick Settings, Terminal, and desktop) for every ID in `themes.json`, at 1600 × 1000 with high contrast and the floating bottom taskbar set to Fit contents. The app tour shows closer views of the windows and links to the full screenshots. Use sample files and keep personal windows, notifications, and user data out. Save lossless WebP images under `assets/themes/` as `<theme>-<view>.webp`. When refreshing them, update the explicit dimensions and cache revision in the HTML and JavaScript together.

Serve locally with `python3 -m http.server 8765 --directory website` (configuration uses fetch, so opening as `file://` is not supported). View at 1440px, 768px and 375px widths; verify keyboard focus, copy failure feedback and reduced motion.

Optional live-image downloads stay hidden unless `site-config.json` contains a fully verified `liveImage` object. Add it only after the published ISO passes boot and installation acceptance. Fields: `url`, `sha256` (64 hexadecimal digits), `bytes` (positive integer), `checksumUrl`, `guideUrl`, and `secureBoot: false`. The image and checksum must be release assets in the same release under the official Mellipi OS GitHub repository. The guide must be in that repository’s docs or the official project Pages site. The current unsigned image requires Secure Boot disabled; do not set this field to true without implementing and validating a signed boot chain. Leave `liveImage` absent while an image is being built or tested.
