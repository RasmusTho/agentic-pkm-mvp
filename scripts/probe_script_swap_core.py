"""Finite, descriptor-bound replacement of the installed production probe file.

This module deliberately knows nothing about a host, service manager, transport,
credentials, or incident state.  The caller must qualify those facts and pass a
directory descriptor.  It only replaces ``prod_probe.py`` after rechecking the
owned source slot immediately before the single rename.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat


LEAF = "prod_probe.py"
MAX_BYTES = 262_144
SOURCE_MODE = 0o664
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")


class SwapFailure(Exception):
    """A bounded swap failed; ``replace_returned=False`` is potentially UNKNOWN."""

    def __init__(self, phase: str, attempted: bool, returned: bool):
        super().__init__("probe script swap failed")
        self.phase = phase
        self.replace_attempted = attempted
        self.replace_returned = returned


def _signature(meta: os.stat_result) -> tuple[int, ...]:
    return (
        meta.st_dev,
        meta.st_ino,
        meta.st_mode,
        meta.st_uid,
        meta.st_gid,
        meta.st_nlink,
        meta.st_size,
        meta.st_mtime_ns,
        meta.st_ctime_ns,
    )


def _trusted_parent(fd: int, uid: int, gid: int) -> os.stat_result:
    meta = os.fstat(fd)
    if not (
        stat.S_ISDIR(meta.st_mode)
        and meta.st_uid == uid
        and meta.st_gid == gid
        and stat.S_IMODE(meta.st_mode) in (0o755, 0o775)
    ):
        raise ValueError("parent mismatch")
    list_attributes = getattr(os, "listxattr", None)
    if callable(list_attributes) and {
        "system.posix_acl_access",
        "system.posix_acl_default",
    }.intersection(list_attributes(fd)):
        raise ValueError("parent ACL mismatch")
    return meta


def _read_source(fd: int, uid: int, gid: int) -> tuple[bytes, os.stat_result]:
    before = os.fstat(fd)
    if not (
        stat.S_ISREG(before.st_mode)
        and before.st_uid == uid
        and before.st_gid == gid
        and before.st_nlink == 1
        and stat.S_IMODE(before.st_mode) == SOURCE_MODE
        and 0 < before.st_size <= MAX_BYTES
    ):
        raise ValueError("source metadata mismatch")
    list_attributes = getattr(os, "listxattr", None)
    if callable(list_attributes) and "system.posix_acl_access" in list_attributes(fd):
        raise ValueError("source ACL mismatch")

    chunks: list[bytes] = []
    count = 0
    while True:
        block = os.read(fd, min(65_536, MAX_BYTES + 1 - count))
        if not block:
            break
        chunks.append(block)
        count += len(block)
        if count > MAX_BYTES:
            raise ValueError("source bound")
    after = os.fstat(fd)
    if count != before.st_size or _signature(before) != _signature(after):
        raise ValueError("source changed")
    return b"".join(chunks), before


def _verify_named_stage(
    stage_fd: int,
    stage_name: str,
    stage_identity: tuple[int, int],
    after_sha256: str,
    uid: int,
    gid: int,
) -> None:
    """Rebind the rename source name to the descriptor-qualified stage inode."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    descriptor = os.open(stage_name, flags, dir_fd=stage_fd)
    try:
        named = os.fstat(descriptor)
        if (named.st_dev, named.st_ino) != stage_identity:
            raise ValueError("stage slot changed")
        staged, _ = _read_source(descriptor, uid, gid)
        if hashlib.sha256(staged).hexdigest() != after_sha256:
            raise ValueError("stage slot digest mismatch")
    finally:
        os.close(descriptor)


