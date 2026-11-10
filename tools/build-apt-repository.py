#!/usr/bin/env python3
"""Build a signed, static Abstract APT archive; the signing key stays external.

The output directory is dedicated to the archive. Existing pool versions are
retained and immutable. Publish the complete resulting directory atomically.
"""
import argparse
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def run(args, **kwargs):
    return subprocess.run([str(value) for value in args], check=True, **kwargs)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def package_fields(path):
    result = run(['dpkg-deb', '--field', path], capture_output=True, text=True).stdout
    fields = {}
    for line in result.splitlines():
        if line and not line[0].isspace() and ':' in line:
            name, value = line.split(':', 1)
            fields[name] = value.strip()
    if not re.fullmatch(r'abstract-[a-z0-9][a-z0-9+.-]*', fields.get('Package', '')):
        raise ValueError('Only Abstract packages may be published in this archive')
    if fields.get('Architecture') not in ('amd64', 'all'):
        raise ValueError('Only amd64 and architecture-independent packages are supported')
    if not re.fullmatch(r'[0-9][A-Za-z0-9.+:~\-]*', fields.get('Version', '')):
        raise ValueError('Invalid Debian package version')
    return fields


def fingerprint(home, key):
    if not re.fullmatch(r'[A-Fa-f0-9]{40}|[A-Fa-f0-9]{64}', key):
        raise ValueError('Use the complete signing-key fingerprint')
    result = run(['gpg', '--homedir', home, '--batch', '--with-colons', '--fingerprint', '--list-keys', key], capture_output=True, text=True).stdout
    pubs = [line for line in result.splitlines() if line.startswith('pub:')]
    prints = [line.split(':')[9] for line in result.splitlines() if line.startswith('fpr:')]
    if len(pubs) != 1 or not prints or prints[0].upper() != key.upper():
        raise ValueError('Signing key fingerprint is not an exact primary-key match')
    return key.upper()


def build(output, packages, home, key, suite='noble', valid_days=90, now=None):
    output, home = Path(output).absolute(), Path(home).resolve()
    if output.is_symlink():
        raise ValueError('Archive output must not be a symbolic link')
    output = output.resolve()
    if output.exists() and not output.is_dir():
        raise ValueError('Archive output must be a directory')
    if output.exists() and any(path.is_symlink() for path in output.rglob('*')):
        raise ValueError('Archive output must not contain symbolic links')
    if suite != 'noble':
        raise ValueError('This binary release supports only the noble suite')
    if not 1 <= valid_days <= 180:
        raise ValueError('Metadata validity must be between 1 and 180 days')
    if output.is_symlink() or output == home or output in home.parents:
        raise ValueError('Signing home must be outside the published archive')
    if not packages:
        raise ValueError('At least one package is required')
    key = fingerprint(home, key)
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.abstract-apt-', dir=output.parent))
    backup = None
    try:
        pool = stage / 'pool/main'
        pool.mkdir(parents=True)
        old_pool = output / 'pool'
        if old_pool.exists():
            for path in old_pool.rglob('*'):
                if path.is_symlink():
                    raise ValueError('Archive pool must not contain symbolic links')
            shutil.copytree(old_pool, stage / 'pool', dirs_exist_ok=True)
        for source in map(Path, packages):
            fields = package_fields(source)
            filename = '{Package}_{Version}_{Architecture}.deb'.format(**fields)
            destination = pool / fields['Package'][0] / fields['Package'] / filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and digest(destination) != digest(source):
                raise ValueError('Published package versions are immutable: ' + filename)
            if not destination.exists():
                shutil.copyfile(source, destination)
        # dpkg's multiversion scanner supplies canonical control paragraphs and
        # SHA256 for every retained release, including Architecture: all.
        scan = run(['dpkg-scanpackages', '--multiversion', 'pool', '/dev/null'], cwd=stage, capture_output=True, text=True).stdout
        for path in (stage / 'pool').rglob('*.deb'):
            package_fields(path)
        directory = stage / 'dists' / suite / 'main/binary-amd64'
        directory.mkdir(parents=True)
        (directory / 'Packages').write_text(scan)
        (directory / 'Packages.gz').write_bytes(gzip.compress(scan.encode(), mtime=0))
        release_root = stage / 'dists' / suite
        indices = sorted(path for path in release_root.rglob('*') if path.is_file())
        release = ('Origin: Abstract\nLabel: Abstract\nSuite: {suite}\nCodename: {suite}\n'
                   'Architectures: amd64\nComponents: main\nDescription: Abstract desktop updates\n'
                   'Date: {date}\nValid-Until: {expiry}\nAcquire-By-Hash: yes\nSHA256:\n').format(
                       suite=suite, date=format_datetime(now, usegmt=True),
                       expiry=format_datetime(now + timedelta(days=valid_days), usegmt=True))
        for path in indices:
            sha = digest(path)
            release += ' {} {} {}\n'.format(sha, path.stat().st_size, path.relative_to(release_root).as_posix())
            by_hash = path.parent / 'by-hash/SHA256' / sha
            by_hash.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, by_hash)
        # Keep older index hashes for clients whose metadata predates this build.
        if output.exists():
            for old in (output / 'dists' / suite).glob('*/binary-amd64/by-hash/SHA256/*'):
                if old.is_symlink() or not old.is_file() or old.name != digest(old):
                    raise ValueError('Invalid retained by-hash index')
                dest = release_root / old.relative_to(output / 'dists' / suite)
                if not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(old, dest)
        (release_root / 'Release').write_text(release)
        command = ['gpg', '--homedir', home, '--batch', '--yes', '--local-user', key, '--digest-algo', 'SHA256']
        run([*command, '--output', release_root / 'InRelease', '--clearsign', release_root / 'Release'])
        run([*command, '--output', release_root / 'Release.gpg', '--armor', '--detach-sign', release_root / 'Release'])
        with (stage / 'abstract-archive-keyring.gpg').open('wb') as target:
            run(['gpg', '--homedir', home, '--batch', '--export-options', 'export-minimal', '--export', key], stdout=target)
        with (stage / 'abstract-archive-keyring.asc').open('wb') as target:
            run(['gpg', '--homedir', home, '--batch', '--armor', '--export-options', 'export-minimal', '--export', key], stdout=target)
        metadata = {'fingerprint': key, 'suite': suite, 'architectures': ['amd64'], 'valid_until': format_datetime(now + timedelta(days=valid_days), usegmt=True)}
        (stage / 'archive-key.json').write_text(json.dumps(metadata, indent=2) + '\n')
        (stage / '.nojekyll').touch()
        for path in stage.rglob('*'):
            path.chmod(0o755 if path.is_dir() else 0o644)
        stage.chmod(0o755)
        if output.exists():
            backup = Path(tempfile.mkdtemp(prefix='.abstract-apt-old-', dir=output.parent))
            backup.rmdir()
            output.rename(backup)
        try:
            stage.rename(output)
        except BaseException:
            if backup is not None:
                backup.rename(output)
                backup = None
            raise
        return metadata
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        if backup is not None and backup.exists():
            shutil.rmtree(backup)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--packages', required=True, nargs='+', type=Path)
    parser.add_argument('--gnupg-home', required=True, type=Path)
    parser.add_argument('--signing-key', required=True)
    parser.add_argument('--suite', default='noble', choices=['noble'])
    parser.add_argument('--valid-days', type=int, default=90)
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.packages, args.gnupg_home, args.signing_key, args.suite, args.valid_days)))


if __name__ == '__main__':
    main()
