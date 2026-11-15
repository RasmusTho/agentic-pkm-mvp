"""Inspect explicitly selected index entries without running Git in the source.

This is a constituent check, not a candidate inventory or custody authority.
The caller must independently bind expected blob IDs to the qualified HEAD.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile


class IndexRefused(ValueError):
    """The selected index or its explicitly selected entries are unsupported."""


def inspect_index(index: Path, expected_blobs: dict[str, str]) -> str:
    """Copy one bounded index and check exactly two paths in a neutral Git repository."""
    if not index.is_absolute() or len(expected_blobs) != 2:
        raise IndexRefused("invalid index contract")
    for name, oid in expected_blobs.items():
        path = PurePosixPath(name)
        if (not name or str(path) != name or path.is_absolute()
                or any(part in (".", "..", ".git") for part in path.parts)
                or any(c in name for c in "\\\n\r\0") or not re.fullmatch(r"[0-9a-f]{40}", oid)):
            raise IndexRefused("invalid selected entry")
    descriptors: list[int] = []
    try:
        current = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        descriptors.append(current)
        for part in index.parts[1:-1]:
            current = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            descriptors.append(current)
        fd = os.open(index.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=current)
        descriptors.append(fd)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 12 <= before.st_size <= 16 * 1024 * 1024:
            raise IndexRefused("unsupported index")
        chunks = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(fd, min(remaining, 65536))
            if not chunk:
                raise IndexRefused("index changed while reading")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(fd)
        named = os.stat(index.name, dir_fd=current, follow_symlinks=False)
        if (named.st_dev, named.st_ino) != (after.st_dev, after.st_ino):
            raise IndexRefused("index changed during read")
        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise IndexRefused("index changed while reading")
        data = b"".join(chunks)
    except OSError as exc:
        raise IndexRefused("index cannot be safely opened") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
    if data[:4] != b"DIRC" or int.from_bytes(data[4:8], "big") not in (2, 3):
        raise IndexRefused("unsupported index version")
    with tempfile.TemporaryDirectory(prefix="legacy-index-") as temporary:
        root = Path(temporary)
        env = {"PATH": "/usr/bin:/bin", "HOME": temporary, "LC_ALL": "C",
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
               "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_OPTIONAL_LOCKS": "0"}

        def git(*args: str) -> bytes:
            try:
                result = subprocess.run(["/usr/bin/git", *args], cwd=root, env=env,
                                        capture_output=True, timeout=10, check=False)
            except (OSError, subprocess.SubprocessError) as exc:
                raise IndexRefused("isolated Git unavailable") from exc
            if result.returncode or len(result.stdout) > 1024 * 1024:
                raise IndexRefused("isolated Git refused index")
            return result.stdout

        git("init", "-q")
        (root / ".git/index").write_bytes(data)
        names = sorted(expected_blobs)
        stages = git("--literal-pathspecs", "ls-files", "--stage", "-z", "--", *names)
        flags = git("--literal-pathspecs", "ls-files", "-v", "-z", "--", *names)
        expected_stages = {f"100644 {expected_blobs[n]} 0\t{n}".encode() for n in names}
        expected_flags = {f"H {n}".encode() for n in names}
        if set(filter(None, stages.split(b"\0"))) != expected_stages or set(filter(None, flags.split(b"\0"))) != expected_flags:
            raise IndexRefused("selected index entries differ from HEAD or have hidden flags")
    return hashlib.sha256(data).hexdigest()
