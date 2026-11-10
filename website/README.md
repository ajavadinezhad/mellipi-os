# Mellipi website

Framework-free website source. Edit files here, then stage them with the signed archive and matching sources in repository-root `public/`. The GitHub Pages workflow deploys only `public/`; do not deploy this source directory or the working tree directly. See [the release guide](../docs/update-repository.md). No build, external font, analytics, or service worker is required.

Set `site-config.json` at release time:

- `repositoryUrl`: public `https://github.com/OWNER/REPOSITORY` URL.
- `aptUrl`: HTTPS root containing the APT repository, archive key, and setup helper.
- `release`: published release number, without a leading `v`.
- `signingFingerprint`: full archive-key fingerprint; compare this to the actual exported key before publishing.
- `signingKeyPath`: exported public archive-key filename (informational configuration).
- `installerPath`: setup helper path relative to `aptUrl` (currently `install-update-source.sh`).

The page does not show actionable repository setup until a valid HTTPS address and full fingerprint are present. GitHub release and support links appear only after a real repository is configured. The hero illustration is HTML/CSS and is explicitly labeled as an illustration for assistive technology. The separate screenshot gallery uses actual captures from a clean private Mellipi session. Keep screenshot assets under `assets/`, in WebP format with explicit image dimensions; do not capture personal windows, notifications or user data. Stage the asset directory along with the website files.

Serve locally with `python3 -m http.server 8765 --directory website` (configuration uses fetch, so opening as `file://` is not supported). View at 1440px, 768px and 375px widths; verify keyboard focus, copy failure feedback and reduced motion.

Optional live-image downloads stay hidden unless `site-config.json` contains a fully verified `liveImage` object. Add it only after the published ISO passes boot and installation acceptance. Fields: `url`, `sha256` (64 hexadecimal digits), `bytes` (positive integer), `checksumUrl`, `guideUrl`, and `secureBoot: false`. The image and checksum must be release assets in the same release under the official Mellipi OS GitHub repository. The guide must be in that repository’s docs or the official project Pages site. The current unsigned image requires Secure Boot disabled; do not set this field to true without implementing and validating a signed boot chain. Leave `liveImage` absent while an image is being built or tested.
