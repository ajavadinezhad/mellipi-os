#!/usr/bin/env python3
"""Stage reviewed website files, optionally building a signed APT release too."""
import argparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import gzip
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEBSITE_FILES = ('index.html', 'style.css', 'theme-init.js', 'site.js', 'site-config.json', 'themes.json', 'favicon.svg')
MANIFEST = 'publication-manifest.json'


def file_record(path):
    digest = hashlib.sha256()
    tail = b''
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            scan = tail + chunk
            if b'-----BEGIN PGP PRIVATE KEY BLOCK-----' in scan or b'-----BEGIN OPENSSH PRIVATE KEY-----' in scan:
                raise ValueError('Private key found in public output: ' + str(path))
            tail = scan[-64:]
            digest.update(chunk)
    return {'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}


def records(directory):
    result = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ValueError('Public output contains a symlink: ' + str(path))
        if path.is_file() and path != directory / MANIFEST:
            if path.stat().st_nlink != 1:
                raise ValueError('Public output contains a hard link: ' + str(path))
            result[str(path.relative_to(directory))] = file_record(path)
    return result


def checked_file(root, relative, size, checksum):
    name = Path(relative)
    if name.is_absolute() or '..' in name.parts or not re.fullmatch(r'[a-f0-9]{64}', checksum):
        raise ValueError('Invalid signed archive path/hash')
    path = root / name
    if not path.is_file() or path.is_symlink() or path.stat().st_size != int(size) or file_record(path)['sha256'] != checksum:
        raise ValueError('Signed archive payload mismatch: ' + str(path))
    return path


def validate_existing(output):
    """Authenticate the existing archive and check its complete staged manifest."""
    if not output.is_dir() or not (output / MANIFEST).is_file():
        raise ValueError('--site-only requires an existing release and publication manifest')
    previous = json.loads((output / MANIFEST).read_text())
    current = records(output)
    if previous.get('files') != current:
        raise ValueError('Existing publication manifest does not match its files; inspect the release before refreshing the site')
    archive = output / 'apt'
    metadata = json.loads((archive / 'archive-key.json').read_text())
    fingerprint = metadata.get('fingerprint', '')
    if not re.fullmatch(r'[A-Fa-f0-9]{40}', fingerprint) or metadata.get('suite') != 'noble':
        raise ValueError('Invalid existing archive identity')
    if previous.get('signing_fingerprint', '').upper() != fingerprint.upper():
        raise ValueError('Existing publication/archive fingerprint mismatch')
    key = archive / ('mellipi-archive-keyring.gpg' if (archive/'mellipi-archive-keyring.gpg').is_file() else 'abstract-archive-keyring.gpg')
    release_root = archive / 'dists/noble'
    release = (release_root / 'Release').read_bytes()
    with tempfile.TemporaryDirectory(prefix='abstract-public-verify-') as directory:
        command = ['gpg', '--homedir', directory, '--batch', '--with-colons', '--show-keys', str(key)]
        info = subprocess.run(command, check=True, capture_output=True, text=True).stdout.splitlines()
        public_keys = [line for line in info if line.startswith('pub:')]
        prints = [line.split(':')[9] for line in info if line.startswith('fpr:')]
        if len(public_keys) != 1 or not prints or prints[0].upper() != fingerprint.upper():
            raise ValueError('Existing public archive key fingerprint mismatch')
        verify = ['gpgv', '--homedir', directory, '--keyring', str(key)]
        verified = subprocess.run([*verify, '--output', '-', str(release_root / 'InRelease')], check=True, capture_output=True).stdout
        subprocess.run([*verify, str(release_root / 'Release.gpg'), str(release_root / 'Release')], check=True, capture_output=True)
        if verified != release:
            raise ValueError('InRelease and detached Release content differ')
    text = release.decode()
    expiry = re.search(r'^Valid-Until: (.+)$', text, re.M)
    if not expiry or parsedate_to_datetime(expiry[1]) <= datetime.now(timezone.utc):
        raise ValueError('Existing APT metadata has expired; renew it with a signed release operation')
    hashes = re.search(r'^SHA256:\n((?: .+\n)+)', text, re.M)
    if not hashes:
        raise ValueError('Existing signed release has no index hashes')
    for line in hashes[1].splitlines():
        checksum, size, name = line.split()
        checked_file(release_root, name, size, checksum)
    paragraphs = gzip.decompress((release_root / 'main/binary-amd64/Packages.gz').read_bytes()).decode().strip().split('\n\n')
    if not paragraphs or not paragraphs[0]:
        raise ValueError('Existing package archive is empty')
    for paragraph in paragraphs:
        fields = dict(line.split(': ', 1) for line in paragraph.splitlines() if ': ' in line and not line[0].isspace())
        if not fields.get('Package', '').startswith(('mellipi-','abstract-')) or fields.get('Architecture') not in ('amd64', 'all'):
            raise ValueError('Unexpected package in existing Mellipi archive')
        checked_file(archive, fields['Filename'], fields['Size'], fields['SHA256'])
    return fingerprint.upper(), current


def export_themes():
    subprocess.run(['python3', str(ROOT / 'tools/export-website-themes.py'), '--output', str(ROOT / 'website/themes.json')], check=True)


def prepare_website(stage, fingerprint):
    """Validate all mutable site content before changing the publication tree."""
    export_themes()
    for name in WEBSITE_FILES:
        source = ROOT / 'website' / name
        if not source.is_file() or source.is_symlink():
            raise ValueError('Missing or symlinked website file: ' + str(source))
        shutil.copy2(source, stage / name)
    config = json.loads((stage / 'site-config.json').read_text())
    if config.get('signingFingerprint', '').upper() != fingerprint:
        raise ValueError('Website/archive signing fingerprints differ')
    content = (stage / 'index.html').read_text()
    for name in ('style.css', 'theme-init.js', 'site.js'):
        version = file_record(stage / name)['sha256'][:12]
        content = content.replace('"' + name + '"', '"' + name + '?v=' + version + '"')
    (stage / 'index.html').write_text(content)
    assets = ROOT / 'website/assets'
    if assets.is_symlink() or any(path.is_symlink() for path in assets.rglob('*')):
        raise ValueError('Website assets must not contain symlinks')
    if assets.is_dir():
        shutil.copytree(assets, stage / 'assets')
    (stage / '.nojekyll').write_text('')
    records(stage)


def assemble(output, packages=None, key_home=None, fingerprint=None, sources=(), site_only=False):
    raw_output = Path(output)
    if raw_output.is_symlink():
        raise ValueError('Output must not be a symlink')
    output = raw_output.resolve()
    if output == ROOT or ROOT in output.parents and output.relative_to(ROOT).parts[0] not in ('public', 'dist'):
        raise ValueError('Choose public/ or dist/ output, or a dedicated path outside the project')
    if site_only:
        if packages is not None or key_home is not None or fingerprint is not None or sources:
            raise ValueError('--site-only cannot use package, signing or source inputs')
        fingerprint, original = validate_existing(output)
    else:
        if not packages or key_home is None or not fingerprint or not re.fullmatch(r'[A-Fa-f0-9]{40}', fingerprint):
            raise ValueError('A full release requires packages, a signing home and a full signing fingerprint')
        fingerprint = fingerprint.upper()
        original = None
    with tempfile.TemporaryDirectory(prefix='abstract-website-stage-') as directory:
        stage = Path(directory)
        prepare_website(stage, fingerprint)
        output.mkdir(parents=True, exist_ok=True)
        for name in (*WEBSITE_FILES, '.nojekyll'):
            shutil.copy2(stage / name, output / name)
        assets = output / 'assets'
        if assets.exists():
            shutil.rmtree(assets)
        if (stage / 'assets').is_dir():
            shutil.copytree(stage / 'assets', assets)
    if not site_only:
        subprocess.run(['python3', str(ROOT / 'tools/build-apt-repository.py'), '--output', str(output / 'apt'), '--packages', *[str(Path(p).resolve()) for p in packages], '--gnupg-home', str(Path(key_home).resolve()), '--signing-key', fingerprint], check=True)
        shutil.copy2(ROOT / 'tools/install-update-source.sh', output / 'apt/install-update-source.sh')
        for source in map(Path, sources):
            if not source.is_file() or source.is_symlink() or not source.name.endswith(('.tar.gz', '.tar.xz', '.json', '.md')):
                raise ValueError('Only reviewed source archives/manifests may be published')
            target = output / 'sources' / source.name
            target.parent.mkdir(exist_ok=True)
            shutil.copy2(source, target)
    files = records(output)
    if site_only:
        protected = lambda values: {name: value for name, value in values.items() if name.startswith(('apt/', 'sources/'))}
        if protected(files) != protected(original):
            raise ValueError('Site-only staging changed protected archive/source files')
    published_sources = sorted(name for name in files if name.startswith('sources/'))
    manifest = {'release': json.loads((output / 'site-config.json').read_text())['release'], 'signing_fingerprint': fingerprint, 'sources': published_sources, 'files': files}
    (output / MANIFEST).write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'public_directory': str(output), 'mode': 'site-only' if site_only else 'release', 'files': len(files), 'bytes': sum(value['bytes'] for value in files.values())}))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'public')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--site-only', action='store_true', help='Refresh only website files/assets and manifest, preserving the existing verified APT archive and sources')
    mode.add_argument('--packages', type=Path, nargs='+')
    parser.add_argument('--gnupg-home', type=Path)
    parser.add_argument('--signing-key')
    parser.add_argument('--sources', type=Path, nargs='*', default=None)
    args = parser.parse_args()
    if args.site_only and (args.gnupg_home is not None or args.signing_key is not None or args.sources is not None):
        parser.error('--site-only cannot be combined with signing or source inputs')
    if not args.site_only and (args.gnupg_home is None or args.signing_key is None):
        parser.error('--packages requires --gnupg-home and --signing-key')
    assemble(args.output, args.packages, args.gnupg_home, args.signing_key, args.sources or (), args.site_only)


if __name__ == '__main__':
    main()
