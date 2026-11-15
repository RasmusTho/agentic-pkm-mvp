from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.builderops.legacy_patch_backup import PatchBackupRefused, verify_patch_backup


def test_verifies_exact_separate_binary_backup(tmp_path: Path) -> None:
    data = b"binary patch\x00\xff\n"
    backup = tmp_path / "backup.patch"
    backup.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    assert verify_patch_backup(backup, digest) == digest
    backup.write_bytes(data + b"changed")
    with pytest.raises(PatchBackupRefused, match="digest mismatch"):
        verify_patch_backup(backup, digest)


def test_refuses_symlinks_and_oversized_backup(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    backup.write_bytes(b"data")
    digest = hashlib.sha256(b"data").hexdigest()
    link = tmp_path / "link"
    link.symlink_to(backup)
    with pytest.raises(PatchBackupRefused):
        verify_patch_backup(link, digest)
    directory_link = tmp_path / "directory-link"
    directory_link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(PatchBackupRefused):
        verify_patch_backup(directory_link / "backup", digest)
    with pytest.raises(PatchBackupRefused, match="bounded"):
        verify_patch_backup(backup, digest, max_bytes=3)
