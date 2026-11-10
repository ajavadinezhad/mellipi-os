#!/bin/sh
# Enroll only the Mellipi archive, using a separately verified key fingerprint.
set -eu
url= fingerprint=
usage() { printf '%s\n' 'Usage: sudo sh install-update-source.sh --url https://OWNER.github.io/REPO/apt --fingerprint FULL_PRIMARY_FINGERPRINT' 'Adds an amd64 noble deb822 source with its own Signed-By key, then runs apt-get update.'; }
while [ "$#" -gt 0 ]; do
    case "$1" in
        --url) [ "$#" -ge 2 ] || { usage; exit 2; }; url=$2; shift 2 ;;
        --fingerprint) [ "$#" -ge 2 ] || { usage; exit 2; }; fingerprint=$2; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
done
[ -n "$url" ] && [ -n "$fingerprint" ] || { usage >&2; exit 2; }
# Restrict the URL to printable HTTPS characters without deb822 line breaks,
# credentials, query strings or fragments. No shell evaluation is used.
case "$url" in https://*) ;; *) echo 'An HTTPS archive URL is required.' >&2; exit 2 ;; esac
case "$url" in *[!A-Za-z0-9:/._~-]*|*'@'*|*'?'*|*'#'*) echo 'Unsupported archive URL.' >&2; exit 2 ;; esac
url=${url%/}
fingerprint=$(printf '%s' "$fingerprint" | tr '[:lower:]' '[:upper:]')
case "$fingerprint" in *[!A-F0-9]*) echo 'A complete hexadecimal primary fingerprint is required.' >&2; exit 2 ;; esac
[ "${#fingerprint}" -eq 40 ] || [ "${#fingerprint}" -eq 64 ] || { echo 'A complete primary fingerprint is required.' >&2; exit 2; }
[ "$(id -u)" -eq 0 ] || { echo 'Run this enrollment helper with sudo.' >&2; exit 1; }
[ "$(dpkg --print-architecture)" = amd64 ] || { echo 'This release supports amd64 only.' >&2; exit 1; }
# The binaries use Ubuntu 24.04 library ABIs. Mint's UBUNTU_CODENAME is accepted.
. /etc/os-release
[ "${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}" = noble ] || { echo 'This release requires an Ubuntu 24.04 (noble) compatible system.' >&2; exit 1; }
for program in curl gpg install apt-get; do command -v "$program" >/dev/null || { echo "Missing prerequisite: $program" >&2; exit 1; }; done
umask 077
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
mkdir "$tmp/gnupg"
chmod 700 "$tmp/gnupg"
curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --connect-timeout 15 --max-time 60 --output "$tmp/archive.gpg" "$url/mellipi-archive-keyring.gpg"
gpg --homedir "$tmp/gnupg" --batch --with-colons --show-keys "$tmp/archive.gpg" > "$tmp/key-info"
actual=$(awk -F: '$1=="fpr" {print $10;exit}' "$tmp/key-info")
count=$(awk -F: '$1=="pub" {n++} END {print n+0}' "$tmp/key-info")
[ "$actual" = "$fingerprint" ] && [ "$count" -eq 1 ] || { echo 'Archive key fingerprint mismatch; no source was installed.' >&2; exit 1; }
# Fetch and verify the current signed metadata before enrolling the key.
curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --connect-timeout 15 --max-time 60 --output "$tmp/InRelease" "$url/dists/noble/InRelease"
gpg --homedir "$tmp/gnupg" --batch --no-default-keyring --keyring "$tmp/archive.gpg" --verify "$tmp/InRelease"
key=/etc/apt/keyrings/mellipi-archive-keyring.gpg
source=/etc/apt/sources.list.d/mellipi.sources
printf 'Types: deb\nURIs: %s\nSuites: noble\nComponents: main\nArchitectures: amd64\nSigned-By: %s\n' "$url" "$key" > "$tmp/mellipi.sources"
if [ -e "$source" ] && ! cmp -s "$source" "$tmp/mellipi.sources"; then
    echo 'A different Mellipi source already exists; review it before replacing it.' >&2
    exit 1
fi
install -d -m 0755 /etc/apt/keyrings /etc/apt/sources.list.d
install -m 0644 "$tmp/archive.gpg" "$key.tmp"
mv -f "$key.tmp" "$key"
install -m 0644 "$tmp/mellipi.sources" "$source.tmp"
mv -f "$source.tmp" "$source"
printf '%s\n' 'Mellipi update source enrolled. Checking package indexes...'
apt-get update
