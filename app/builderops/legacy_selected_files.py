"""Read only two explicitly selected regular files for patch custody checks."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat


class SelectedFilesRefused(ValueError):
    """Selected files are unsafe, unstable, or do not match expected bytes."""


def read_selected(root: Path, expected: dict[str, str]) -> dict[str, bytes]:
    """Return selected bytes for an in-memory patch comparison, never neighbouring files."""
    if not root.is_absolute() or len(expected) != 2:
        raise SelectedFilesRefused("invalid file contract")
    descriptors: list[int] = []
    try:
        current = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        descriptors.append(current)
        for part in root.parts[1:]:
            current = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            descriptors.append(current)
        result: dict[str, bytes] = {}
        for name, digest in sorted(expected.items()):
            path = PurePosixPath(name)
            if (not name or path.is_absolute() or str(path) != name
                    or any(part in (".", "..", ".git") for part in path.parts)
                    or any(c in name for c in "\\\n\r\0") or not isinstance(digest, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", digest)):
                raise SelectedFilesRefused("invalid selected path")
            parent = current
            for part in path.parts[:-1]:
                parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                descriptors.append(parent)
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            descriptors.append(fd)
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o644
                    or before.st_size > 16 * 1024 * 1024):
                raise SelectedFilesRefused("unsupported selected file")
            remaining = before.st_size
            chunks: list[bytes] = []
            while remaining:
                chunk = os.read(fd, min(remaining, 65536))
                if not chunk:
                    raise SelectedFilesRefused("selected file changed")
                chunks.append(chunk)
                remaining -= len(chunk)
            after = os.fstat(fd)
            named = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    or (named.st_dev, named.st_ino) != (after.st_dev, after.st_ino)):
                raise SelectedFilesRefused("selected file changed")
            data = b"".join(chunks)
            if hashlib.sha256(data).hexdigest() != digest:
                raise SelectedFilesRefused("selected file differs")
            result[name] = data
        return result
    except OSError as exc:
        raise SelectedFilesRefused("selected file unavailable") from exc
    finally:
        for fd in reversed(descriptors):
            os.close(fd)
