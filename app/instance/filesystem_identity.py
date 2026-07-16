from __future__ import annotations

import errno
import os
import stat
from dataclasses import dataclass
from pathlib import Path


class FilesystemIdentityError(RuntimeError):
    """A root's physical identity cannot be established safely."""


@dataclass(frozen=True)
class FilesystemRootIdentity:
    canonical_path: str
    device: int | None
    inode: int | None

    @property
    def materialized(self) -> bool:
        return self.device is not None and self.inode is not None


def resolve_filesystem_root_identity(value: str | Path) -> FilesystemRootIdentity:
    """Resolve lexical, symlink, and materialized filesystem identity for one root.

    Missing roots retain canonical-path identity because dormant/offline registrations are
    valid. Existing roots must be directories and must be stat-able without ambiguity.
    """

    try:
        resolved = Path(value).expanduser().resolve(strict=False)
        metadata = os.stat(resolved)
    except OSError as exc:
        if exc.errno in {errno.ENOENT, errno.ENOTDIR}:
            return FilesystemRootIdentity(str(resolved), None, None)
        raise FilesystemIdentityError(f"cannot resolve filesystem identity for {value}: {exc}") from exc
    except RuntimeError as exc:
        raise FilesystemIdentityError(f"cannot resolve filesystem identity for {value}: {exc}") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise FilesystemIdentityError(f"registered vault root is not a directory: {resolved}")
    return FilesystemRootIdentity(str(resolved), metadata.st_dev, metadata.st_ino)


def same_filesystem_root(left: FilesystemRootIdentity, right: FilesystemRootIdentity) -> bool:
    if left.canonical_path == right.canonical_path:
        return True
    return (
        left.materialized
        and right.materialized
        and (left.device, left.inode) == (right.device, right.inode)
    )


__all__ = [
    "FilesystemIdentityError",
    "FilesystemRootIdentity",
    "resolve_filesystem_root_identity",
    "same_filesystem_root",
]
