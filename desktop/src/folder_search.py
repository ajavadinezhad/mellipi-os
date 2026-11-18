"""On-demand, bounded local filename search shared by Files and the Launcher."""
import os
from pathlib import Path


def find_nested_names(root, query, stopped, *, hidden=False, limit=500, scan_limit=100000):
    """Bounded ad hoc filename search; never traverse symlinked directories."""
    pending = [(Path(root), 0)]
    matches, visited, skipped = [], 0, 0
    needle = query.casefold()
    while pending and not stopped.is_set():
        folder, depth = pending.pop()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if stopped.is_set():
                        return [], False, 0
                    visited += 1
                    if visited > scan_limit:
                        return matches, True, skipped
                    if not hidden and entry.name.startswith('.'):
                        continue
                    path = Path(entry.path)
                    if needle in entry.name.casefold():
                        matches.append(path)
                        if len(matches) >= limit:
                            return matches, True, skipped
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if depth < 64:
                                pending.append((path, depth + 1))
                            else:
                                skipped += 1
                    except OSError:
                        skipped += 1
        except OSError:
            skipped += 1
    return matches, False, skipped
