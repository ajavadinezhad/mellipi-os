"""Bounded local ZIP/TAR operations. No external commands or archive permissions."""
import bz2
import gzip
import lzma
import os
import re
import stat
import tarfile
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path

TAR_SUFFIXES = ('.tar.gz', '.tar.bz2', '.tar.xz', '.tgz', '.tbz2', '.txz', '.tar')
SUFFIXES = ('.zip', *TAR_SUFFIXES)
MAX_MEMBERS = 10000
MAX_BYTES = 4 * 1024**3
MAX_INDEX = 8 * 1024**2
MAX_DEPTH = 32
CHUNK = 256 * 1024
PREVIEW_ROWS = 500
PREVIEW_BYTES = 32 * 1024**2


def archive_suffix(path):
    return next((suffix for suffix in SUFFIXES if path.name.lower().endswith(suffix)), '')


def _parts(name):
    if name.startswith('/') or '\\' in name or re.match(r'^[A-Za-z]:', name):
        raise ValueError('Archive contains an unsafe path')
    parts = name.rstrip('/').split('/')
    while parts and parts[0] == '.':
        parts.pop(0)
    if len(parts) > MAX_DEPTH or any(
        part in ('', '.', '..') or len(os.fsencode(part)) > 255 or any(ord(c) < 32 for c in part)
        for part in parts
    ):
        raise ValueError('Archive contains an unsafe or oversized path')
    return parts


def _copy(source, target, size):
    remaining = size
    while remaining:
        block = source.read(min(CHUNK, remaining))
        if not block:
            raise ValueError('Archive or source file is incomplete')
        target.write(block)
        remaining -= len(block)
    if source.read(1):
        raise ValueError('Archive or source file size changed')


def _regular(path, *, dir_fd=None):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
    try:
        size = os.fstat(fd)
        if not stat.S_ISREG(size.st_mode):
            raise ValueError('Only regular files and folders are supported')
        return os.fdopen(fd, 'rb'), size.st_size
    except BaseException:
        os.close(fd)
        raise


class _BoundedTarInfo(tarfile.TarInfo):
    @classmethod
    def _fromtarfile(cls, archive, *, dircheck=True):
        # Extended headers bypass the public member iterator. Bound their
        # memory and recursion before tarfile reads or interprets them.
        position = archive.fileobj.tell()
        header = archive.fileobj.read(tarfile.BLOCKSIZE)
        if len(header) != tarfile.BLOCKSIZE:
            raise ValueError('TAR archive is incomplete')
        # The stream only seeks forwards. Parse the header once here, as
        # TarInfo._fromtarfile normally does.
        try:
            item = cls._frombuf(header, archive.encoding, archive.errors, dircheck=dircheck)
        except tarfile.InvalidHeaderError as error:
            raise ValueError('TAR header is invalid') from error
        item.offset = position
        if item.size < 0 or item.size > MAX_BYTES:
            raise ValueError('TAR member is too large')
        if item.type in (tarfile.GNUTYPE_SPARSE, tarfile.GNUTYPE_LONGLINK):
            raise ValueError('Sparse files and links are not supported')
        metadata = item.type in (tarfile.GNUTYPE_LONGNAME, tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.SOLARIS_XHDTYPE)
        if metadata:
            depth = getattr(archive, '_mellipi_metadata_depth', 0)
            budget = getattr(archive, '_mellipi_metadata_bytes', 0) + item.size
            if depth >= 4 or item.size > CHUNK or budget > MAX_INDEX:
                raise ValueError('TAR metadata is too large')
            archive._mellipi_metadata_bytes = budget
            archive._mellipi_metadata_depth = depth + 1
            try:
                return item._proc_member(archive)
            finally:
                archive._mellipi_metadata_depth = depth
        return item._proc_member(archive)

    def _proc_gnusparse_00(self, *args):
        raise ValueError('Sparse TAR files are not supported')

    _proc_gnusparse_01 = _proc_gnusparse_10 = _proc_gnusparse_00


class _XzInput:
    def __init__(self, source):
        self.source = source
        self.decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ, memlimit=64 * 1024**2)

    def read(self, size):
        output = bytearray()
        while len(output) < size and not self.decoder.eof:
            block = self.source.read(CHUNK) if self.decoder.needs_input else b''
            if not block and self.decoder.needs_input:
                raise ValueError('XZ archive is incomplete')
            output.extend(self.decoder.decompress(block, size - len(output)))
        return bytes(output)


