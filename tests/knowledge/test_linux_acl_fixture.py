from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

from tests.knowledge import linux_acl
from tests.knowledge.linux_acl import (
    LinuxNamedAclFile,
    LinuxNamedAclUnavailable,
    create_linux_named_acl_file,
    read_linux_access_acl,
    replace_with_staged_acl_copy,
)


pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="Linux POSIX ACL semantics are proved on the governed Ubuntu CI lane",
)


@pytest.fixture
def linux_named_acl_file(tmp_path: Path) -> LinuxNamedAclFile:
    target = tmp_path / "vault" / "Logs" / "steering.md"
    try:
        return create_linux_named_acl_file(target, content=b"before\n")
    except LinuxNamedAclUnavailable as exc:
        pytest.fail(str(exc), pytrace=False)


def test_linux_named_acl_fixture_is_nontrivial(
    linux_named_acl_file: LinuxNamedAclFile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = linux_named_acl_file

    assert stat.S_ISREG(fixture.path.stat().st_mode)
    assert fixture.owner_uid != fixture.named_uid
    assert f"user:{fixture.named_uid}:r--" in fixture.access_acl.splitlines()
    assert "mask::r--" in fixture.access_acl.splitlines()
    assert read_linux_access_acl(fixture.path) == fixture.access_acl

    monkeypatch.setattr(linux_acl.shutil, "which", lambda _name: None)
    with pytest.raises(
        LinuxNamedAclUnavailable,
        match="install the Ubuntu 'acl' package",
    ):
        read_linux_access_acl(fixture.path)


def test_atomic_replacement_fixture_preserves_named_acl(
    linux_named_acl_file: LinuxNamedAclFile,
) -> None:
    fixture = linux_named_acl_file
    original_inode = fixture.path.stat().st_ino

    staged_inode = replace_with_staged_acl_copy(fixture.path, content=b"after\n")

    assert fixture.path.read_bytes() == b"after\n"
    assert fixture.path.stat().st_ino == staged_inode
    assert fixture.path.stat().st_ino != original_inode
    assert read_linux_access_acl(fixture.path) == fixture.access_acl
    assert f"user:{fixture.named_uid}:r--" in fixture.access_acl.splitlines()