def swap_script(
    parent_fd: int,
    before_sha256: str,
    after_bytes: bytes,
    after_sha256: str,
    operation_hex: str,
    before_commit,
    *,
    expected_uid: int = 0,
    expected_gid: int = 0,
) -> dict[str, object]:
    """Atomically replace only ``prod_probe.py`` in ``parent_fd``.

    ``before_commit`` is called after staging and before the final revalidation.
    It must recheck service quiescence and any operation-owned directory facts.
    A failed ``os.replace`` is reported as attempted-but-not-returned, never as
    proof that the old image remains.  The caller must reconcile that result.
    """

    phase = "input"
    attempted = False
    returned = False
    old_fd: int | None = None
    stage_fd: int | None = None
    stage_directory_fd: int | None = None
    stage_directory_name = f".prod_probe.4076-{operation_hex}.stage"
    stage_directory_identity: tuple[int, int] | None = None
    stage_name: str | None = None
    stage_identity: tuple[int, int] | None = None
    try:
        if not (
            isinstance(after_bytes, bytes)
            and 0 < len(after_bytes) <= MAX_BYTES
            and _HEX64.fullmatch(before_sha256)
            and _HEX64.fullmatch(after_sha256)
            and _HEX32.fullmatch(operation_hex)
            and hashlib.sha256(after_bytes).hexdigest() == after_sha256
        ):
            raise ValueError("input mismatch")

        phase = "parent"
        parent = _trusted_parent(parent_fd, expected_uid, expected_gid)
        phase = "before"
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        old_fd = os.open(LEAF, flags, dir_fd=parent_fd)
        old_bytes, original = _read_source(old_fd, expected_uid, expected_gid)
        if hashlib.sha256(old_bytes).hexdigest() != before_sha256:
            raise ValueError("before image mismatch")
        if _signature(os.stat(LEAF, dir_fd=parent_fd, follow_symlinks=False)) != _signature(
            original
        ):
            raise ValueError("before slot changed")

        phase = "stage_open"
        # Group 0 may write the installed source directory.  The rename source
        # lives in an exclusively created owner-only namespace instead of an
        # equally writable sibling name.  An existing namespace is a collision.
        os.mkdir(stage_directory_name, mode=0o700, dir_fd=parent_fd)
        stage_directory_fd = os.open(
            stage_directory_name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_fd,
        )
        namespace = os.fstat(stage_directory_fd)
        stage_directory_identity = (namespace.st_dev, namespace.st_ino)
        if not (
            namespace.st_uid == expected_uid
            and namespace.st_gid == expected_gid
            and stat.S_IMODE(namespace.st_mode) == 0o700
        ):
            raise ValueError("stage namespace ownership mismatch")
        stage_name = "prod_probe.py.new"
        stage_fd = os.open(
            stage_name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=stage_directory_fd,
        )
        info = os.fstat(stage_fd)
        stage_identity = (info.st_dev, info.st_ino)
        if not (
            stat.S_ISREG(info.st_mode)
            and info.st_nlink == 1
            and info.st_uid == expected_uid
            and info.st_gid == expected_gid
        ):
            raise ValueError("stage ownership mismatch")

        phase = "stage_write"
        view = memoryview(after_bytes)
        while view:
            written = os.write(stage_fd, view)
            if written <= 0:
                raise ValueError("stage write incomplete")
            view = view[written:]
        os.fchmod(stage_fd, SOURCE_MODE)
        os.fsync(stage_fd)
        os.lseek(stage_fd, 0, os.SEEK_SET)
        staged, _ = _read_source(stage_fd, expected_uid, expected_gid)
        if hashlib.sha256(staged).hexdigest() != after_sha256:
            raise ValueError("stage digest mismatch")

        phase = "before_commit"
        before_commit()
        current_parent = _trusted_parent(parent_fd, expected_uid, expected_gid)
        if (parent.st_dev, parent.st_ino) != (current_parent.st_dev, current_parent.st_ino):
            raise ValueError("parent changed")
        if _signature(os.stat(LEAF, dir_fd=parent_fd, follow_symlinks=False)) != _signature(
            original
        ):
            raise ValueError("source slot changed")
        named_namespace = os.stat(stage_directory_name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISDIR(named_namespace.st_mode)
            or (named_namespace.st_dev, named_namespace.st_ino) != stage_directory_identity
            or named_namespace.st_uid != expected_uid
            or named_namespace.st_gid != expected_gid
            or stat.S_IMODE(named_namespace.st_mode) != 0o700
        ):
            raise ValueError("stage namespace changed")
        _verify_named_stage(
            stage_directory_fd,
            stage_name,
            stage_identity,
            after_sha256,
            expected_uid,
            expected_gid,
        )

        phase = "replace"
        attempted = True
        os.replace(stage_name, LEAF, src_dir_fd=stage_directory_fd, dst_dir_fd=parent_fd)
        returned = True
        phase = "durability"
        os.fsync(parent_fd)
        phase = "after"
        installed = os.stat(LEAF, dir_fd=parent_fd, follow_symlinks=False)
        if (installed.st_dev, installed.st_ino) != stage_identity:
            raise ValueError("installed slot changed")
        os.lseek(stage_fd, 0, os.SEEK_SET)
        installed_bytes, _ = _read_source(stage_fd, expected_uid, expected_gid)
        if hashlib.sha256(installed_bytes).hexdigest() != after_sha256:
            raise ValueError("installed digest mismatch")
        return {
            "before_sha256": before_sha256,
            "after_sha256": after_sha256,
            "replace_attempted": True,
            "replace_returned": True,
            "source_mode": "0664",
            "stage_namespace_mode": "0700",
        }
    except BaseException:
        raise SwapFailure(phase, attempted, returned) from None
    finally:
        # Remove only the operation-created stage inode.  A collision or an
        # uncertain replacement remains for the owner to reconcile.
        if (
            stage_fd is not None
            and stage_name is not None
            and stage_identity is not None
            and stage_directory_fd is not None
        ):
            try:
                info = os.stat(stage_name, dir_fd=stage_directory_fd, follow_symlinks=False)
                if (
                    (info.st_dev, info.st_ino) == stage_identity
                    and stat.S_ISREG(info.st_mode)
                    and info.st_nlink == 1
                    and info.st_uid == expected_uid
                    and info.st_gid == expected_gid
                ):
                    os.unlink(stage_name, dir_fd=stage_directory_fd)
            except FileNotFoundError:
                pass
            except OSError:
                pass
        if stage_directory_identity is not None:
            try:
                namespace = os.stat(stage_directory_name, dir_fd=parent_fd, follow_symlinks=False)
                if (namespace.st_dev, namespace.st_ino) == stage_directory_identity:
                    # rmdir refuses a nonempty namespace: preserve foreign files.
                    os.rmdir(stage_directory_name, dir_fd=parent_fd)
            except OSError:
                pass
        for descriptor in (old_fd, stage_fd, stage_directory_fd):
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


if __name__ == "__main__":
    print('{"schema":"probe_script_swap_preparation.v1","armed":false}')
    raise SystemExit(78)
