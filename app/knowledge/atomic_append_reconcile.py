"""Descriptor-bound, recoverable append records for one vault-relative target.

This seam intentionally is not a ``KnowledgePort.append_note`` replacement.  A
caller opts in with a stable operation identity, a payload digest, and a pure
reconciliation callback; ordinary append semantics remain unchanged until a
consumer is migrated explicitly.
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.util
import errno
import fcntl
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import TYPE_CHECKING, Callable, Literal
import unicodedata
import uuid

from app.knowledge.adapters import (
    _atomic_exchange_at,
    _atomic_rename_noreplace_at,
    _same_file_identity,
)
from app.knowledge.errors import KnowledgeCapabilityError, KnowledgeWriteConflict

if TYPE_CHECKING:
    from app.write_guard import WriteGuard


_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
_OPEN_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_OPEN_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_TARGET_OPEN_FLAGS = os.O_RDONLY | _OPEN_NOFOLLOW | _OPEN_CLOEXEC
_STAGE_OPEN_FLAGS = os.O_RDWR | os.O_CREAT | os.O_EXCL | _OPEN_NOFOLLOW | _OPEN_CLOEXEC
_RECOVERY_OPEN_FLAGS = os.O_RDWR | os.O_CREAT | os.O_EXCL | _OPEN_NOFOLLOW | _OPEN_CLOEXEC
_LOCK_OPEN_FLAGS = os.O_RDWR | os.O_CREAT | _OPEN_NOFOLLOW | _OPEN_CLOEXEC
_RECOVERY_DIRECTORY = ".atomic-append-reconcile-recovery"
_RECOVERY_SUFFIX = ".recovery"
_MAX_RECOVERY_ENTRIES = 256
_CAPACITY_DIRECTORY = ".capacity-slots"
_CAPACITY_INITIALIZING = ".initializing"
_CAPACITY_INITIALIZED = ".initialized"
_FRAME_PREFIX = b"\x1ePKM-ATOMIC-APPEND-RECONCILE-V1 "
_FRAME_HEADER_END = b" -->\n"
_FRAME_COMMIT_PREFIX = b"\n<!-- /pkm-atomic-append-reconcile:commit "
_OPERATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


class AtomicAppendIdentityCollision(KnowledgeWriteConflict):
    """The stable operation identity was previously committed for another payload."""


class AtomicAppendRecoveryError(KnowledgeWriteConflict):
    """A target contains a torn or otherwise unverifiable append frame."""


@dataclass(frozen=True)
class AtomicAppendRecord:
    operation_id: str
    payload_fingerprint: str
    payload: bytes


@dataclass(frozen=True)
class AtomicAppendReconcileResult:
    outcome: Literal["appended", "reconciled_replay"]
    operation_id: str
    payload_fingerprint: str


@dataclass(frozen=True)
class _InventoryEntry:
    namespace: Literal["active", "retained"]
    name: str
    descriptor: int


@dataclass(frozen=True)
class _RetirementReceipt:
    stage_name: str
    name: str
    descriptor: int


@dataclass
class _CapacitySlot:
    index: int
    name: str
    descriptor: int
    consumed: bool = False


@dataclass
class _CapacityReservation:
    directory: int
    slots: list[_CapacitySlot]


ReconcileCallback = Callable[[bytes, tuple[AtomicAppendRecord, ...]], bytes | str | None]


class _RetryAnchoredIdentity(RuntimeError):
    """A cooperating writer replaced the target before this attempt published."""


def _require_platform_primitives() -> None:
    if not getattr(os, "O_DIRECTORY", 0) or not _OPEN_NOFOLLOW:
        raise KnowledgeCapabilityError("descriptor no-follow directory opens are unavailable")
    required = ("fchown", "fchmod")
    missing = [name for name in required if not callable(getattr(os, name, None))]
    if missing:
        raise KnowledgeCapabilityError(
            "required metadata preservation primitive is unavailable: " + ", ".join(missing)
        )


def _xattr_libc() -> ctypes.CDLL:
    return ctypes.CDLL(ctypes.util.find_library("c") or None, use_errno=True)


def _acl_libc() -> ctypes.CDLL:
    return ctypes.CDLL(
        ctypes.util.find_library("acl") or ctypes.util.find_library("c") or None,
        use_errno=True,
    )


def _xattr_error(operation: str) -> OSError:
    error_number = ctypes.get_errno()
    return OSError(error_number, f"{operation}: {os.strerror(error_number)}")


def _list_xattrs(fd: int) -> list[str]:
    list_xattr = getattr(os, "listxattr", None)
    if callable(list_xattr):
        return list(list_xattr(fd))
    libc = _xattr_libc()
    operation = getattr(libc, "flistxattr", None)
    if operation is None:
        raise KnowledgeCapabilityError("descriptor ACL metadata enumeration is unavailable")
    if sys.platform == "darwin":
        operation.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
        operation.restype = ctypes.c_ssize_t
        result = operation(fd, None, 0, 0)
    else:
        operation.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t]
        operation.restype = ctypes.c_ssize_t
        result = operation(fd, None, 0)
    if result < 0:
        raise _xattr_error("flistxattr")
    if result == 0:
        return []
    buffer = ctypes.create_string_buffer(result)
    if sys.platform == "darwin":
        result = operation(fd, buffer, result, 0)
    else:
        result = operation(fd, buffer, result)
    if result < 0:
        raise _xattr_error("flistxattr")
    return [os.fsdecode(name) for name in buffer.raw[:result].split(b"\0") if name]


def _get_xattr(fd: int, name: str) -> bytes:
    get_xattr = getattr(os, "getxattr", None)
    if callable(get_xattr):
        return get_xattr(fd, name)
    libc = _xattr_libc()
    operation = getattr(libc, "fgetxattr", None)
    if operation is None:
        raise KnowledgeCapabilityError("descriptor ACL metadata reads are unavailable")
    encoded_name = os.fsencode(name)
    if sys.platform == "darwin":
        operation.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_uint32,
            ctypes.c_int,
        ]
        operation.restype = ctypes.c_ssize_t
        result = operation(fd, encoded_name, None, 0, 0, 0)
    else:
        operation.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t]
        operation.restype = ctypes.c_ssize_t
        result = operation(fd, encoded_name, None, 0)
    if result < 0:
        raise _xattr_error("fgetxattr")
    if result == 0:
        return b""
    buffer = ctypes.create_string_buffer(result)
    if sys.platform == "darwin":
        result = operation(fd, encoded_name, buffer, result, 0, 0)
    else:
        result = operation(fd, encoded_name, buffer, result)
    if result < 0:
        raise _xattr_error("fgetxattr")
    return buffer.raw[:result]


def _set_xattr(fd: int, name: str, value: bytes) -> None:
    set_xattr = getattr(os, "setxattr", None)
    if callable(set_xattr):
        set_xattr(fd, name, value)
        return
    libc = _xattr_libc()
    operation = getattr(libc, "fsetxattr", None)
    if operation is None:
        raise KnowledgeCapabilityError("descriptor ACL metadata writes are unavailable")
    encoded_name = os.fsencode(name)
    buffer = ctypes.create_string_buffer(value)
    if sys.platform == "darwin":
        operation.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_uint32,
            ctypes.c_int,
        ]
        operation.restype = ctypes.c_int
        result = operation(fd, encoded_name, buffer, len(value), 0, 0)
    else:
        operation.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_int,
        ]
        operation.restype = ctypes.c_int
        result = operation(fd, encoded_name, buffer, len(value), 0)
    if result != 0:
        raise _xattr_error("fsetxattr")


def _acl_text(fd: int) -> bytes:
    """Return a canonical descriptor ACL representation or fail before replacement."""

    libc = _acl_libc()
    get_acl = getattr(libc, "acl_get_fd", None)
    to_text = getattr(libc, "acl_to_text", None)
    free_acl = getattr(libc, "acl_free", None)
    if get_acl is None or to_text is None or free_acl is None:
        raise KnowledgeCapabilityError("descriptor ACL clone primitives are unavailable")
    get_acl.argtypes = [ctypes.c_int]
    get_acl.restype = ctypes.c_void_p
    to_text.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ssize_t)]
    to_text.restype = ctypes.c_void_p
    free_acl.argtypes = [ctypes.c_void_p]
    free_acl.restype = ctypes.c_int
    acl = get_acl(fd)
    if not acl:
        if ctypes.get_errno() in {errno.ENOENT, getattr(errno, "ENODATA", errno.ENOENT)}:
            return b""
        raise _xattr_error("acl_get_fd")
    text = ctypes.c_void_p()
    try:
        length = ctypes.c_ssize_t()
        text = ctypes.c_void_p(to_text(acl, ctypes.byref(length)))
        if not text.value:
            raise _xattr_error("acl_to_text")
        return ctypes.string_at(text, length.value)
    finally:
        if text.value:
            free_acl(text)
        free_acl(acl)


def _clone_acl(source_fd: int, destination_fd: int) -> None:
    libc = _acl_libc()
    get_acl = getattr(libc, "acl_get_fd", None)
    set_acl = getattr(libc, "acl_set_fd", None)
    free_acl = getattr(libc, "acl_free", None)
    if get_acl is None or set_acl is None or free_acl is None:
        raise KnowledgeCapabilityError("descriptor ACL clone primitives are unavailable")
    get_acl.argtypes = [ctypes.c_int]
    get_acl.restype = ctypes.c_void_p
    set_acl.argtypes = [ctypes.c_int, ctypes.c_void_p]
    set_acl.restype = ctypes.c_int
    free_acl.argtypes = [ctypes.c_void_p]
    free_acl.restype = ctypes.c_int
    acl = get_acl(source_fd)
    if not acl:
        if ctypes.get_errno() in {errno.ENOENT, getattr(errno, "ENODATA", errno.ENOENT)}:
            return
        raise _xattr_error("acl_get_fd")
    try:
        if set_acl(destination_fd, acl) != 0:
            raise _xattr_error("acl_set_fd")
    finally:
        free_acl(acl)


def _relative_parts(note_rel_path: str) -> tuple[str, ...]:
    if not note_rel_path or "\x00" in note_rel_path or "\\" in note_rel_path:
        raise ValueError("target path must be a portable vault-relative POSIX path")
    path = PurePosixPath(note_rel_path)
    if path.is_absolute() or path.as_posix() != note_rel_path:
        raise ValueError("target path must be normalized and vault-relative")
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("target path must remain inside the vault")
    return path.parts


def _absolute_vault_path(vault_root: Path | str) -> Path:
    raw_path = os.fspath(vault_root)
    if "\x00" in raw_path:
        raise ValueError("vault root may not contain NUL")
    return Path(os.path.abspath(os.path.expanduser(raw_path)))


def _open_absolute_directory_no_follow(path: Path) -> int:
    """Open every lexical component so a vault-root alias cannot be accepted."""

    if not path.is_absolute():
        raise ValueError("vault root must resolve to an absolute lexical path")
    current_fd = os.open(os.sep, _DIRECTORY_FLAGS | _OPEN_NOFOLLOW | _OPEN_CLOEXEC)
    try:
        for part in path.parts[1:]:
            next_fd = os.open(
                part,
                _DIRECTORY_FLAGS | _OPEN_NOFOLLOW | _OPEN_CLOEXEC,
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def _open_existing_relative_directory(root_fd: int, parts: tuple[str, ...]) -> int:
    current_fd = os.dup(root_fd)
    try:
        for part in parts:
            next_fd = os.open(
                part,
                _DIRECTORY_FLAGS | _OPEN_NOFOLLOW | _OPEN_CLOEXEC,
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def _open_or_create_parent(root_fd: int, parts: tuple[str, ...]) -> int:
    current_fd = os.dup(root_fd)
    try:
        for part in parts:
            try:
                # Fence an existing or concurrently-created child link before
                # accepting it as the parent of a later durable mutation.
                os.fsync(current_fd)
                next_fd = os.open(
                    part,
                    _DIRECTORY_FLAGS | _OPEN_NOFOLLOW | _OPEN_CLOEXEC,
                    dir_fd=current_fd,
                )
            except FileNotFoundError:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=current_fd)
                except FileExistsError:
                    # A cooperating creator won after our no-follow open.
                    # Fence its link before reopening its directory inode.
                    os.fsync(current_fd)
                    next_fd = os.open(
                        part,
                        _DIRECTORY_FLAGS | _OPEN_NOFOLLOW | _OPEN_CLOEXEC,
                        dir_fd=current_fd,
                    )
                else:
                    # The parent link and the created directory itself are both
                    # durability dependencies before a child can be trusted.
                    os.fsync(current_fd)
                    next_fd = os.open(
                        part,
                        _DIRECTORY_FLAGS | _OPEN_NOFOLLOW | _OPEN_CLOEXEC,
                        dir_fd=current_fd,
                    )
            # A freshly created child and an existing child both need a
            # directory fence before the next descendant is trusted.
            os.fsync(next_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def _open_or_create_recovery_directory(parent_fd: int) -> int:
    """Open the scanner-inert stage-retention namespace without following aliases."""

    try:
        os.fsync(parent_fd)
        recovery_fd = os.open(
            _RECOVERY_DIRECTORY,
            _DIRECTORY_FLAGS | _OPEN_NOFOLLOW | _OPEN_CLOEXEC,
            dir_fd=parent_fd,
        )
    except FileNotFoundError:
        try:
            os.mkdir(_RECOVERY_DIRECTORY, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        os.fsync(parent_fd)
        recovery_fd = os.open(
            _RECOVERY_DIRECTORY,
            _DIRECTORY_FLAGS | _OPEN_NOFOLLOW | _OPEN_CLOEXEC,
            dir_fd=parent_fd,
        )
    recovery_stat = os.fstat(recovery_fd)
    if not stat.S_ISDIR(recovery_stat.st_mode):
        os.close(recovery_fd)
        raise KnowledgeCapabilityError("atomic append recovery namespace must be a directory")
    os.fsync(recovery_fd)
    return recovery_fd


def _require_recovery_directory_binding(parent_fd: int, recovery_fd: int) -> None:
    try:
        entry_stat = os.stat(
            _RECOVERY_DIRECTORY,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError as exc:
        raise KnowledgeWriteConflict("atomic append recovery namespace disappeared") from exc
    held_stat = os.fstat(recovery_fd)
    if not stat.S_ISDIR(entry_stat.st_mode) or not _same_file_identity(entry_stat, held_stat):
        raise KnowledgeWriteConflict("atomic append recovery namespace identity changed")


def _free_capacity_name(index: int) -> str:
    return f"free-{index:04d}"


def _require_capacity_directory_binding(recovery_fd: int, capacity_fd: int) -> None:
    try:
        entry_stat = os.stat(
            _CAPACITY_DIRECTORY,
            dir_fd=recovery_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError as exc:
        raise KnowledgeWriteConflict("atomic append capacity namespace disappeared") from exc
    held_stat = os.fstat(capacity_fd)
    if not stat.S_ISDIR(entry_stat.st_mode) or not _same_file_identity(entry_stat, held_stat):
        raise KnowledgeWriteConflict("atomic append capacity namespace identity changed")


def _reserved_capacity_name(index: int) -> str:
    return f"reserved-{uuid.uuid4().hex}-{index:04d}"


def _capacity_slot_index(name: str) -> int | None:
    match = re.fullmatch(r"(?:free-\d{4}|reserved-(?:legacy|[0-9a-f]{32})-\d{4})", name)
    if match is None:
        return None
    try:
        return int(name[-4:])
    except ValueError:  # pragma: no cover - regex already constrains the suffix
        return None


def _open_or_initialize_capacity_directory(recovery_fd: int) -> int:
    """Open the atomic no-replace reservation pool for retained evidence."""

    try:
        capacity_fd = os.open(
            _CAPACITY_DIRECTORY,
            _DIRECTORY_FLAGS | _OPEN_NOFOLLOW | _OPEN_CLOEXEC,
            dir_fd=recovery_fd,
        )
    except FileNotFoundError:
        try:
            os.mkdir(_CAPACITY_DIRECTORY, mode=0o700, dir_fd=recovery_fd)
        except FileExistsError:
            pass
        os.fsync(recovery_fd)
        capacity_fd = os.open(
            _CAPACITY_DIRECTORY,
            _DIRECTORY_FLAGS | _OPEN_NOFOLLOW | _OPEN_CLOEXEC,
            dir_fd=recovery_fd,
        )
    try:
        legacy_count = sum(
            name.endswith(_RECOVERY_SUFFIX) for name in os.listdir(recovery_fd)
        )
        if legacy_count > _MAX_RECOVERY_ENTRIES:
            raise KnowledgeCapabilityError("atomic append recovery capacity is exhausted")
        if _CAPACITY_INITIALIZED not in os.listdir(capacity_fd):
            try:
                initializing_fd = os.open(
                    _CAPACITY_INITIALIZING,
                    _RECOVERY_OPEN_FLAGS,
                    0o600,
                    dir_fd=capacity_fd,
                )
            except FileExistsError:
                raise KnowledgeCapabilityError(
                    "atomic append recovery capacity initialization is incomplete"
                )
            else:
                try:
                    os.fsync(initializing_fd)
                    for index in range(_MAX_RECOVERY_ENTRIES):
                        name = (
                            f"reserved-legacy-{index:04d}"
                            if index < legacy_count
                            else _free_capacity_name(index)
                        )
                        slot_fd = os.open(
                            name,
                            _RECOVERY_OPEN_FLAGS,
                            0o600,
                            dir_fd=capacity_fd,
                        )
                        os.fsync(slot_fd)
                        os.close(slot_fd)
                    initialized_fd = os.open(
                        _CAPACITY_INITIALIZED,
                        _RECOVERY_OPEN_FLAGS,
                        0o600,
                        dir_fd=capacity_fd,
                    )
                    os.fsync(initialized_fd)
                    os.close(initialized_fd)
                    os.fsync(capacity_fd)
                finally:
                    os.close(initializing_fd)

        names = tuple(
            name
            for name in os.listdir(capacity_fd)
            if name not in {_CAPACITY_INITIALIZING, _CAPACITY_INITIALIZED}
        )
        indexed: dict[int, list[str]] = {}
        for name in names:
            slot_index = _capacity_slot_index(name)
            if slot_index is None or slot_index >= _MAX_RECOVERY_ENTRIES:
                raise KnowledgeCapabilityError("atomic append recovery capacity state is invalid")
            indexed.setdefault(slot_index, []).append(name)
        if len(indexed) != _MAX_RECOVERY_ENTRIES or any(
            len(indexed.get(index, [])) != 1 for index in range(_MAX_RECOVERY_ENTRIES)
        ):
            raise KnowledgeCapabilityError("atomic append recovery capacity state is incomplete")
        reserved_count = sum(
            name.startswith("reserved-") for names_for_index in indexed.values() for name in names_for_index
        )
        if legacy_count > reserved_count:
            raise KnowledgeCapabilityError("unreserved atomic append recovery evidence exists")
        os.fsync(capacity_fd)
        return capacity_fd
    except Exception:
        os.close(capacity_fd)
        raise


def _reserve_recovery_capacity(recovery_fd: int) -> _CapacityReservation:
    capacity_fd = _open_or_initialize_capacity_directory(recovery_fd)
    slots: list[_CapacitySlot] = []
    try:
        for index in range(_MAX_RECOVERY_ENTRIES):
            if len(slots) == 2:
                break
            free_name = _free_capacity_name(index)
            reserved_name = _reserved_capacity_name(index)
            try:
                _atomic_rename_noreplace_at(
                    capacity_fd,
                    free_name,
                    capacity_fd,
                    reserved_name,
                )
            except FileNotFoundError:
                continue
            slot_fd = os.open(reserved_name, _TARGET_OPEN_FLAGS, dir_fd=capacity_fd)
            descriptor_stat = os.fstat(slot_fd)
            entry_stat = os.stat(
                reserved_name,
                dir_fd=capacity_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(descriptor_stat.st_mode)
                or descriptor_stat.st_nlink != 1
                or not _same_file_identity(descriptor_stat, entry_stat)
            ):
                os.close(slot_fd)
                raise KnowledgeCapabilityError("atomic append recovery reservation changed")
            slots.append(_CapacitySlot(index, reserved_name, slot_fd))
        os.fsync(capacity_fd)
        if len(slots) != 2:
            raise KnowledgeCapabilityError("atomic append recovery capacity is exhausted")
        _require_capacity_directory_binding(recovery_fd, capacity_fd)
        return _CapacityReservation(capacity_fd, slots)
    except Exception:
        reservation = _CapacityReservation(capacity_fd, slots)
        _release_recovery_capacity(reservation)
        raise


def _consume_recovery_capacity(reservation: _CapacityReservation) -> None:
    for slot in reservation.slots:
        if not slot.consumed:
            slot.consumed = True
            os.close(slot.descriptor)
            slot.descriptor = -1
            return
    raise KnowledgeCapabilityError("atomic append recovery reservation is exhausted")


def _release_recovery_capacity(reservation: _CapacityReservation) -> None:
    release_error: BaseException | None = None
    for slot in reservation.slots:
        try:
            if not slot.consumed:
                free_name = _free_capacity_name(slot.index)
                _atomic_rename_noreplace_at(
                    reservation.directory,
                    slot.name,
                    reservation.directory,
                    free_name,
                )
                os.fsync(reservation.directory)
                entry_stat = os.stat(
                    free_name,
                    dir_fd=reservation.directory,
                    follow_symlinks=False,
                )
                if not _same_file_identity(entry_stat, os.fstat(slot.descriptor)):
                    raise KnowledgeWriteConflict("atomic append capacity release changed identity")
        except BaseException as exc:  # noqa: BLE001 - release must fail loud
            release_error = release_error or exc
        finally:
            if slot.descriptor >= 0:
                try:
                    os.close(slot.descriptor)
                except BaseException as exc:  # noqa: BLE001
                    release_error = release_error or exc
                slot.descriptor = -1
    try:
        os.close(reservation.directory)
    except BaseException as exc:  # noqa: BLE001
        release_error = release_error or exc
    if release_error is not None:
        raise release_error


def _read_fd(fd: int) -> bytes:
    size = os.fstat(fd).st_size
    chunks: list[bytes] = []
    offset = 0
    while offset < size:
        chunk = os.pread(fd, size - offset, offset)
        if not chunk:
            raise OSError(errno.EIO, "short descriptor-relative read")
        chunks.append(chunk)
        offset += len(chunk)
    return b"".join(chunks)


def _write_all(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(fd, payload[offset:])
        if written <= 0:
            raise OSError(errno.EIO, "append-reconcile stage write made no progress")
        offset += written


def _frame_commit_marker(operation_id: str, fingerprint: str) -> bytes:
    return (
        _FRAME_COMMIT_PREFIX
        + operation_id.encode("ascii")
        + b" "
        + fingerprint.encode("ascii")
        + b" -->\n"
    )


def _encode_frame(operation_id: str, fingerprint: str, payload: bytes) -> bytes:
    header = json.dumps(
        {"bytes": len(payload), "id": operation_id, "sha256": fingerprint, "v": 1},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return (
        _FRAME_PREFIX
        + header
        + _FRAME_HEADER_END
        + base64.b64encode(payload)
        + _frame_commit_marker(operation_id, fingerprint)
    )


def _parse_complete_records(target_bytes: bytes) -> tuple[AtomicAppendRecord, ...]:
    records: list[AtomicAppendRecord] = []
    offset = 0
    while True:
        start = target_bytes.find(_FRAME_PREFIX, offset)
        if start < 0:
            # Record Separator is not valid Markdown prose. Every truncated
            # byte of a frame opener is therefore explicit torn-record proof.
            for prefix_length in range(1, len(_FRAME_PREFIX)):
                if target_bytes.endswith(_FRAME_PREFIX[:prefix_length]):
                    raise AtomicAppendRecoveryError("partial atomic append frame prefix")
            return tuple(records)
        header_start = start + len(_FRAME_PREFIX)
        header_end = target_bytes.find(_FRAME_HEADER_END, header_start)
        if header_end < 0:
            raise AtomicAppendRecoveryError("partial atomic append frame header")
        try:
            header = json.loads(target_bytes[header_start:header_end])
            operation_id = header["id"]
            fingerprint = header["sha256"]
            byte_count = header["bytes"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AtomicAppendRecoveryError("invalid atomic append frame header") from exc
        if (
            header.get("v") != 1
            or not isinstance(operation_id, str)
            or _OPERATION_ID.fullmatch(operation_id) is None
            or not isinstance(fingerprint, str)
            or not re.fullmatch(r"[0-9a-f]{64}", fingerprint)
            or not isinstance(byte_count, int)
            or byte_count < 0
        ):
            raise AtomicAppendRecoveryError("invalid atomic append frame identity")
        payload_start = header_end + len(_FRAME_HEADER_END)
        commit = _frame_commit_marker(operation_id, fingerprint)
        payload_end = target_bytes.find(commit, payload_start)
        if payload_end < 0:
            raise AtomicAppendRecoveryError("partial atomic append frame commit marker")
        try:
            payload = base64.b64decode(target_bytes[payload_start:payload_end], validate=True)
        except ValueError as exc:
            raise AtomicAppendRecoveryError("invalid atomic append frame payload") from exc
        if len(payload) != byte_count or hashlib.sha256(payload).hexdigest() != fingerprint:
            raise AtomicAppendRecoveryError("atomic append frame payload does not match its digest")
        record = AtomicAppendRecord(operation_id, fingerprint, payload)
        if any(previous.operation_id == operation_id for previous in records):
            raise AtomicAppendRecoveryError("duplicate committed atomic append identity")
        records.append(record)
        offset = payload_end + len(commit)


def _snapshot_metadata(
    fd: int,
    *,
    allow_unlinked: bool = False,
) -> tuple[int, int, int, dict[str, bytes], bytes]:
    target_stat = os.fstat(fd)
    if not stat.S_ISREG(target_stat.st_mode):
        raise KnowledgeCapabilityError("atomic append target must be a regular file")
    acceptable_links = {0, 1} if allow_unlinked else {1}
    if target_stat.st_nlink not in acceptable_links:
        raise KnowledgeCapabilityError("atomic append target may not have hard-link aliases")
    try:
        names = _list_xattrs(fd)
        xattrs = {name: _get_xattr(fd, name) for name in names}
        acl = _acl_text(fd)
    except OSError as exc:
        raise KnowledgeCapabilityError("cannot read target ACL or extended metadata") from exc
    return stat.S_IMODE(target_stat.st_mode), target_stat.st_uid, target_stat.st_gid, xattrs, acl


def _apply_and_verify_metadata(
    stage_fd: int,
    source_fd: int,
    metadata: tuple[int, int, int, dict[str, bytes], bytes],
) -> None:
    mode, uid, gid, xattrs, acl = metadata
    try:
        os.fchown(stage_fd, uid, gid)
        os.fchmod(stage_fd, mode)
        _clone_acl(source_fd, stage_fd)
        for name, value in xattrs.items():
            _set_xattr(stage_fd, name, value)
        stage_stat = os.fstat(stage_fd)
        if (
            stat.S_IMODE(stage_stat.st_mode) != mode
            or stage_stat.st_uid != uid
            or stage_stat.st_gid != gid
            or set(_list_xattrs(stage_fd)) != set(xattrs)
            or any(_get_xattr(stage_fd, name) != value for name, value in xattrs.items())
            or _acl_text(stage_fd) != acl
        ):
            raise KnowledgeCapabilityError("replacement metadata cannot be proven exact")
    except OSError as exc:
        raise KnowledgeCapabilityError("cannot preserve target ACL or extended metadata") from exc


def _open_or_create_target(parent_fd: int, target_name: str) -> int:
    while True:
        try:
            target_fd = os.open(target_name, _TARGET_OPEN_FLAGS, dir_fd=parent_fd)
        except FileNotFoundError:
            try:
                target_fd = os.open(
                    target_name,
                    os.O_RDWR | os.O_CREAT | os.O_EXCL | _OPEN_NOFOLLOW | _OPEN_CLOEXEC,
                    0o600,
                    dir_fd=parent_fd,
                )
            except FileExistsError:
                continue
            os.fsync(target_fd)
            os.fsync(parent_fd)
        target_stat = os.fstat(target_fd)
        if not stat.S_ISREG(target_stat.st_mode):
            os.close(target_fd)
            raise KnowledgeCapabilityError("atomic append target must be a regular file")
        return target_fd


def _canonical_target_entry(
    parent_fd: int, requested_name: str, target_stat: os.stat_result
) -> str:
    """Resolve the caller-authorized target entry without accepting a rename.

    The directory scan obtains the stable on-disk spelling used to derive the
    lock name on case-insensitive filesystems.  It is not authority to follow
    the inode to another name: the name requested by the caller must still
    resolve to that exact inode first.
    """

    if target_stat.st_nlink != 1:
        raise KnowledgeCapabilityError("atomic append target may not have hard-link aliases")
    matches: list[str] = []
    for name in os.listdir(parent_fd):
        try:
            candidate = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        if _same_file_identity(candidate, target_stat):
            matches.append(name)
    if len(matches) != 1:
        raise KnowledgeCapabilityError("atomic append target does not have one canonical entry")
    try:
        requested_stat = os.stat(requested_name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError as exc:
        requested_stat = None
        request_error: BaseException | None = exc
    else:
        request_error = None
    if requested_stat is None or not _same_file_identity(requested_stat, target_stat):
        # A stage-looking filename is untrusted input: a non-cooperating actor
        # can choose it too.  A caller retry after this explicit CAS conflict
        # will reopen the authorized path, but this attempt never follows an
        # inode that was renamed away from that path.
        raise KnowledgeWriteConflict(
            "caller-authorized vault target path changed before lock acquisition"
        ) from request_error
    return matches[0]


def _target_lock_name(parent_fd: int, target_name: str) -> str:
    parent_stat = os.fstat(parent_fd)
    # A filesystem may resolve case and Unicode aliases to one entry.  A
    # collision on a case-sensitive filesystem is merely extra serialization;
    # failing to collide on an aliasing filesystem would violate the CAS.
    lock_identity = unicodedata.normalize("NFC", target_name).casefold()
    digest = hashlib.sha256(
        f"{parent_stat.st_dev}:{parent_stat.st_ino}:{lock_identity}".encode("utf-8")
    ).hexdigest()
    return f".atomic-append-reconcile-{digest}.lock"


def _stage_scope_prefix(target_name: str, operation_id: str) -> str:
    target_digest = hashlib.sha256(target_name.encode("utf-8")).hexdigest()[:32]
    operation_digest = hashlib.sha256(operation_id.encode("ascii")).hexdigest()[:32]
    return f".atomic-append-reconcile-{target_digest}-{operation_digest}.stage-"


def _stage_prefix(target_name: str, operation_id: str, fingerprint: str) -> str:
    fingerprint_digest = hashlib.sha256(fingerprint.encode("ascii")).hexdigest()[:32]
    return f"{_stage_scope_prefix(target_name, operation_id)}{fingerprint_digest}-"


def _open_target_lock(parent_fd: int, target_name: str) -> int:
    """Acquire a per-target lock inode that remains stable across exchange."""

    lock_name = _target_lock_name(parent_fd, target_name)
    try:
        lock_fd = os.open(lock_name, _LOCK_OPEN_FLAGS, 0o600, dir_fd=parent_fd)
    except FileNotFoundError:  # pragma: no cover - O_CREAT makes this defensive
        raise KnowledgeCapabilityError("cannot create the descriptor-bound append lock")
    try:
        lock_stat = os.fstat(lock_fd)
        if not stat.S_ISREG(lock_stat.st_mode):
            raise KnowledgeCapabilityError("atomic append lock must be a regular file")
        os.fsync(lock_fd)
        os.fsync(parent_fd)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        return lock_fd
    except Exception:
        os.close(lock_fd)
        raise


def _stage_inventory_names(
    parent_fd: int,
    recovery_fd: int,
    scope_prefix: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    active = tuple(sorted(name for name in os.listdir(parent_fd) if name.startswith(scope_prefix)))
    retained_candidates = tuple(
        sorted(name for name in os.listdir(recovery_fd) if name.startswith(scope_prefix))
    )
    if any(not name.endswith(_RECOVERY_SUFFIX) for name in retained_candidates):
        raise AtomicAppendRecoveryError("append recovery inventory has an invalid retained name")
    retained = retained_candidates
    return active, retained


def _open_inventory_entry(
    directory_fd: int,
    namespace: Literal["active", "retained"],
    name: str,
) -> _InventoryEntry:
    try:
        descriptor = os.open(name, _TARGET_OPEN_FLAGS, dir_fd=directory_fd)
        descriptor_stat = os.fstat(descriptor)
        entry_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except OSError as exc:
        if "descriptor" in locals():
            os.close(descriptor)
        raise AtomicAppendRecoveryError(
            f"cannot bind {namespace} append recovery entry"
        ) from exc
    if (
        not stat.S_ISREG(descriptor_stat.st_mode)
        or descriptor_stat.st_nlink != 1
        or not _same_file_identity(descriptor_stat, entry_stat)
    ):
        os.close(descriptor)
        raise AtomicAppendRecoveryError(
            f"{namespace} append recovery entry is not one exclusive regular inode"
        )
    return _InventoryEntry(namespace, name, descriptor)


def _close_inventory(entries: tuple[_InventoryEntry, ...]) -> None:
    for entry in entries:
        os.close(entry.descriptor)


def _open_stable_stage_inventory(
    parent_fd: int,
    recovery_fd: int,
    scope_prefix: str,
) -> tuple[_InventoryEntry, ...]:
    """Open a stable target/operation inventory without following mutable names."""

    before_active, before_retained = _stage_inventory_names(
        parent_fd,
        recovery_fd,
        scope_prefix,
    )
    if len(before_active) > 1:
        raise AtomicAppendRecoveryError("multiple active append recovery entries are ambiguous")
    entries: list[_InventoryEntry] = []
    try:
        entries.extend(
            _open_inventory_entry(parent_fd, "active", name) for name in before_active
        )
        entries.extend(
            _open_inventory_entry(recovery_fd, "retained", name)
            for name in before_retained
        )
        after_active, after_retained = _stage_inventory_names(
            parent_fd,
            recovery_fd,
            scope_prefix,
        )
        if (before_active, before_retained) != (after_active, after_retained):
            raise AtomicAppendRecoveryError("append recovery inventory changed during enumeration")
        for entry in entries:
            directory_fd = parent_fd if entry.namespace == "active" else recovery_fd
            descriptor_stat = os.fstat(entry.descriptor)
            entry_stat = os.stat(entry.name, dir_fd=directory_fd, follow_symlinks=False)
            if not _same_file_identity(descriptor_stat, entry_stat):
                raise AtomicAppendRecoveryError(
                    "append recovery entry changed during enumeration"
                )
        return tuple(entries)
    except Exception:
        _close_inventory(tuple(entries))
        raise


def _validate_inventory_payloads(
    entries: tuple[_InventoryEntry, ...],
    *,
    operation_id: str,
    payload_fingerprint: str,
    target_has_operation: bool,
) -> None:
    for entry in entries:
        records = _parse_complete_records(_read_fd(entry.descriptor))
        matching = [record for record in records if record.operation_id == operation_id]
        if any(record.payload_fingerprint != payload_fingerprint for record in matching):
            raise AtomicAppendIdentityCollision(
                f"atomic append identity collision for {operation_id}"
            )
        if not target_has_operation and not matching:
            raise AtomicAppendRecoveryError(
                f"{entry.namespace} append recovery entry has another identity"
            )


def _classify_interrupted_stages(
    parent_fd: int,
    recovery_fd: int,
    scope_prefix: str,
    operation_id: str,
    payload_fingerprint: str,
    target_records: tuple[AtomicAppendRecord, ...],
    capacity: _CapacityReservation,
) -> None:
    """Validate both namespaces and descriptor-retire any interrupted active stage."""

    target_has_operation = any(
        record.operation_id == operation_id for record in target_records
    )
    entries = _open_stable_stage_inventory(
        parent_fd,
        recovery_fd,
        scope_prefix,
    )
    try:
        _validate_inventory_payloads(
            entries,
            operation_id=operation_id,
            payload_fingerprint=payload_fingerprint,
            target_has_operation=target_has_operation,
        )
        active = tuple(entry for entry in entries if entry.namespace == "active")
        if not active:
            return
        receipt = _retire_owned_stage(
            parent_fd,
            active[0].name,
            active[0].descriptor,
            recovery_fd,
            capacity,
        )
        try:
            _revalidate_retirement(
                receipt,
                recovery_fd,
                active[0].descriptor,
                capacity,
            )
        finally:
            os.close(receipt.descriptor)
        raise AtomicAppendRecoveryError(
            "interrupted active append stage was retained; retry required"
        )
    finally:
        _close_inventory(entries)


def _require_anchored_identity(
    vault_path: Path,
    root_stat: os.stat_result,
    parent_parts: tuple[str, ...],
    parent_fd: int,
    parent_stat: os.stat_result,
    target_name: str,
    target_stat: os.stat_result,
) -> None:
    fresh_root_fd = _open_absolute_directory_no_follow(vault_path)
    fresh_parent_fd = -1
    try:
        if not _same_file_identity(os.fstat(fresh_root_fd), root_stat):
            raise _RetryAnchoredIdentity("vault root identity changed")
        try:
            fresh_parent_fd = _open_existing_relative_directory(fresh_root_fd, parent_parts)
        except FileNotFoundError as exc:
            raise _RetryAnchoredIdentity("vault parent disappeared") from exc
        if not _same_file_identity(os.fstat(fresh_parent_fd), parent_stat):
            raise _RetryAnchoredIdentity("vault parent identity changed")
        if not _same_file_identity(os.fstat(parent_fd), parent_stat):
            raise _RetryAnchoredIdentity("held vault parent identity changed")
        try:
            entry_stat = os.stat(target_name, dir_fd=fresh_parent_fd, follow_symlinks=False)
        except FileNotFoundError as exc:
            raise _RetryAnchoredIdentity("vault target disappeared") from exc
        if not _same_file_identity(entry_stat, target_stat):
            raise _RetryAnchoredIdentity("vault target identity changed")
    finally:
        if fresh_parent_fd >= 0:
            os.close(fresh_parent_fd)
        os.close(fresh_root_fd)


def _recovery_name(stage_name: str, *, snapshot: bool = False) -> str:
    kind = "snapshot" if snapshot else "retained"
    return f"{stage_name}.{uuid.uuid4().hex}.{kind}{_RECOVERY_SUFFIX}"


def _retain_untrusted_stage(
    parent_fd: int,
    stage_name: str,
    recovery_fd: int,
    capacity: _CapacityReservation,
) -> str | None:
    """Move an active stage aside without deleting or overwriting any entry."""

    for _attempt in range(9):
        retained_name = _recovery_name(stage_name)
        try:
            _atomic_rename_noreplace_at(
                parent_fd,
                stage_name,
                recovery_fd,
                retained_name,
            )
        except FileNotFoundError:
            return None
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                continue
            raise
        # The reservation becomes permanent at the namespace transition.  It
        # must not be released if a later durability fence fails or the process
        # crashes before returning from this helper.
        _consume_recovery_capacity(capacity)
        os.fsync(parent_fd)
        os.fsync(recovery_fd)
        return retained_name
    raise KnowledgeCapabilityError("cannot allocate atomic append recovery entry")


def _snapshot_owned_descriptor(
    owner_fd: int,
    recovery_fd: int,
    stage_name: str,
    capacity: _CapacityReservation,
) -> str:
    """Durably copy a still-open owner inode after its directory link was lost."""

    owner_stat = os.fstat(owner_fd)
    if not stat.S_ISREG(owner_stat.st_mode):
        raise KnowledgeWriteConflict("atomic append cleanup owner is not a regular file")
    payload = _read_fd(owner_fd)
    metadata = _snapshot_metadata(owner_fd, allow_unlinked=True)
    snapshot_fd = -1
    snapshot_name = ""
    for _attempt in range(9):
        snapshot_name = _recovery_name(stage_name, snapshot=True)
        try:
            snapshot_fd = os.open(
                snapshot_name,
                _RECOVERY_OPEN_FLAGS,
                0o600,
                dir_fd=recovery_fd,
            )
        except FileExistsError:
            continue
        _consume_recovery_capacity(capacity)
        break
    else:
        raise KnowledgeCapabilityError("cannot allocate descriptor-owned recovery snapshot")
    try:
        _apply_and_verify_metadata(snapshot_fd, owner_fd, metadata)
        _write_all(snapshot_fd, payload)
        os.fsync(snapshot_fd)
        snapshot_stat = os.fstat(snapshot_fd)
        entry_stat = os.stat(snapshot_name, dir_fd=recovery_fd, follow_symlinks=False)
        if (
            not _same_file_identity(snapshot_stat, entry_stat)
            or _read_fd(snapshot_fd) != payload
            or _snapshot_metadata(snapshot_fd) != metadata
        ):
            raise KnowledgeWriteConflict("descriptor-owned recovery snapshot changed")
        os.fsync(recovery_fd)
        return snapshot_name
    finally:
        os.close(snapshot_fd)


def _retire_owned_stage(
    parent_fd: int,
    stage_name: str,
    owner_fd: int,
    recovery_fd: int,
    capacity: _CapacityReservation,
) -> _RetirementReceipt:
    """Retire a stage by descriptor identity without unlinking a mutable name."""

    owner_stat = os.fstat(owner_fd)
    if not stat.S_ISREG(owner_stat.st_mode):
        raise KnowledgeWriteConflict("atomic append cleanup owner is not a regular file")
    retained_name = _retain_untrusted_stage(
        parent_fd,
        stage_name,
        recovery_fd,
        capacity,
    )
    if retained_name is None:
        snapshot_name = _snapshot_owned_descriptor(
            owner_fd,
            recovery_fd,
            stage_name,
            capacity,
        )
        raise KnowledgeWriteConflict(
            "atomic append cleanup entry disappeared; "
            f"owner retained as {_RECOVERY_DIRECTORY}/{snapshot_name}"
        )
    retained_fd = -1
    try:
        try:
            retained_fd = os.open(retained_name, _TARGET_OPEN_FLAGS, dir_fd=recovery_fd)
        except OSError as exc:
            snapshot_name = _snapshot_owned_descriptor(
                owner_fd,
                recovery_fd,
                stage_name,
                capacity,
            )
            raise KnowledgeWriteConflict(
                "atomic append retained entry cannot be descriptor-bound; "
                f"owner retained as {_RECOVERY_DIRECTORY}/{snapshot_name}"
            ) from exc
        moved = os.fstat(retained_fd)
        moved_entry = os.stat(retained_name, dir_fd=recovery_fd, follow_symlinks=False)
        owner_after = os.fstat(owner_fd)
        if not _same_file_identity(moved, moved_entry):
            snapshot_name = _snapshot_owned_descriptor(
                owner_fd,
                recovery_fd,
                stage_name,
                capacity,
            )
            raise KnowledgeWriteConflict(
                "atomic append retained entry changed after retirement; "
                f"owner retained as {_RECOVERY_DIRECTORY}/{snapshot_name}"
            )
        if _same_file_identity(moved, owner_after):
            if owner_after.st_nlink == 0:
                snapshot_name = _snapshot_owned_descriptor(
                    owner_fd,
                    recovery_fd,
                    stage_name,
                    capacity,
                )
                raise KnowledgeWriteConflict(
                    "atomic append cleanup owner lost its retained link; "
                    f"owner retained as {_RECOVERY_DIRECTORY}/{snapshot_name}"
                )
            if moved.st_nlink != 1 or owner_after.st_nlink != 1:
                raise KnowledgeWriteConflict(
                    "atomic append cleanup owner acquired a hard-link alias; entry retained"
                )
            receipt = _RetirementReceipt(stage_name, retained_name, retained_fd)
            retained_fd = -1
            return receipt

        snapshot_name = _snapshot_owned_descriptor(
            owner_fd,
            recovery_fd,
            stage_name,
            capacity,
        )
        try:
            _atomic_rename_noreplace_at(
                recovery_fd,
                retained_name,
                parent_fd,
                stage_name,
            )
        except OSError as exc:
            os.fsync(parent_fd)
            os.fsync(recovery_fd)
            retained_entry = os.stat(
                retained_name,
                dir_fd=recovery_fd,
                follow_symlinks=False,
            )
            if not _same_file_identity(retained_entry, moved):
                raise KnowledgeWriteConflict(
                    "foreign atomic append cleanup entry changed after restoration collision"
                ) from exc
            raise KnowledgeWriteConflict(
                "foreign atomic append cleanup entry retained after restoration collision; "
                f"owner retained as {_RECOVERY_DIRECTORY}/{snapshot_name}"
            ) from exc
        os.fsync(recovery_fd)
        os.fsync(parent_fd)
        restored = os.stat(stage_name, dir_fd=parent_fd, follow_symlinks=False)
        if not _same_file_identity(restored, moved):
            raise KnowledgeWriteConflict(
                "foreign atomic append cleanup entry changed during restoration"
            )
        raise KnowledgeWriteConflict(
            "foreign atomic append cleanup entry restored without deletion; "
            f"owner retained as {_RECOVERY_DIRECTORY}/{snapshot_name}"
        )
    finally:
        if retained_fd >= 0:
            os.close(retained_fd)


def _revalidate_retirement(
    receipt: _RetirementReceipt,
    recovery_fd: int,
    owner_fd: int,
    capacity: _CapacityReservation,
) -> None:
    try:
        entry_stat = os.stat(receipt.name, dir_fd=recovery_fd, follow_symlinks=False)
    except FileNotFoundError as exc:
        snapshot_name = _snapshot_owned_descriptor(
            owner_fd,
            recovery_fd,
            receipt.stage_name,
            capacity,
        )
        raise KnowledgeWriteConflict(
            "retained append recovery entry disappeared; "
            f"owner retained as {_RECOVERY_DIRECTORY}/{snapshot_name}"
        ) from exc
    retained_stat = os.fstat(receipt.descriptor)
    owner_stat = os.fstat(owner_fd)
    if (
        not stat.S_ISREG(retained_stat.st_mode)
        or retained_stat.st_nlink != 1
        or owner_stat.st_nlink != 1
        or not _same_file_identity(retained_stat, entry_stat)
        or not _same_file_identity(retained_stat, owner_stat)
    ):
        snapshot_name = _snapshot_owned_descriptor(
            owner_fd,
            recovery_fd,
            receipt.stage_name,
            capacity,
        )
        raise KnowledgeWriteConflict(
            "retained append recovery ownership changed before final proof; "
            f"owner retained as {_RECOVERY_DIRECTORY}/{snapshot_name}"
        )


def _require_open_descriptor_payload_and_metadata(
    descriptor: int,
    expected_payload: bytes,
    expected_metadata: tuple[int, int, int, dict[str, bytes], bytes],
) -> None:
    descriptor_stat = os.fstat(descriptor)
    if not stat.S_ISREG(descriptor_stat.st_mode) or descriptor_stat.st_nlink != 1:
        raise KnowledgeWriteConflict("atomic append publication acquired a hard-link alias")
    if _read_fd(descriptor) != expected_payload:
        raise KnowledgeWriteConflict("atomic append payload changed at publication")
    if _snapshot_metadata(descriptor) != expected_metadata:
        raise KnowledgeWriteConflict("atomic append metadata changed at publication")


def _require_descriptor_payload_and_metadata(
    parent_fd: int,
    name: str,
    expected_payload: bytes,
    expected_metadata: tuple[int, int, int, dict[str, bytes], bytes],
) -> None:
    descriptor = -1
    try:
        descriptor = os.open(name, _TARGET_OPEN_FLAGS, dir_fd=parent_fd)
        _require_open_descriptor_payload_and_metadata(
            descriptor,
            expected_payload,
            expected_metadata,
        )
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _validated_reconciliation(
    candidate: bytes,
    records: tuple[AtomicAppendRecord, ...],
    reconcile: ReconcileCallback,
) -> bytes:
    reconciled = reconcile(candidate, records)
    if reconciled is None:
        return candidate
    if isinstance(reconciled, str):
        reconciled = reconciled.encode("utf-8")
    if not isinstance(reconciled, bytes):
        raise TypeError("reconcile callback must return bytes, str, or None")
    if _parse_complete_records(reconciled) != records:
        raise AtomicAppendRecoveryError(
            "reconcile callback changed the committed atomic append records"
        )
    return reconciled


def atomic_append_reconcile_relative(
    note_rel_path: str,
    *,
    operation_id: str,
    payload: str | bytes,
    payload_fingerprint: str,
    vault_root: Path | str,
    action: str,
    write_guard: WriteGuard | None = None,
    reconcile: ReconcileCallback,
) -> AtomicAppendReconcileResult:
    """Append one framed record and reconcile derived bytes under an identity CAS.

    ``reconcile`` is called only after all existing frames were verified complete.
    It must be pure and retain the exact committed frame set it receives.  A
    repeated identity with the same fingerprint runs reconciliation again and
    returns ``reconciled_replay``; a differing fingerprint fails before any
    replacement is published.
    """

    from app.write_guard import DEFAULT_WRITE_GUARD

    _require_platform_primitives()
    parts = _relative_parts(note_rel_path)
    if _OPERATION_ID.fullmatch(operation_id) is None:
        raise ValueError("operation identity must be stable portable ASCII")
    payload_bytes = payload.encode("utf-8") if isinstance(payload, str) else payload
    if not isinstance(payload_bytes, bytes):
        raise TypeError("payload must be bytes or UTF-8 text")
    expected_fingerprint = hashlib.sha256(payload_bytes).hexdigest()
    if payload_fingerprint != expected_fingerprint:
        raise ValueError("payload fingerprint must equal SHA-256 of the supplied payload")
    guard = write_guard or DEFAULT_WRITE_GUARD
    guard.assert_writes_allowed(action)

    vault_path = _absolute_vault_path(vault_root)
    parent_parts = parts[:-1]
    target_name = parts[-1]
    for attempt in range(16):
        root_fd = -1
        parent_fd = -1
        recovery_fd = -1
        lock_fd = -1
        target_fd = -1
        stage_fd = -1
        stage_name: str | None = None
        stage_stat: os.stat_result | None = None
        stage_owned = False
        retirement_receipt: _RetirementReceipt | None = None
        capacity: _CapacityReservation | None = None
        try:
            root_fd = _open_absolute_directory_no_follow(vault_path)
            root_stat = os.fstat(root_fd)
            parent_fd = _open_or_create_parent(root_fd, parent_parts)
            parent_stat = os.fstat(parent_fd)
            target_fd = _open_or_create_target(parent_fd, target_name)
            target_stat = os.fstat(target_fd)
            if target_stat.st_nlink != 1:
                raise KnowledgeCapabilityError("atomic append target may not have hard-link aliases")
            # The lock is keyed from the caller-authorized lexical component
            # (normalised for aliasing filesystems), not an inode discovered
            # before the lock.  Once acquired, revalidation below retries a
            # cooperating exchange rather than treating its displaced inode as
            # authority for another path.
            lock_fd = _open_target_lock(parent_fd, target_name)
            try:
                _require_anchored_identity(
                    vault_path,
                    root_stat,
                    parent_parts,
                    parent_fd,
                    parent_stat,
                    target_name,
                    target_stat,
                )
            except _RetryAnchoredIdentity:
                continue
            target_entry = _canonical_target_entry(parent_fd, target_name, target_stat)
            recovery_fd = _open_or_create_recovery_directory(parent_fd)
            _require_recovery_directory_binding(parent_fd, recovery_fd)
            capacity = _reserve_recovery_capacity(recovery_fd)

            original = _read_fd(target_fd)
            records = _parse_complete_records(original)
            stage_scope_prefix = _stage_scope_prefix(target_entry, operation_id)
            stage_prefix = _stage_prefix(target_entry, operation_id, payload_fingerprint)
            _classify_interrupted_stages(
                parent_fd,
                recovery_fd,
                stage_scope_prefix,
                operation_id,
                payload_fingerprint,
                records,
                capacity,
            )
            matching = [record for record in records if record.operation_id == operation_id]
            if matching and matching[0].payload_fingerprint != payload_fingerprint:
                raise AtomicAppendIdentityCollision(
                    f"atomic append identity collision for {operation_id}"
                )
            outcome: Literal["appended", "reconciled_replay"]
            if matching:
                outcome = "reconciled_replay"
                candidate = original
            else:
                outcome = "appended"
                candidate = original + _encode_frame(
                    operation_id, payload_fingerprint, payload_bytes
                )
                records = records + (
                    AtomicAppendRecord(operation_id, payload_fingerprint, payload_bytes),
                )
            replacement = _validated_reconciliation(candidate, records, reconcile)
            metadata = _snapshot_metadata(target_fd)

            stage_name = f"{stage_prefix}{uuid.uuid4().hex}"
            stage_fd = os.open(stage_name, _STAGE_OPEN_FLAGS, 0o600, dir_fd=parent_fd)
            stage_stat = os.fstat(stage_fd)
            stage_owned = True
            _apply_and_verify_metadata(stage_fd, target_fd, metadata)
            _write_all(stage_fd, replacement)
            os.fsync(stage_fd)
            stage_stat = os.fstat(stage_fd)
            if not stat.S_ISREG(stage_stat.st_mode) or stage_stat.st_nlink != 1:
                raise KnowledgeWriteConflict("atomic append stage acquired a hard-link alias")

            # A same-inode path writer is not caught by directory identity, so
            # bind the staged bytes to one final descriptor read as well.
            if _read_fd(target_fd) != original:
                raise KnowledgeWriteConflict("atomic append target bytes changed during reconciliation")
            if _snapshot_metadata(target_fd) != metadata:
                raise KnowledgeWriteConflict("atomic append metadata changed during reconciliation")
            try:
                _require_anchored_identity(
                    vault_path,
                    root_stat,
                    parent_parts,
                    parent_fd,
                    parent_stat,
                    target_entry,
                    target_stat,
                )
            except _RetryAnchoredIdentity:
                continue

            _atomic_exchange_at(parent_fd, target_entry, parent_fd, stage_name)
            stage_owned = False
            try:
                # Both names now carry durable recovery meaning. Fence the swap
                # before classifying the entry that occupies the displaced name.
                os.fsync(parent_fd)
                published = os.stat(target_entry, dir_fd=parent_fd, follow_symlinks=False)
                displaced = os.stat(stage_name, dir_fd=parent_fd, follow_symlinks=False)
                published_owner = os.fstat(stage_fd)
                displaced_owner = os.fstat(target_fd)
                if (
                    not _same_file_identity(published, published_owner)
                    or not _same_file_identity(published_owner, stage_stat)
                    or not _same_file_identity(displaced, displaced_owner)
                    or not _same_file_identity(displaced_owner, target_stat)
                ):
                    raise KnowledgeWriteConflict(
                        "atomic append target identity changed at publication; recovery stage retained"
                    )
                if published.st_nlink != 1 or displaced.st_nlink != 1:
                    raise KnowledgeWriteConflict(
                        "atomic append publication acquired a hard-link alias; recovery stage retained"
                    )
                _require_open_descriptor_payload_and_metadata(stage_fd, replacement, metadata)
                _require_open_descriptor_payload_and_metadata(target_fd, original, metadata)
                try:
                    _require_anchored_identity(
                        vault_path,
                        root_stat,
                        parent_parts,
                        parent_fd,
                        parent_stat,
                        target_entry,
                        stage_stat,
                    )
                except _RetryAnchoredIdentity as exc:
                    raise KnowledgeWriteConflict(
                        "atomic append vault chain changed after publication; recovery stage retained"
                    ) from exc
            finally:
                retirement_receipt = _retire_owned_stage(
                    parent_fd,
                    stage_name,
                    target_fd,
                    recovery_fd,
                    capacity,
                )
                _require_recovery_directory_binding(parent_fd, recovery_fd)

            # Cleanup is a state transition too.  Re-read the surviving
            # descriptor after the cleanup fence so a write racing either the
            # publication proof or the cleanup cannot be reported as success.
            _require_descriptor_payload_and_metadata(
                parent_fd, target_entry, replacement, metadata
            )
            try:
                _require_anchored_identity(
                    vault_path,
                    root_stat,
                    parent_parts,
                    parent_fd,
                    parent_stat,
                    target_entry,
                    stage_stat,
                )
            except _RetryAnchoredIdentity as exc:
                raise KnowledgeWriteConflict(
                    "atomic append vault chain changed during cleanup"
                ) from exc
            final_inventory = _open_stable_stage_inventory(
                parent_fd,
                recovery_fd,
                stage_scope_prefix,
            )
            try:
                _validate_inventory_payloads(
                    final_inventory,
                    operation_id=operation_id,
                    payload_fingerprint=payload_fingerprint,
                    target_has_operation=True,
                )
                if any(entry.namespace == "active" for entry in final_inventory):
                    raise KnowledgeWriteConflict(
                        "atomic append cleanup left an active recovery entry"
                    )
                if retirement_receipt is None:
                    raise KnowledgeWriteConflict("atomic append cleanup has no retirement proof")
                _revalidate_retirement(
                    retirement_receipt,
                    recovery_fd,
                    target_fd,
                    capacity,
                )
                if not any(
                    entry.namespace == "retained"
                    and entry.name == retirement_receipt.name
                    and _same_file_identity(
                        os.fstat(entry.descriptor),
                        os.fstat(retirement_receipt.descriptor),
                    )
                    for entry in final_inventory
                ):
                    raise KnowledgeWriteConflict(
                        "atomic append retirement is absent from the final inventory"
                    )
            finally:
                _close_inventory(final_inventory)
            _require_recovery_directory_binding(parent_fd, recovery_fd)
            _require_capacity_directory_binding(recovery_fd, capacity.directory)
            return AtomicAppendReconcileResult(outcome, operation_id, payload_fingerprint)
        except _RetryAnchoredIdentity:
            pass
        finally:
            cleanup_error: BaseException | None = None
            if (
                stage_owned
                and stage_name is not None
                and stage_fd >= 0
                and parent_fd >= 0
                and recovery_fd >= 0
                and capacity is not None
            ):
                try:
                    cleanup_receipt = _retire_owned_stage(
                        parent_fd,
                        stage_name,
                        stage_fd,
                        recovery_fd,
                        capacity,
                    )
                    try:
                        _revalidate_retirement(
                            cleanup_receipt,
                            recovery_fd,
                            stage_fd,
                            capacity,
                        )
                    finally:
                        os.close(cleanup_receipt.descriptor)
                except BaseException as exc:  # noqa: BLE001 - cleanup must be fail-loud
                    cleanup_error = exc
            if retirement_receipt is not None:
                try:
                    os.close(retirement_receipt.descriptor)
                except BaseException as exc:  # noqa: BLE001 - preserve a close failure
                    cleanup_error = cleanup_error or exc
            if stage_fd >= 0:
                try:
                    os.close(stage_fd)
                except BaseException as exc:  # noqa: BLE001 - preserve a close failure
                    cleanup_error = cleanup_error or exc
            if target_fd >= 0:
                try:
                    os.close(target_fd)
                except BaseException as exc:  # noqa: BLE001 - preserve a close failure
                    cleanup_error = cleanup_error or exc
            if capacity is not None:
                try:
                    if recovery_fd >= 0:
                        _require_capacity_directory_binding(recovery_fd, capacity.directory)
                except BaseException as exc:  # noqa: BLE001 - binding must fail loud
                    cleanup_error = cleanup_error or exc
                try:
                    _release_recovery_capacity(capacity)
                except BaseException as exc:  # noqa: BLE001 - release must fail loud
                    cleanup_error = cleanup_error or exc
            if recovery_fd >= 0:
                try:
                    os.close(recovery_fd)
                except BaseException as exc:  # noqa: BLE001 - preserve a close failure
                    cleanup_error = cleanup_error or exc
            if lock_fd >= 0:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    os.close(lock_fd)
                except BaseException as exc:  # noqa: BLE001 - preserve a close failure
                    cleanup_error = cleanup_error or exc
            if parent_fd >= 0:
                try:
                    os.close(parent_fd)
                except BaseException as exc:  # noqa: BLE001 - preserve a close failure
                    cleanup_error = cleanup_error or exc
            if root_fd >= 0:
                try:
                    os.close(root_fd)
                except BaseException as exc:  # noqa: BLE001 - preserve a close failure
                    cleanup_error = cleanup_error or exc
            if cleanup_error is not None:
                raise cleanup_error
    raise KnowledgeWriteConflict("atomic append could not stabilize the anchored target identity")


__all__ = [
    "AtomicAppendIdentityCollision",
    "AtomicAppendReconcileResult",
    "AtomicAppendRecoveryError",
    "AtomicAppendRecord",
    "ReconcileCallback",
    "atomic_append_reconcile_relative",
]
