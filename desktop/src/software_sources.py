"""Package discovery and installation through configured Linux software sources."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from http.client import HTTPConnection, HTTPException
import json
import os
from pathlib import Path
import re
import selectors
import socket
import subprocess
from urllib.parse import urlencode

APT_CACHE = '/usr/bin/apt-cache'
APT_GET = '/usr/bin/apt-get'
APPSTREAM_CLI = '/usr/bin/appstreamcli'
DPKG_QUERY = '/usr/bin/dpkg-query'
FLATPAK = '/usr/bin/flatpak'
SNAP = '/usr/bin/snap'
PKEXEC = '/usr/bin/pkexec'
SNAP_SOCKET = Path('/run/snapd.socket')
SOURCES = {'apt': 'System packages', 'flatpak': 'Flatpak', 'snap': 'Snap Store'}
BROWSE_CATEGORIES = {
    'AudioVideo': 'Audio & video', 'Development': 'Development', 'Education': 'Education',
    'Game': 'Games', 'Graphics': 'Graphics', 'Network': 'Internet', 'Office': 'Office',
    'Utility': 'Utilities',
}
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
    update_version: str = ''

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
    check_failed: bool = False
    checked: bool = False


def executable(path):
    return os.path.isfile(path) and os.access(path, os.X_OK)


def run(arguments, timeout=15):
    env = dict(os.environ, LC_ALL='C.UTF-8', NO_COLOR='1', TERM='dumb')
    result = subprocess.run(arguments, stdin=subprocess.DEVNULL, capture_output=True,
                            encoding='utf-8', errors='replace', timeout=timeout, env=env)
    if result.returncode:
        if arguments[0] == PKEXEC and result.returncode in (126, 127):
            raise AuthorizationDeclined('Administrator authorization was canceled or unavailable.')
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(detail[-1600:] or 'The software source did not complete the request.')
    return result.stdout


class AuthorizationDeclined(RuntimeError):
    """pkexec exited without granting authorisation."""


def transaction(arguments, observe=None):
    """Report package phases without canceling or timing out a live write."""
    if observe is None:
        return run(arguments, timeout=None)

    waiting = arguments[0] == PKEXEC
    if waiting:
        observe('authorization')
    elif arguments[0] == FLATPAK and '--system' in arguments:
        # The Flatpak service can request authorization at several points.
        observe('system-flatpak')
    else:
        observe('applying')

    # pkexec reports its own errors on stderr and execs (not forks) its target.
    # Observe that transition where /proc permits it; stdout from the target
    # also distinguishes it from the authorization phase. Neither is used as a
    # security decision. In particular, only the trusted prompt cancels auth.
    env = dict(os.environ, LC_ALL='C.UTF-8', NO_COLOR='1', TERM='dumb')
    with subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env=env) as process, selectors.DefaultSelector() as selector:
        output = {process.stdout: bytearray(), process.stderr: bytearray()}
        for stream in output:
            selector.register(stream, selectors.EVENT_READ)
        expected = Path(arguments[1]).name[:15] if waiting else ''
        while selector.get_map():
            if waiting:
                try:
                    applying = Path(f'/proc/{process.pid}/comm').read_text().strip() == expected
                except OSError:
                    applying = False
                if applying:
                    waiting = False
                    observe('applying')
            for key, _ in selector.select(timeout=.25 if waiting else None):
                stream = key.fileobj
                chunk = os.read(stream.fileno(), 8192)
                if not chunk:
                    selector.unregister(stream)
                    continue
                if waiting and stream is process.stdout:
                    waiting = False
                    observe('applying')
                output[stream].extend(chunk)
                del output[stream][:-8192]
        code = process.wait()
    if code in (126, 127) and arguments[0] == PKEXEC and waiting:
        raise AuthorizationDeclined('Administrator authorization was canceled or unavailable.')
    if code:
        detail = (output[process.stderr] or output[process.stdout]).decode('utf-8', errors='replace').strip()
        raise RuntimeError(detail[-1600:] or 'The software source did not complete the request.')
    return output[process.stdout].decode('utf-8', errors='replace')


MELLIPI_COMPATIBILITY = {'abstract-shell': 'Mellipi Shell compatibility',
                        'abstract-desktop': 'Mellipi Desktop compatibility'}


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
        if separator and identifier not in MELLIPI_COMPATIBILITY and APT_ID.fullmatch(identifier):
            packages.append(Package('apt', identifier, identifier, description,
                                    installed=identifier in installed))
    return SourceResult(rank(packages, query), 'APT is ready.')


def refresh_apt(observe=None):
    return transaction([PKEXEC, APT_GET, '-o', 'APT::Update::Error-Mode=any', 'update'], observe)



def browse_system_apps(category, query='', on_result=None):
    """Use the local AppStream catalog; installation still goes through APT."""
    if category not in BROWSE_CATEGORIES:
        raise ValueError('Unknown software category.')
    if not (executable(APPSTREAM_CLI) and executable(DPKG_QUERY) and executable(APT_CACHE)):
        result = SourceResult(status='System app browsing requires AppStream and APT.')
    else:
        policy = apt_search('')
        if policy.status != 'APT is ready.':
            result = policy
        else:
            combined = run([APPSTREAM_CLI, 'list-categories', category])
            inventory = {p.identifier.partition(':')[0]: p.version for p in apt_installed().packages}
            packages = {}
            words = query.casefold()
            for entry in combined.split('\n---\n'):
                fields = {}
                for line in entry.splitlines():
                    key, delimiter, value = line.partition(': ')
                    if delimiter and key in ('Identifier', 'Name', 'Summary', 'Package'):
                        fields.setdefault(key, value.strip())
                identifier = fields.get('Package', '')
                if not (fields.get('Identifier', '').endswith(' [desktop-application]')
                        and APT_ID.fullmatch(identifier)):
                    continue
                name, summary = fields.get('Name') or identifier, fields.get('Summary', '')
                if words and words not in f'{name}\n{identifier}\n{summary}'.casefold():
                    continue
                packages.setdefault(identifier, Package(
                    'apt', identifier, name, summary, inventory.get(identifier, ''),
                    installed=identifier in inventory))
            result = SourceResult(
                sorted(packages.values(), key=lambda p: (p.name.casefold(), p.identifier)),
                'Browsing the local system app catalog.' if packages
                else 'No matching apps in the local system catalog.')
    if on_result:
        on_result('apt', result)
    return {'apt': result}


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


def search(query, sources=SOURCES, on_result=None):
    query = query.strip()
    if len(query) > 120:
        raise ValueError('Search terms must be 120 characters or fewer.')
    adapters = {'apt': apt_search, 'flatpak': flatpak_search, 'snap': snap_search}
    return _query_sources(adapters, sources, on_result, query)


def _query_sources(adapters, sources, on_result, *arguments, match='', update_check=False):
    with ThreadPoolExecutor(max_workers=len(SOURCES)) as pool:
        searches = {pool.submit(adapters[source], *arguments): source for source in sources}
        results = {}
        for future in as_completed(searches):
            source = searches[future]
            try:
                result = future.result()
                if match:
                    result.packages = [p for p in result.packages if match in
                                       (p.name + '\n' + p.identifier + '\n' + p.description).casefold()]
                results[source] = result
            except (RuntimeError, OSError, HTTPException, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
                prefix = f'{SOURCES[source]}: ' if update_check else ''
                results[source] = SourceResult(status=prefix + friendly_error(error), check_failed=update_check)
            if on_result:on_result(source, results[source])
        return results



def apt_installed():
    if not executable(DPKG_QUERY):
        return SourceResult(status='APT inventory is unavailable.')
    fields = r'${binary:Package}\t${db:Status-Status}\t${Version}\t${binary:Synopsis}\n'
    packages = []
    for line in run([DPKG_QUERY, '-W', '-f=' + fields]).splitlines():
        row = line.split('\t', 3)
        if len(row) != 4:
            continue
        identifier, status, version, summary = row
        name, separator, arch = identifier.partition(':')
        if status == 'installed' and name not in MELLIPI_COMPATIBILITY and APT_ID.fullmatch(name) and (
                not separator or re.fullmatch(r'[a-z0-9-]+', arch)):
            packages.append(Package('apt', identifier, name, summary, version, installed=True))
    return SourceResult(packages, f'APT: {len(packages)} installed.')


def flatpak_installed():
    if not executable(FLATPAK):
        return SourceResult(status='Flatpak is not installed.')
    packages, errors = [], []
    for scope in ('user', 'system'):
        try:
            rows = run([FLATPAK, '--' + scope, 'list', '--app',
                        '--columns=application:f,name:f,version:f,branch:f,origin:f'])
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
            errors.append(f'{scope.title()} Flatpak: {friendly_error(error)}')
            continue
        for line in rows.splitlines():
            row = line.split('\t')
            if len(row) != 5:
                continue
            identifier, name, version, branch, remote = row
            if FLATPAK_ID.fullmatch(identifier) and FLATPAK_COMPONENT.fullmatch(branch):
                packages.append(Package('flatpak', identifier, name or identifier, '',
                                        version, scope, remote or 'Flatpak', branch, installed=True))
    return SourceResult(packages, ' '.join([f'Flatpak: {len(packages)} installed.', *errors]))


def snap_installed():
    if not (executable(SNAP) and SNAP_SOCKET.is_socket()):
        return SourceResult(status='Snap is not configured.')
    packages = []
    for row in snap_request('/v2/snaps'):
        identifier = row.get('name')
        if not isinstance(identifier, str) or not SNAP_ID.fullmatch(identifier):
            continue
        title, summary, version = (row.get(key) for key in ('title', 'summary', 'version'))
        packages.append(Package('snap', identifier, title if isinstance(title, str) and title else identifier,
                                summary if isinstance(summary, str) else '',
                                version if isinstance(version, str) else '', installed=True))
    return SourceResult(packages, f'Snap: {len(packages)} installed.')


def installed_software(query, sources=SOURCES, on_result=None):
    """List local package-manager state without refresh, network searches or authorization."""
    query = query.strip().casefold()
    if len(query) > 120:
        raise ValueError('Search terms must be 120 characters or fewer.')
    adapters = {'apt': apt_installed, 'flatpak': flatpak_installed, 'snap': snap_installed}
    return _query_sources(adapters, sources, on_result, match=query)

def apt_updates():
    if not (executable(APT_GET) and executable(APT_CACHE)):
        return SourceResult(status='APT is unavailable.')
    if not any(line.rstrip().endswith(' Packages')
               for line in run([APT_CACHE, 'policy']).splitlines()):
        return SourceResult(status='APT: refresh the system package index to check for updates.',
                            needs_refresh=True, check_failed=True)
    # Simulation uses the configured policy and local signed indexes. It does not
    # take package locks, prompt for administrator access, or start a transaction.
    rows = run([APT_GET, '--simulate', '--no-remove',
                '-o', 'APT::Get::Show-User-Simulation-Note=false', 'upgrade'], timeout=20)
    packages = []
    for row in rows.splitlines():
        match = re.match(r'^Inst (\S+) \[([^\]]+)\] \((\S+)', row)
        if match and APT_INSTALLED_ID.fullmatch(match[1]):
            identifier, installed, candidate = match.groups()
            name=MELLIPI_COMPATIBILITY.get(identifier.split(':',1)[0],identifier)
            packages.append(Package('apt', identifier, name, '', installed,
                                    installed=True, update_version=candidate))
    return SourceResult(packages, f'APT: {len(packages)} eligible from the local index.', checked=True)


def flatpak_updates():
    if not executable(FLATPAK):
        return SourceResult(status='Flatpak is not installed.')
    packages, errors = [], []
    checked = False
    for scope in ('user', 'system'):
        try:
            rows = run([FLATPAK, '--' + scope, 'remote-ls', '--app', '--updates',
                        '--columns=application:f,name:f,version:f,branch:f,origin:f'], timeout=15)
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
            errors.append(f'{scope.title()} Flatpak: {friendly_error(error)}')
            continue
        checked = True
        seen = set()
        for line in rows.splitlines():
            fields = line.split('\t')
            if len(fields) != 5:
                continue
            identifier, name, version, branch, remote = fields
            if not (FLATPAK_ID.fullmatch(identifier) and FLATPAK_COMPONENT.fullmatch(branch)
                    and FLATPAK_COMPONENT.fullmatch(remote)):
                continue
            if (identifier, branch) in seen:
                continue
            seen.add((identifier, branch))
            packages.append(Package('flatpak', identifier, name or identifier, '',
                                    scope=scope, remote=remote, branch=branch,
                                    installed=True, update_version=version))
    return SourceResult(packages, ' '.join([f'Flatpak: {len(packages)} available.', *errors]),
                        check_failed=bool(errors), checked=checked)


def snap_updates():
    if not (executable(SNAP) and SNAP_SOCKET.is_socket()):
        return SourceResult(status='Snap is not configured.')
    packages = []
    for row in snap_request('/v2/find', select='refresh'):
        identifier = row.get('name')
        if not isinstance(identifier, str) or not SNAP_ID.fullmatch(identifier):
            continue
        title, summary, version = (row.get(key) for key in ('title', 'summary', 'version'))
        packages.append(Package('snap', identifier, title if isinstance(title, str) and title else identifier,
                                summary if isinstance(summary, str) else '', installed=True,
                                update_version=version if isinstance(version, str) else ''))
    return SourceResult(packages, f'Snap: {len(packages)} available.', checked=True)


def available_updates(sources=SOURCES, on_result=None):
    """Query configured sources independently, without installing or refreshing packages."""
    adapters = {'apt': apt_updates, 'flatpak': flatpak_updates, 'snap': snap_updates}
    return _query_sources(adapters, sources, on_result, update_check=True)


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


def install(package, observe=None):
    # A package transaction belongs to its system manager. Let it finish even
    # when a download or the administrator prompt takes longer than a search.
    output = transaction(install_arguments(package), observe)
    if package.source == 'apt':
        result = run([DPKG_QUERY, '-W', '-f=${db:Status-Status}', '--', package.identifier])
        if result.strip() != 'installed':
            raise RuntimeError('APT finished without installing the selected package.')
    return output


DPKG = '/usr/bin/dpkg'
APT_INSTALLED_ID = re.compile(r'[a-z0-9][a-z0-9+.-]+(?::[a-z0-9][a-z0-9-]*)?')


def can_manage(package, action):
    if not package.installed or action not in ('update', 'remove'):
        return False
    if package.source == 'apt':
        name = package.identifier.split(':', 1)[0]
        return bool(APT_INSTALLED_ID.fullmatch(package.identifier)
                    and (action == 'update' or not name.startswith(('mellipi', 'abstract', 'orbit-'))))
    if package.source == 'flatpak':
        return bool(package.scope in ('user', 'system') and FLATPAK_ID.fullmatch(package.identifier)
                    and FLATPAK_COMPONENT.fullmatch(package.branch))
    if package.source == 'snap':
        return bool(SNAP_ID.fullmatch(package.identifier))
    return False


def manage_arguments(package, action):
    if not can_manage(package, action):
        raise ValueError('This software cannot be managed from here.')
    if package.source == 'apt':
        if action == 'update':
            # Respect holds and authenticated APT sources; never remove another package.
            return [PKEXEC, APT_GET, '-y', '--only-upgrade', '--no-remove',
                    'install', '--', package.identifier]
        # dpkg refuses to break installed dependencies under its package lock.
        # APT remove can silently add dependent packages to the transaction.
        return [PKEXEC, DPKG, '--refuse-depends', '--refuse-remove-essential',
                '--refuse-remove-protected', '--remove', '--', package.identifier]
    if package.source == 'flatpak':
        verb = 'uninstall' if action == 'remove' else 'update'
        options = ['--no-related'] if action == 'remove' else []
        return [FLATPAK, '--' + package.scope, verb, '--app', '--assumeyes',
                '--noninteractive', *options, '--', f'{package.identifier}//{package.branch}']
    return [PKEXEC, SNAP, 'refresh' if action == 'update' else 'remove', '--', package.identifier]


def apt_preview(packages, action):
    packages = tuple(package for package in dict.fromkeys(packages) if package.source == 'apt')
    if not packages:
        return ()
    if action == 'install' and len(packages) == 1:
        arguments = install_arguments(packages[0])[2:]
    elif action == 'update':
        arguments = manage_arguments(packages[0], action)[2:]
        arguments.extend(manage_arguments(package, action)[-1] for package in packages[1:])
    elif action == 'remove' and len(packages) == 1 and can_manage(packages[0], action):
        arguments = ['remove', '--', packages[0].identifier]
    else:
        raise ValueError('Cannot preview this APT transaction.')
    output = run([APT_GET, '--simulate', *arguments], timeout=30)
    rows = []
    for line in output.splitlines():
        if not line.startswith(('Inst ', 'Remv ', 'Purg ')):
            continue
        verb, name, *_ = line.split()
        if not APT_INSTALLED_ID.fullmatch(name) or len(rows) >= 4000:
            raise RuntimeError('APT returned a package plan that could not be reviewed safely.')
        if verb != 'Inst' and (action != 'remove' or name.split(':')[0] != packages[0].identifier.split(':')[0]):
            raise RuntimeError(f'APT would also remove {name}. Nothing changed.')
        operation = ('Upgrade' if re.match(r'^Inst \S+ \[', line) else 'Install') if verb == 'Inst' else 'Remove'
        rows.append((operation, name, line.split(maxsplit=2)[-1] if operation != 'Remove' else ''))
    if not rows and action in ('install', 'remove'):
        raise RuntimeError('APT did not include the selected change. Refresh the package list and try again.')
    return tuple(rows)


def manage(package, action, observe=None):
    arguments = manage_arguments(package, action)
    if package.source == 'apt':
        fields = r'${db:Status-Want}\t${db:Status-Status}\t${Essential}\t${Protected}\t${Priority}\t${Version}\n'
        before = run([DPKG_QUERY, '-W', '-f=' + fields, '--', package.identifier]).rstrip('\n').split('\t')
        if len(before) != 6 or before[1] != 'installed':
            raise RuntimeError('This package is no longer installed. Refresh the list and try again.')
        if before[0] == 'hold':
            raise RuntimeError('This package is on hold in the system package manager.')
        if action == 'remove':
            if before[2:4].count('yes') or before[4] in ('required', 'important'):
                raise RuntimeError('Software cannot remove a protected system package.')
            paths = run([DPKG_QUERY, '-L', '--', package.identifier]).splitlines()
            if not any(re.fullmatch(r'/usr/share/applications/[^/]+\.desktop', path) for path in paths):
                raise RuntimeError('Software removes desktop apps only. Use the system package manager for this package.')
    transaction(arguments, observe)
    if package.source == 'apt' and action == 'update':
        # Check the installed version rather than interpreting localized apt output.
        after = run([DPKG_QUERY, '-W', '-f=${Version}', '--', package.identifier]).strip()
        return after != before[5]
    return None


def manage_updates(packages, observe=None):
    """Update selected packages in one transaction per manager and scope."""
    unique = tuple(dict.fromkeys(packages))
    if not 1 <= len(unique) <= 100 or not all(can_manage(p, 'update') for p in unique):
        raise ValueError('Select 1–100 supported updates.')
    groups = {}
    for package in unique:
        key = (package.source, package.scope if package.source == 'flatpak' else '')
        groups.setdefault(key, []).append(package)
    # Validate every APT target before starting any group; holds stay respected.
    for package in groups.get(('apt', ''), []):
        state = run([DPKG_QUERY, '-W', '-f=${db:Status-Want} ${db:Status-Status}', '--',
                     package.identifier]).strip()
        if state == 'hold installed':
            raise RuntimeError(f'{package.name} is on hold.')
        if not state.endswith(' installed'):
            raise RuntimeError(f'{package.name} is no longer installed. Check for updates again.')
    completed = 0
    for packages_in_group in groups.values():
        first, *rest = packages_in_group
        command = manage_arguments(first, 'update')
        command.extend(manage_arguments(package, 'update')[-1] for package in rest)
        try:
            transaction(command, observe)
        except (AuthorizationDeclined, RuntimeError, OSError) as error:
            if completed:
                error_type = AuthorizationDeclined if isinstance(error, AuthorizationDeclined) else RuntimeError
                raise error_type(f'{completed} earlier update(s) completed. {error}') from error
            raise
        completed += len(packages_in_group)
    return completed
