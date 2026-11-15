"""Verify a separately preserved patch, without granting recovery authority."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat


class PatchBackupRefused(ValueError):
    """The selected backup is unsafe, unstable, or does not match its digest."""


def read_patch_backup(path: Path, expected_sha256: str, *, max_bytes: int = 16 * 1024 * 1024) -> bytes:
    """Hash one explicit backup through no-follow descriptors; never read its neighbours.

    The returned bytes are content evidence only. They do not establish the patch's
    provenance, applicability, candidate identity, writer custody, or authority.
    """
    if (not path.is_absolute() or any(part in (".", "..") for part in path.parts)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
            or type(max_bytes) is not int or max_bytes < 1):
        raise PatchBackupRefused("invalid backup contract")
    descriptors: list[int] = []
    try:
        current = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        descriptors.append(current)
        for component in path.parts[1:-1]:
            current = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            descriptors.append(current)
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=current)
        descriptors.append(fd)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size < 1 or before.st_size > max_bytes:
            raise PatchBackupRefused("backup is not a bounded regular file")
        digest = hashlib.sha256()
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(fd, min(remaining, 65536))
            if not chunk:
                raise PatchBackupRefused("backup changed during read")
            digest.update(chunk)
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(fd)
        named = os.stat(path.name, dir_fd=current, follow_symlinks=False)
        if (named.st_dev, named.st_ino) != (after.st_dev, after.st_ino):
            raise PatchBackupRefused("backup changed during read")
        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise PatchBackupRefused("backup changed during read")
        observed = digest.hexdigest()
        if observed != expected_sha256:
            raise PatchBackupRefused("backup digest mismatch")
        return b"".join(chunks)
    except OSError as exc:
        raise PatchBackupRefused("backup cannot be safely opened") from exc
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def verify_patch_backup(path: Path, expected_sha256: str, *, max_bytes: int = 16 * 1024 * 1024) -> str:
    """Return the digest of one verified backup without returning its content."""
    read_patch_backup(path, expected_sha256, max_bytes=max_bytes)
    return expected_sha256