def _zip_members(archive):
    for item in archive.infolist():
        kind = stat.S_IFMT(item.external_attr >> 16) if item.create_system == 3 else 0
        if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or item.flag_bits & 1:
            raise ValueError('ZIP links, special files and encrypted entries are not supported')
        if item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise ValueError('Only Stored and Deflate ZIP compression are supported')
        yield item.orig_filename, item.is_dir() or kind == stat.S_IFDIR, item.file_size, item


def _tar_members(archive):
    for item in archive:
        if not (item.isdir() or item.type in (tarfile.REGTYPE, tarfile.AREGTYPE)) or item.issparse():
            raise ValueError('TAR links and special files are not supported')
        yield item.name, item.isdir(), item.size, item


def _verify_tar_tail(stream):
    # tarfile stops at the first zero block. Require the second marker and
    # finish reading bounded zero padding so compressed trailers are checked.
    padding = 0
    while block := stream.read(CHUNK):
        padding += len(block)
        if padding > MAX_INDEX or block.strip(b'\0'):
            raise ValueError('TAR end marker is invalid')
    if padding < tarfile.BLOCKSIZE or padding % tarfile.BLOCKSIZE:
        raise ValueError('TAR archive is incomplete')


class _PreviewLimit(Exception):
    pass


class _PreviewInput:
    def __init__(self, source):
        self.source = source
        self.remaining = PREVIEW_BYTES

    def read(self, size):
        if size == 0:
            return b''
        if size < 0 or not self.remaining:
            raise _PreviewLimit
        data = self.source.read(min(size, self.remaining))
        self.remaining -= len(data)
        return data


@contextmanager
def _open_archive(handle, suffix, *, preview=False):
    if suffix == '.zip':
        # ZipFile allocates the entire central directory at once.
        index = zipfile._EndRecData(handle)
        if index is None or index[zipfile._ECD_SIZE] > MAX_INDEX or index[zipfile._ECD_ENTRIES_TOTAL] > MAX_MEMBERS:
            raise ValueError('ZIP directory is invalid or too large')
        with zipfile.ZipFile(handle) as archive:
            yield archive, _zip_members, archive.open
        return

    magic = handle.peek(6)
    source = _PreviewInput(handle) if preview else handle
    if magic.startswith(b'\x1f\x8b'):
        stream = gzip.GzipFile(fileobj=source)
    elif magic.startswith(b'BZh'):
        stream = bz2.BZ2File(source)
    elif magic.startswith(b'\xfd7zXZ\x00'):
        stream = _XzInput(source)
    else:
        stream = source
    try:
        with tarfile.open(fileobj=_PreviewInput(stream) if preview else stream,
                          mode='r|', tarinfo=_BoundedTarInfo) as archive:
            yield archive, _tar_members, archive.extractfile
    finally:
        if stream is not source and hasattr(stream, 'close'):
            stream.close()


def preview_archive(path):
    """List names and sizes without writing or opening individual entries.

    TAR is sequential, so bound both compressed input and decoded bytes;
    a large payload can hide later headers even in a short listing.
    """
    path = Path(path)
    suffix = archive_suffix(path)
    if not suffix:
        raise ValueError('Choose a ZIP or TAR archive')
    handle, _ = _regular(path)
    rows = []
    try:
        with handle, _open_archive(handle, suffix, preview=True) as (archive, members, _):
            for name, directory, size, _ in members(archive):
                parts = _parts(name)
                if not parts and directory:
                    continue
                if not parts:
                    raise ValueError('Archive contains a file with no name')
                if len(rows) == PREVIEW_ROWS:
                    return rows, True
                rows.append(('/'.join(parts), directory, size))
    except _PreviewLimit:
        return rows, True
    return rows, False


def _extract(archive, members, opener, tree):
    total = 0
    seen = set()
    for count, (name, directory, size, item) in enumerate(members(archive), 1):
        total += size
        if count > MAX_MEMBERS or size < 0 or total > MAX_BYTES:
            raise ValueError('Archive exceeds the extraction limit')
        parts = _parts(name)
        if not parts and directory:
            continue  # Standard TAR root entry, e.g. tar -cf archive.tar .
        if not parts:
            raise ValueError('Archive contains a file with no name')
        path = tree.joinpath(*parts)
        if path in seen:
            raise ValueError('Archive contains duplicate entries')
        seen.add(path)
        if directory:
            if size:
                raise ValueError('Archive contains a malformed directory')
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            with opener(item) as source, path.open('xb') as target:
                _copy(source, target, size)


