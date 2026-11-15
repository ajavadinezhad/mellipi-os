"""Bounded, read-only folder sizing for Files."""
import heapq
import os
import stat
from dataclasses import dataclass
from pathlib import Path


_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
MAX_ENTRIES = 250_000
MAX_DEPTH = 48
MAX_RESULTS = 100


@dataclass(frozen=True)
class StorageRow:
    name: str
    size: int
    folder: bool


@dataclass(frozen=True)
class StorageReport:
    rows: tuple[StorageRow, ...]
    entries: int
    total: int
    omitted: int
    incomplete: bool
    cancelled: bool


def _open_root(path):
    """Resolve each component without following links, including parent paths."""
    path = Path(os.path.abspath(path))
    fd = os.open('/', _FLAGS)
    try:
        for part in path.parts[1:]:
            new = os.open(part, _FLAGS, dir_fd=fd)
            os.close(fd)
            fd = new
    except BaseException:
        os.close(fd)
        raise
    return fd


def analyze(path, cancelled=lambda: False, max_entries=MAX_ENTRIES, max_depth=MAX_DEPTH):
    """Return the largest direct children by apparent size on one filesystem."""
    entries = total = omitted = 0
    incomplete = stopped = False
    rows = []

    def available():
        nonlocal incomplete, stopped
        if cancelled():
            stopped = incomplete = True
            return False
        if entries >= max_entries:
            incomplete = True
            return False
        return True

    def account(entry, parent, depth):
        nonlocal entries, omitted, incomplete
        entries += 1
        try:
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISREG(info.st_mode):
                return info.st_size, False
            if not stat.S_ISDIR(info.st_mode):
                return None
            if info.st_dev != device:
                omitted += 1
                return None
            if depth >= max_depth:
                incomplete = True
                omitted += 1
                return None

            fd = os.open(entry.name, _FLAGS, dir_fd=parent)
            try:
                opened = os.fstat(fd)
                if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                    omitted += 1
                    return None
                size = 0
                with os.scandir(fd) as children:
                    for child in children:
                        if not available():
                            break
                        result = account(child, fd, depth + 1)
                        if result is not None:
                            size += result[0]
                return size, True
            finally:
                os.close(fd)
        except OSError:
            omitted += 1
            return None

    root = _open_root(path)
    try:
        device = os.fstat(root).st_dev
        with os.scandir(root) as children:
            for child in children:
                if not available():
                    break
                result = account(child, root, 0)
                if result is None:
                    continue
                size, folder = result
                total += size
                value = (size, child.name, folder)
                if len(rows) < MAX_RESULTS:
                    heapq.heappush(rows, value)
                elif value > rows[0]:
                    heapq.heapreplace(rows, value)
    finally:
        os.close(root)
    return StorageReport(tuple(StorageRow(name, size, folder)
                               for size, name, folder in sorted(rows, reverse=True)),
                         entries, total, omitted, incomplete or bool(omitted), stopped)
