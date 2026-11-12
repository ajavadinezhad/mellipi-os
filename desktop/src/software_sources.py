"""Package discovery and installation through configured Linux software sources."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from http.client import HTTPConnection, HTTPException
import json
import os
from pathlib import Path
import re
import socket
import subprocess
from urllib.parse import urlencode

APT_CACHE = '/usr/bin/apt-cache'
APT_GET = '/usr/bin/apt-get'
DPKG_QUERY = '/usr/bin/dpkg-query'
FLATPAK = '/usr/bin/flatpak'
SNAP = '/usr/bin/snap'
PKEXEC = '/usr/bin/pkexec'
SNAP_SOCKET = Path('/run/snapd.socket')
SOURCES = {'apt': 'System packages', 'flatpak': 'Flatpak', 'snap': 'Snap Store'}
RESULT_LIMIT = 50
APT_ID = re.compile(r'[a-z0-9][a-z0-9+.-]+')
FLATPAK_ID = re.compile(r'[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*){2,}')
FLATPAK_COMPONENT = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]*')
SNAP_ID = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?')


@dataclass(frozen=True)
class Package:
    source: str
    identifier: str
    name: str
    description: str
    version: str = ''
    scope: str = ''
    remote: str = ''
    branch: str = ''
    installed: bool = False
    classic: bool = False

    @property
    def origin(self):
        if self.source == 'flatpak':
            scope = 'For me' if self.scope == 'user' else 'System-wide'
            return f'{self.remote} · {scope}'
        return SOURCES[self.source]


@dataclass
class SourceResult:
    packages: list[Package] = field(default_factory=list)
    status: str = ''
    needs_refresh: bool = False


def executable(path):
    return os.path.isfile(path) and os.access(path, os.X_OK)


def run(arguments, timeout=15):
    env = dict(os.environ, LC_ALL='C.UTF-8', NO_COLOR='1', TERM='dumb')
    result = subprocess.run(arguments, stdin=subprocess.DEVNULL, capture_output=True,
                            encoding='utf-8', errors='replace', timeout=timeout, env=env)
    if result.returncode:
        if arguments[0] == PKEXEC and result.returncode in (126, 127):
            raise RuntimeError('Administrator authorization was canceled or unavailable.')
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(detail[-1600:] or 'The software source did not complete the request.')
    return result.stdout


def apt_search(query):
    if not (executable(APT_CACHE) and executable(DPKG_QUERY)):
        return SourceResult(status='APT is unavailable.')
    policy = run([APT_CACHE, 'policy'])
    if not any(line.rstrip().endswith(' Packages') for line in policy.splitlines()):
        return SourceResult(status='System packages need a first-time refresh.',
                            needs_refresh=executable(APT_GET) and executable(PKEXEC))
    if not query:
        return SourceResult(status='APT is ready.')
    installed = set()
    status_format = r'${binary:Package}\t${db:Status-Status}\n'
    for line in run([DPKG_QUERY, '-W', '-f=' + status_format]).splitlines():
        identifier, separator, status = line.partition('\t')
        if separator and status == 'installed':
            installed.add(identifier.split(':', 1)[0])
    packages = []
    for line in run([APT_CACHE, 'search', '--', re.escape(query)]).splitlines():
        identifier, separator, description = line.partition(' - ')
        if separator and APT_ID.fullmatch(identifier):
            packages.append(Package('apt', identifier, identifier, description,
                                    installed=identifier in installed))
    return SourceResult(rank(packages, query), 'APT is ready.')


def refresh_apt():
    return run([PKEXEC, APT_GET, '-o', 'APT::Update::Error-Mode=any', 'update'],
               timeout=None)


def flatpak_search(query):
    if not executable(FLATPAK):
        return SourceResult(status='Flatpak is not installed.')
    packages = []
    remotes = set()
    errors = []
    for scope in ('user', 'system'):
        prefix = [FLATPAK, '--' + scope]
        try:
            available = {}
            for line in run([*prefix, 'remotes', '--columns=name,options']).splitlines():
                remote, _, options = line.partition('\t')
                if FLATPAK_COMPONENT.fullmatch(remote) and 'disabled' not in options.split(','):
                    available[remote] = options
            remotes.update(available)
            if not available or not query:
                continue
            installed = {tuple(line.split('\t')) for line in
                         run([*prefix, 'list', '--app', '--columns=application,branch']).splitlines()}
            rows = run([*prefix, 'search',
                        '--columns=name:f,description:f,application:f,version:f,branch:f,remotes:f',
                        '--', query], timeout=20)
            app_refs = set()
            for line in run([*prefix, 'remote-ls', '--cached', '--app',
                             '--columns=origin,application,branch'], timeout=15).splitlines():
                app_refs.add(tuple(line.split('\t')))
            for line in rows.splitlines():
                fields = line.split('\t')
                if len(fields) != 6:
                    continue
                name, description, identifier, version, branch, origins = fields
                if not (FLATPAK_ID.fullmatch(identifier) and FLATPAK_COMPONENT.fullmatch(branch)):
                    continue
                for remote in re.split(r'[, ]+', origins):
                    if remote in available and (remote, identifier, branch) in app_refs:
                        packages.append(Package('flatpak', identifier, name or identifier, description,
                                                version, scope, remote, branch,
                                                (identifier, branch) in installed))
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
            errors.append(f'{scope.title()} Flatpak: {friendly_error(error)}')
    if errors:
        status = ' '.join(errors)
    elif remotes:
        status = 'Flatpak remotes: ' + ', '.join(sorted(remotes))
    else:
        status = 'No Flatpak remote is configured.'
    return SourceResult(rank(packages, query), status)


class SnapConnection(HTTPConnection):
    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(str(SNAP_SOCKET))
        except OSError:
            sock.close()
            raise
        self.sock = sock


def snap_request(path, **parameters):
    connection = SnapConnection('localhost', timeout=12)
    try:
        if parameters:
            path += '?' + urlencode(parameters)
        connection.request('GET', path)
        response = connection.getresponse()
        payload = response.read(4 * 1024 * 1024 + 1)
        if len(payload) > 4 * 1024 * 1024:
            raise RuntimeError('The Snap Store response was too large.')
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise RuntimeError('The Snap Store returned an unexpected response.')
        if response.status != 200:
            result = data.get('result')
            message = result.get('message') if isinstance(result, dict) else None
            raise RuntimeError(message or f'Snap Store request failed ({response.status}).')
        result = data.get('result')
        if not isinstance(result, list):
            raise RuntimeError('The Snap Store returned an unexpected response.')
        return [row for row in result if isinstance(row, dict)]
    finally:
        connection.close()


def snap_search(query):
    if not (executable(SNAP) and SNAP_SOCKET.is_socket()):
        return SourceResult(status='Snap is not configured.')
    installed = {row['name'] for row in snap_request('/v2/snaps') if isinstance(row.get('name'), str)}
    if not query:
        return SourceResult(status='Snap is ready.')
    packages = []
    for row in snap_request('/v2/find', q=query):
        identifier = row.get('name', '')
        if isinstance(identifier, str) and SNAP_ID.fullmatch(identifier):
            title, summary, version = (row.get(key) for key in ('title', 'summary', 'version'))
            packages.append(Package('snap', identifier, title if isinstance(title, str) and title else identifier,
                                    summary if isinstance(summary, str) else '',
                                    version if isinstance(version, str) else '',
                                    installed=identifier in installed,
                                    classic=row.get('confinement') == 'classic'))
    return SourceResult(rank(packages, query), 'Snap is ready.')


def rank(packages, query, limit=RESULT_LIMIT):
    query = query.casefold()
    def relevance(package):
        name = package.name.casefold()
        identifier = package.identifier.casefold()
        return (query not in (name, identifier, identifier.rsplit('.', 1)[-1]), not name.startswith(query),
                query not in name, len(name), name)
    return sorted(dict.fromkeys(packages), key=relevance)[:limit]


def friendly_error(error):
    if isinstance(error, (TimeoutError, subprocess.TimeoutExpired)):
        return 'The software source timed out. Try again.'
    if isinstance(error, json.JSONDecodeError):
        return 'The software source returned an invalid response.'
    return str(error)


def search(query, sources=SOURCES):
    query = query.strip()
    if len(query) > 120:
        raise ValueError('Search terms must be 120 characters or fewer.')
    adapters = {'apt': apt_search, 'flatpak': flatpak_search, 'snap': snap_search}
    with ThreadPoolExecutor(max_workers=len(SOURCES)) as pool:
        searches = {source: pool.submit(adapters[source], query) for source in sources}
        results = {}
        for source, future in searches.items():
            try:
                results[source] = future.result()
            except (RuntimeError, OSError, HTTPException, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
                results[source] = SourceResult(status=friendly_error(error))
        return results


def install_arguments(package):
    if package.installed:
        raise ValueError('This software is already installed.')
    if package.source == 'apt' and APT_ID.fullmatch(package.identifier):
        # Anchor and escape the name: apt-get otherwise interprets missing
        # names containing a dot as a substring regex.
        exact = '^' + re.escape(package.identifier) + '$'
        return [PKEXEC, APT_GET, '-y', '--no-remove', 'install', '--', exact]
    if (package.source == 'flatpak' and package.scope in ('user', 'system')
            and FLATPAK_ID.fullmatch(package.identifier)
            and FLATPAK_COMPONENT.fullmatch(package.remote)
            and FLATPAK_COMPONENT.fullmatch(package.branch)):
        ref = f'{package.identifier}//{package.branch}'
        return [FLATPAK, '--' + package.scope, 'install', '--app', '--assumeyes',
                '--', package.remote, ref]
    if package.source == 'snap' and SNAP_ID.fullmatch(package.identifier) and not package.classic:
        return [PKEXEC, SNAP, 'install', '--', package.identifier]
    raise ValueError('This package cannot be installed from Software.')


def install(package):
    # A package transaction belongs to its system manager. Let it finish even
    # when a download or the administrator prompt takes longer than a search.
    output = run(install_arguments(package), timeout=None)
    if package.source == 'apt':
        result = run([DPKG_QUERY, '-W', '-f=${db:Status-Status}', '--', package.identifier])
        if result.strip() != 'installed':
            raise RuntimeError('APT finished without installing the selected package.')
    return output