def extract_here(path, rename):
    """Publish only a complete tree; never merge with existing folders."""
    path = Path(path)
    suffix = archive_suffix(path)
    if not suffix:
        raise ValueError('Choose a ZIP or TAR archive')
    destination = path.with_name(path.name[:-len(suffix)] or 'Extracted archive')
    if destination.exists() or destination.is_symlink():
        raise ValueError('An item with that name already exists')
    handle, _ = _regular(path)
    with handle, tempfile.TemporaryDirectory(prefix='.mellipi-extract-', dir=path.parent) as directory:
        tree = Path(directory) / 'contents'
        tree.mkdir()
        with _open_archive(handle, suffix) as (archive, members, opener):
            _extract(archive, members, opener, tree)
            if suffix != '.zip':
                _verify_tar_tail(archive.fileobj)
        rename(tree, destination)
    return destination


def archive_identity(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def folder_identity(info):
    return info.st_dev, info.st_ino


def compress(paths, destination, rename, *, expected_sources=None, expected_folder=None):
    """Write one ZIP next to the selection and publish without overwriting."""
    paths = tuple(map(Path, paths))
    destination = Path(destination)
    if not 1 <= len(paths) <= MAX_MEMBERS:
        raise ValueError('Select files or folders to compress')
    if destination.exists() or destination.is_symlink():
        raise ValueError('An item with that name already exists')
    if any(path == destination or path in destination.parents for path in paths):
        raise ValueError('Choose a ZIP name outside the selected folders')
    total = count = index_size = 0

    def add(parent, basename, name, depth, expected=None):
        nonlocal count, total, index_size
        count += 1
        # Reserve central-directory filename bytes plus record/ZIP64 overhead
        # so we never write an archive that our own Extract Here refuses.
        index_size += len(name.encode('utf-8')) + 128
        if count > MAX_MEMBERS or depth > MAX_DEPTH or index_size > MAX_INDEX:
            raise ValueError('Selection exceeds the archive limit')
        _parts(name)
        info = os.stat(basename, dir_fd=parent, follow_symlinks=False)
        if expected is not None and archive_identity(info) != expected:
            raise ValueError('A selected item changed before compression.')
        mode = info.st_mode
        if stat.S_ISDIR(mode):
            fd = os.open(basename, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                if archive_identity(os.fstat(fd)) != archive_identity(info):
                    raise ValueError('A source folder changed before compression.')
                archive.writestr(name + '/', b'')
                with os.scandir(fd) as children:
                    for child in children:
                        add(fd, child.name, name + '/' + child.name, depth + 1)
            finally:
                os.close(fd)
        elif stat.S_ISREG(mode):
            source, size = _regular(basename, dir_fd=parent)
            with source:
                if archive_identity(os.fstat(source.fileno())) != archive_identity(info):
                    raise ValueError('A source file changed before compression.')
                total += size
                if total > MAX_BYTES:
                    raise ValueError('Selection exceeds the archive size limit')
                with archive.open(name, 'w', force_zip64=size >= zipfile.ZIP64_LIMIT) as target:
                    _copy(source, target, size)
                if archive_identity(os.fstat(source.fileno())) != archive_identity(info):
                    raise ValueError('A source file changed during compression.')
        else:
            raise ValueError('Links and special files cannot be compressed')

    destfd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        pinned_identity = folder_identity(os.fstat(destfd))
        if expected_folder is not None and expected_folder != pinned_identity:
            raise ValueError('The destination folder changed before compression.')
        pinned = Path('/proc/self/fd') / str(destfd)
        with tempfile.TemporaryDirectory(prefix='.mellipi-compress-', dir=pinned) as directory:
            temporary = Path(directory) / 'archive.zip'
            with zipfile.ZipFile(temporary, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
                for path in paths:
                    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        add(fd, path.name, path.name, 1,
                            expected_sources[path] if expected_sources is not None else None)
                    finally:
                        os.close(fd)
            if folder_identity(destination.parent.stat()) != pinned_identity:
                raise ValueError('The destination folder changed during compression.')
            rename(temporary, pinned / destination.name)
    finally:
        os.close(destfd)
    return destination
