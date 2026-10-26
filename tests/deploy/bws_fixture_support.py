"""Test fixtures for BWS candidate paths that exercise production ownership checks."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import os
import stat
import tempfile
from pathlib import Path

import pytest


def _has_protected_ancestry(path: Path, *, require_private_leaf: bool = True) -> bool:
    try:
        resolved = path.resolve(strict=True)
        for index, directory in enumerate((resolved, *resolved.parents)):
            info = directory.stat(follow_symlinks=False)
            is_leaf = index == 0
            sticky_shared_ancestor = (
                not is_leaf and info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
            )
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid not in {0, os.geteuid()}
                or (info.st_mode & 0o022 and not sticky_shared_ancestor)
                or (
                    is_leaf
                    and require_private_leaf
                    and stat.S_IMODE(info.st_mode) not in {0o700, 0o755}
                )
            ):
                return False
        return True
    except OSError:
        return False


@contextmanager
def _protected_temp_path(tmp_path: Path, *, repository_root: Path) -> Iterator[Path]:
    """Yield a temp directory whose full ancestry meets BWS checkout checks."""
    if _has_protected_ancestry(tmp_path):
        yield tmp_path
        return

    for candidate in (repository_root, Path.home()):
        try:
            candidate = candidate.resolve(strict=True)
        except OSError:
            continue
        if not _has_protected_ancestry(candidate, require_private_leaf=False):
            continue
        with tempfile.TemporaryDirectory(prefix="pytest-secure-", dir=candidate) as directory:
            protected = Path(directory)
            if _has_protected_ancestry(protected):
                yield protected
                return

    raise RuntimeError("no temp directory has ancestry safe for BWS checkout tests")


@pytest.fixture(name="secure_tmp_path")
def bws_secure_tmp_path(tmp_path: Path) -> Iterator[Path]:
    repository_root = Path(__file__).resolve().parents[2]
    with _protected_temp_path(tmp_path, repository_root=repository_root) as path:
        yield path
