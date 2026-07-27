from __future__ import annotations

import ctypes
import ctypes.util
import errno
import hashlib
import logging
import os
import stat
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Callable, NamedTuple, Sequence

from app.knowledge.contracts import NoteLocator, SearchHit, WriteReceipt
from app.knowledge.errors import KnowledgeCapabilityError, KnowledgeDependencyError, KnowledgeTransportError, KnowledgeWriteConflict
from app.knowledge.locators import make_note_locator
from app.knowledge.obsidian_cli_scope import scoped_cli_args
from app.knowledge.multiwriter import (
    NoteClass,
    WriteOperation,
    classify_note,
    conflict_artifact_path,
)

logger = logging.getLogger(__name__)


_DIRECTORY_OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


def _atomic_exchange_at(
    first_dir_fd: int,
    first_name: str,
    second_dir_fd: int,
    second_name: str,
) -> None:
    """Atomically swap two same-filesystem paths or fail closed.

    Python does not expose the exchange variants of rename. Linux and macOS do,
    and both are used by the supported runtime/CI environments. An unsupported
    platform must reject optimistic rewritten-note writes rather than degrade to
    a non-atomic check-then-write sequence.
    """
    libc = ctypes.CDLL(ctypes.util.find_library("c") or None, use_errno=True)
    first_raw = os.fsencode(first_name)
    second_raw = os.fsencode(second_name)
    if sys.platform == "darwin":
        rename_exchange = getattr(libc, "renameatx_np", None)
        if rename_exchange is None:
            raise KnowledgeCapabilityError("atomic path exchange is unavailable")
        rename_exchange.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename_exchange.restype = ctypes.c_int
        result = rename_exchange(
            first_dir_fd,
            first_raw,
            second_dir_fd,
            second_raw,
            0x00000002,
        )  # RENAME_SWAP
    elif sys.platform.startswith("linux"):
        rename_exchange = getattr(libc, "renameat2", None)
        if rename_exchange is None:
            raise KnowledgeCapabilityError("atomic path exchange is unavailable")
        rename_exchange.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename_exchange.restype = ctypes.c_int
        result = rename_exchange(
            first_dir_fd,
            first_raw,
            second_dir_fd,
            second_raw,
            0x00000002,
        )
    else:
        raise KnowledgeCapabilityError("atomic path exchange is unavailable")
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), first_name)


def _atomic_rename_noreplace_at(
    source_dir_fd: int,
    source_name: str,
    destination_dir_fd: int,
    destination_name: str,
) -> None:
    """Atomically rename without replacing an existing destination."""

    libc = ctypes.CDLL(ctypes.util.find_library("c") or None, use_errno=True)
    source_raw = os.fsencode(source_name)
    destination_raw = os.fsencode(destination_name)
    if sys.platform == "darwin":
        rename_noreplace = getattr(libc, "renameatx_np", None)
        if rename_noreplace is None:
            raise KnowledgeCapabilityError("atomic no-replace rename is unavailable")
        rename_noreplace.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename_noreplace.restype = ctypes.c_int
        result = rename_noreplace(
            source_dir_fd,
            source_raw,
            destination_dir_fd,
            destination_raw,
            0x00000004,
        )  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        rename_noreplace = getattr(libc, "renameat2", None)
        if rename_noreplace is None:
            raise KnowledgeCapabilityError("atomic no-replace rename is unavailable")
        rename_noreplace.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename_noreplace.restype = ctypes.c_int
        result = rename_noreplace(
            source_dir_fd,
            source_raw,
            destination_dir_fd,
            destination_raw,
            0x00000001,
        )  # RENAME_NOREPLACE
    else:
        raise KnowledgeCapabilityError("atomic no-replace rename is unavailable")
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), source_name)


def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        stat.S_IFMT(left.st_mode),
    ) == (
        right.st_dev,
        right.st_ino,
        stat.S_IFMT(right.st_mode),
    )


def _entry_has_identity(
    dir_fd: int, name: str, expected: os.stat_result
) -> bool:
    try:
        current = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return _same_file_identity(current, expected)


def _open_directory_from_root(
    root_fd: int,
    relative_path: PurePosixPath,
) -> int:
    """Open a vault-relative directory without following any path component."""

    current_fd = os.dup(root_fd)
    try:
        for part in relative_path.parts:
            if part in {"", "."}:
                continue
            if part == "..":
                raise KnowledgeCapabilityError("note path escapes vault root")
            next_fd = os.open(
                part,
                _DIRECTORY_OPEN_FLAGS,
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def _open_anchored_parent(
    root_path: Path,
    relative_parent: PurePosixPath,
) -> tuple[int, int]:
    root_fd = os.open(root_path, _DIRECTORY_OPEN_FLAGS)
    try:
        parent_fd = _open_directory_from_root(root_fd, relative_parent)
    except Exception:
        os.close(root_fd)
        raise
    return root_fd, parent_fd


def _open_conflict_directory(parent_fd: int) -> int:
    try:
        os.mkdir("_conflicts", mode=0o700, dir_fd=parent_fd)
        os.fsync(parent_fd)
    except FileExistsError:
        pass
    try:
        return os.open("_conflicts", _DIRECTORY_OPEN_FLAGS, dir_fd=parent_fd)
    except OSError as exc:
        raise KnowledgeCapabilityError(
            "conflict directory must be an anchored non-symlink directory"
        ) from exc


def _conflict_artifact_name(locator: NoteLocator) -> str:
    artifact_rel = conflict_artifact_path(
        locator.path,
        writer_identity=f"concurrent-save-{uuid.uuid4().hex}",
        written_at=datetime.now(UTC),
    )
    # ``.md.conflict`` is intentionally not a markdown-indexable extension. The
    # displaced inode remains durable and human-recoverable without becoming a
    # second authority-like note in search, projection, or retrieval scans.
    return f"{artifact_rel.name}.conflict"


class _RetainedEntry(NamedTuple):
    name: str
    guard_name: str | None = None


def _link_identity_recovery(
    source_dir_fd: int,
    source_name: str,
    expected: os.stat_result,
    conflict_dir_fd: int,
    locator: NoteLocator,
) -> str:
    for _attempt in range(9):
        guard_name = _conflict_artifact_name(locator)
        try:
            os.link(
                source_name,
                guard_name,
                src_dir_fd=source_dir_fd,
                dst_dir_fd=conflict_dir_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            continue
        break
    else:
        raise KnowledgeCapabilityError(
            f"could not allocate recovery guard for rewritten note {locator.path}"
        )
    guard_stat = os.stat(
        guard_name,
        dir_fd=conflict_dir_fd,
        follow_symlinks=False,
    )
    os.fsync(conflict_dir_fd)
    if not _same_file_identity(guard_stat, expected):
        raise KnowledgeWriteConflict(
            f"version mismatch for rewritten note {locator.path}: "
            "displaced recovery guard changed during publication"
        )
    return guard_name


def _snapshot_payload_recovery(
    payload: bytes,
    mode: int,
    conflict_dir_fd: int,
    locator: NoteLocator,
) -> str:
    """Durably retain known bytes in an independent scanner-inert file."""

    recovery_fd = -1
    recovery_name = ""
    for _attempt in range(9):
        recovery_name = _conflict_artifact_name(locator)
        try:
            recovery_fd = os.open(
                recovery_name,
                os.O_RDWR
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0),
                mode,
                dir_fd=conflict_dir_fd,
            )
        except FileExistsError:
            continue
        break
    else:
        raise KnowledgeCapabilityError(
            f"could not allocate descriptor recovery for rewritten note {locator.path}"
        )

    try:
        offset = 0
        while offset < len(payload):
            written = os.write(recovery_fd, payload[offset:])
            if written <= 0:
                raise OSError("descriptor recovery write made no progress")
            offset += written
        os.fchmod(recovery_fd, mode)
        os.fsync(recovery_fd)
        recovery_stat = os.fstat(recovery_fd)
        recovery_payload = bytearray()
        while len(recovery_payload) < len(payload):
            chunk = os.pread(
                recovery_fd,
                len(payload) - len(recovery_payload),
                len(recovery_payload),
            )
            if not chunk:
                break
            recovery_payload.extend(chunk)
        os.fsync(conflict_dir_fd)
        if (
            bytes(recovery_payload) != payload
            or stat.S_IMODE(recovery_stat.st_mode) != mode
            or not _entry_has_identity(
                conflict_dir_fd,
                recovery_name,
                recovery_stat,
            )
        ):
            raise KnowledgeWriteConflict(
                f"version mismatch for rewritten note {locator.path}: "
                "descriptor recovery changed during publication"
            )
    finally:
        os.close(recovery_fd)
    return recovery_name


def _snapshot_descriptor_recovery(
    source_fd: int,
    expected: os.stat_result,
    conflict_dir_fd: int,
    locator: NoteLocator,
) -> str:
    """Durably snapshot an exact open file when no pathname can be trusted."""

    payload, source_stat = _read_stable_descriptor(source_fd)
    if not _same_file_identity(source_stat, expected):
        raise KnowledgeWriteConflict(
            f"version mismatch for rewritten note {locator.path}: "
            "recovery descriptor identity changed"
        )
    return _snapshot_payload_recovery(
        payload,
        stat.S_IMODE(source_stat.st_mode),
        conflict_dir_fd,
        locator,
    )


def _atomically_retain_controlled_entry(
    source_dir_fd: int,
    source_name: str,
    expected: os.stat_result,
    conflict_dir_fd: int,
    locator: NoteLocator,
    *,
    retain_guard: bool = False,
) -> _RetainedEntry | None:
    """Retire a controlled hidden name without unlinking a raced replacement.

    The current source entry is atomically moved to a unique, non-indexed
    retention name and only then compared with the controlled inode. If a
    replacement won the source name, the exact moved replacement is atomically
    restored without clobbering any later entrant. A failed restore leaves the
    replacement retained and fails closed; no observed entry is deleted.
    """

    guard_name: str | None = None
    if retain_guard:
        try:
            guard_name = _link_identity_recovery(
                source_dir_fd,
                source_name,
                expected,
                conflict_dir_fd,
                locator,
            )
        except FileNotFoundError:
            return None

    retained_name: str | None = None
    for _attempt in range(9):
        candidate_name = _conflict_artifact_name(locator)
        try:
            _atomic_rename_noreplace_at(
                source_dir_fd,
                source_name,
                conflict_dir_fd,
                candidate_name,
            )
        except FileNotFoundError:
            if guard_name is not None:
                second_guard = _link_identity_recovery(
                    conflict_dir_fd,
                    guard_name,
                    expected,
                    conflict_dir_fd,
                    locator,
                )
                return _RetainedEntry(guard_name, second_guard)
            return None
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                continue
            raise
        retained_name = candidate_name
        break
    else:
        raise KnowledgeCapabilityError(
            f"could not allocate cleanup retention for rewritten note {locator.path}"
        )

    moved = os.stat(
        retained_name,
        dir_fd=conflict_dir_fd,
        follow_symlinks=False,
    )
    os.fsync(source_dir_fd)
    os.fsync(conflict_dir_fd)
    if _same_file_identity(moved, expected):
        return _RetainedEntry(retained_name, guard_name)

    try:
        _atomic_rename_noreplace_at(
            conflict_dir_fd,
            retained_name,
            source_dir_fd,
            source_name,
        )
    except OSError as exc:
        os.fsync(source_dir_fd)
        os.fsync(conflict_dir_fd)
        raise KnowledgeWriteConflict(
            f"version mismatch for rewritten note {locator.path}: "
            f"cleanup replacement was retained as _conflicts/{retained_name}"
        ) from exc
    os.fsync(conflict_dir_fd)
    os.fsync(source_dir_fd)
    restored = os.stat(
        source_name,
        dir_fd=source_dir_fd,
        follow_symlinks=False,
    )
    if not _same_file_identity(restored, moved):
        raise KnowledgeWriteConflict(
            f"version mismatch for rewritten note {locator.path}: "
            "cleanup replacement changed during restoration"
        )
    if guard_name is not None:
        second_guard = _link_identity_recovery(
            conflict_dir_fd,
            guard_name,
            expected,
            conflict_dir_fd,
            locator,
        )
        return _RetainedEntry(guard_name, second_guard)
    return None


def _stage_initial_stale_proposal(
    parent_fd: int,
    conflict_fd: int,
    staged_name: str,
    locator: NoteLocator,
    *,
    payload: bytes,
    payload_version: str,
    staged_stat: os.stat_result,
    writer_identity: str,
    written_at: datetime,
) -> tuple[PurePosixPath, os.stat_result]:
    """Publish a durable, no-clobber sibling artifact for an initially stale write."""

    candidate_name = f".{PurePosixPath(locator.path).name}.{uuid.uuid4().hex}.conflict-stage"
    candidate_fd = -1
    candidate_guard_fd = -1
    candidate_stat: os.stat_result | None = None
    artifact_rel: PurePosixPath | None = None
    candidate_payload_durable = False
    artifact_published = False
    artifact_verified_for_receipt = False
    try:
        candidate_fd = os.open(
            candidate_name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_fd,
        )
        # Capture ownership before any fallible payload I/O. Cleanup can then
        # retain a partial controlled entry without touching a raced replacement.
        candidate_stat = os.fstat(candidate_fd)
        # Keep the inode allocated until identity-guarded cleanup completes.
        # Linux can otherwise recycle the inode number immediately after a
        # concurrent unlink, making a replacement look like the controlled entry.
        candidate_guard_fd = os.dup(candidate_fd)
        candidate_handle = os.fdopen(candidate_fd, "wb")
        candidate_fd = -1
        with candidate_handle:
            candidate_handle.write(payload)
            candidate_handle.flush()
            os.fsync(candidate_handle.fileno())
        candidate_payload_durable = True

        for attempt in range(9):
            artifact_writer = (
                writer_identity if attempt == 0 else f"{writer_identity}-{uuid.uuid4().hex}"
            )
            artifact_rel = conflict_artifact_path(
                locator.path,
                writer_identity=artifact_writer,
                written_at=written_at,
            )
            try:
                os.link(
                    candidate_name,
                    artifact_rel.name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileExistsError:
                continue
            artifact_published = True
            break
        else:
            raise KnowledgeCapabilityError(
                f"could not allocate conflict artifact for rewritten note {locator.path}"
            )

        assert candidate_stat is not None
        assert artifact_rel is not None
        if (
            not _entry_has_identity(parent_fd, artifact_rel.name, candidate_stat)
            or hashlib.sha256(_read_entry(parent_fd, artifact_rel.name)).hexdigest()
            != payload_version
        ):
            raise KnowledgeWriteConflict(
                f"version mismatch for rewritten note {locator.path}: "
                "staged conflict artifact verification failed"
            )

        # Persist the human-visible name before retaining the original rewrite
        # staging entry. Keep the trusted candidate link until the final public
        # artifact verification: if another directory writer replaces the
        # public name in that window, the exact proposal must remain recoverable
        # even though no receipt can be returned.
        os.fsync(parent_fd)
        _atomically_retain_controlled_entry(
            parent_fd,
            staged_name,
            staged_stat,
            conflict_fd,
            locator,
        )

        if (
            not _entry_has_identity(parent_fd, artifact_rel.name, candidate_stat)
            or hashlib.sha256(_read_entry(parent_fd, artifact_rel.name)).hexdigest()
            != payload_version
        ):
            raise KnowledgeWriteConflict(
                f"version mismatch for rewritten note {locator.path}: "
                "staged conflict artifact changed before receipt"
            )
        artifact_verified_for_receipt = True
        _atomically_retain_controlled_entry(
            parent_fd,
            candidate_name,
            candidate_stat,
            conflict_fd,
            locator,
        )
        return artifact_rel, candidate_stat
    finally:
        try:
            if candidate_stat is not None and (
                not candidate_payload_durable
                or (
                    not artifact_published
                    and _entry_has_identity(parent_fd, staged_name, staged_stat)
                )
                or (
                    artifact_verified_for_receipt
                    and artifact_rel is not None
                    and _entry_has_identity(
                        parent_fd,
                        artifact_rel.name,
                        candidate_stat,
                    )
                )
            ):
                _atomically_retain_controlled_entry(
                    parent_fd,
                    candidate_name,
                    candidate_stat,
                    conflict_fd,
                    locator,
                )
        finally:
            if candidate_fd >= 0:
                os.close(candidate_fd)
            if candidate_guard_fd >= 0:
                os.close(candidate_guard_fd)


def _read_entry(dir_fd: int, name: str) -> bytes:
    fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=dir_fd)
    with os.fdopen(fd, "rb") as handle:
        return handle.read()


def _read_stable_descriptor(fd: int) -> tuple[bytes, os.stat_result]:
    """Read one exact open inode without consulting a mutable directory name."""

    for _attempt in range(3):
        before = os.fstat(fd)
        offset = 0
        chunks: list[bytes] = []
        while offset < before.st_size:
            chunk = os.pread(fd, min(1024 * 1024, before.st_size - offset), offset)
            if not chunk:
                break
            chunks.append(chunk)
            offset += len(chunk)
        after = os.fstat(fd)
        if (
            _same_file_identity(before, after)
            and offset == before.st_size
            and (
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
                stat.S_IMODE(before.st_mode),
            )
            == (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
                stat.S_IMODE(after.st_mode),
            )
        ):
            return b"".join(chunks), after
    raise KnowledgeWriteConflict(
        "displaced rewritten-note inode changed during descriptor-bound snapshot"
    )


def _read_handle(handle) -> bytes:  # type: ignore[no-untyped-def]
    return handle.read()


def _require_anchored_directory_identity(
    root_fd: int,
    root_path: Path,
    relative_parent: PurePosixPath,
    parent_fd: int,
    conflict_fd: int,
    locator: NoteLocator,
) -> None:
    current_parent_fd = -1
    try:
        current_root = os.stat(root_path, follow_symlinks=False)
        anchored_root = os.fstat(root_fd)
        current_parent_fd = _open_directory_from_root(root_fd, relative_parent)
        current_parent = os.fstat(current_parent_fd)
        anchored_parent = os.fstat(parent_fd)
        current_conflict = os.stat(
            "_conflicts", dir_fd=parent_fd, follow_symlinks=False
        )
        anchored_conflict = os.fstat(conflict_fd)
        if (
            not stat.S_ISDIR(current_root.st_mode)
            or not _same_file_identity(current_root, anchored_root)
            or not stat.S_ISDIR(current_parent.st_mode)
            or not _same_file_identity(current_parent, anchored_parent)
            or not stat.S_ISDIR(current_conflict.st_mode)
            or not _same_file_identity(current_conflict, anchored_conflict)
        ):
            raise KnowledgeWriteConflict(
                f"version mismatch for rewritten note {locator.path}: "
                "anchored write directory changed"
            )
    except OSError as exc:
        raise KnowledgeWriteConflict(
            f"version mismatch for rewritten note {locator.path}: "
            "anchored write directory changed"
        ) from exc
    finally:
        if current_parent_fd >= 0:
            os.close(current_parent_fd)


class FsVaultAdapter:
    def __init__(
        self,
        vault_root: Path | str,
        *,
        capture_note_rel: str | None = None,
        sources_root_rel: str = "Sources",
    ) -> None:
        self.vault_root = Path(vault_root).expanduser()
        self.capture_note_rel = capture_note_rel
        self.sources_root_rel = sources_root_rel

    def _absolute_path(self, locator: NoteLocator) -> Path:
        target = (self.vault_root / locator.path).resolve()
        root = self.vault_root.resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise KnowledgeCapabilityError("note path escapes vault root") from exc
        return target

    def read_note(self, locator: NoteLocator) -> str:
        return self._absolute_path(locator).read_text(encoding="utf-8")

    def write_note(
        self,
        locator: NoteLocator,
        content: str,
        *,
        expected_version: str | None = None,
        writer_identity: str | None = None,
    ) -> WriteReceipt:
        root = self.vault_root.resolve()
        lexical_target = root / locator.path
        try:
            lexical_target.relative_to(root)
        except ValueError as exc:
            raise KnowledgeCapabilityError("note path escapes vault root") from exc
        target = self._absolute_path(locator)
        if expected_version is not None and target != lexical_target:
            raise KnowledgeWriteConflict(
                f"expected-version write rejects aliased note locator {locator.path}"
            )
        note_class = self._classify_target(target, WriteOperation.WRITE)
        effective_writer_identity = writer_identity or "mimer.runtime"
        written_at = datetime.now(UTC)
        if expected_version is not None and note_class is not NoteClass.REWRITTEN:
            raise KnowledgeWriteConflict(
                "expected-version write requires a rewritten note class; "
                f"{locator.path} is {note_class.value}"
            )
        # Opt-in optimistic concurrency (VMW-01 enactment-gap model; owner decision
        # 2026-07-13). Enforcement applies ONLY when the caller opts in by passing
        # ``expected_version``: a versionless write is performed normally so legacy
        # writers are never broken during progressive migration (#3570) -- the
        # structured outcome is still recorded on the receipt's ``note_class``. When a
        # caller DOES pass ``expected_version``, a non-REWRITTEN class fails closed
        # before mutation; a REWRITTEN note whose current bytes no longer match
        # preserves the caller's proposed bytes as a provenance-bearing sibling
        # conflict artifact and returns a legible staged-conflict outcome.
        # Races after this initial comparison retain the hardened atomic exchange,
        # rollback, displaced-inode, and fail-closed behavior.
        if expected_version is not None and note_class is NoteClass.REWRITTEN:
            root_fd = -1
            parent_fd = -1
            conflict_fd = -1
            staged_fd = -1
            staged_guard_fd = -1
            target_guard_fd = -1
            staged_dir_fd = -1
            staged_name = f".{target.name}.{uuid.uuid4().hex}.rewrite-swap"
            preserve_staged_conflict = False
            staged_is_artifact = False
            staged_stat: os.stat_result | None = None
            staged_cleanup_stat: os.stat_result | None = None
            primary_exchange_completed = False
            retained_names: tuple[str, ...] = ()
            try:
                relative_parent = PurePosixPath(locator.path).parent
                root_fd, parent_fd = _open_anchored_parent(
                    root,
                    relative_parent,
                )
                conflict_fd = _open_conflict_directory(parent_fd)
                staged_dir_fd = parent_fd
                staged_fd = os.open(
                    staged_name,
                    os.O_RDWR | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=parent_fd,
                )
                # Capture ownership before any fallible payload I/O so every
                # pre-receipt failure can retain this controlled name safely.
                staged_stat = os.fstat(staged_fd)
                staged_cleanup_stat = staged_stat
                # Retain a descriptor through cleanup/linearization so an
                # unlinked staging inode cannot be recycled under a replacement
                # path entry on Linux.
                staged_guard_fd = os.dup(staged_fd)
                payload = content.encode("utf-8")
                staged_handle = os.fdopen(staged_fd, "wb")
                staged_fd = -1
                with staged_handle:
                    staged_handle.write(payload)
                    staged_handle.flush()
                    os.fsync(staged_handle.fileno())
                if staged_stat is None:
                    raise KnowledgeCapabilityError(
                        f"could not stat staged rewrite for note {locator.path}"
                    )
                payload_version = hashlib.sha256(payload).hexdigest()

                # Validate twice through one descriptor, then use an atomic path exchange
                # as the linearization point. The displaced original remains addressable at
                # ``staged`` so a same-inode save in the final check/exchange gap can be
                # detected and atomically rolled back instead of being silently overwritten.
                target_fd = os.open(
                    target.name,
                    os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=parent_fd,
                )
                with os.fdopen(target_fd, "r+b") as handle:
                    opened_stat = os.fstat(handle.fileno())
                    # Keep the checked target inode allocated through exchange
                    # verification. This makes dev+inode identity stable even
                    # when a racing writer unlinks the target on Linux.
                    target_guard_fd = os.dup(handle.fileno())
                    current_bytes = _read_handle(handle)
                    current_version = hashlib.sha256(current_bytes).hexdigest()
                    if current_version != expected_version:
                        preserve_staged_conflict = True
                        _require_anchored_directory_identity(
                            root_fd,
                            root,
                            relative_parent,
                            parent_fd,
                            conflict_fd,
                            locator,
                        )
                        artifact_rel, artifact_stat = _stage_initial_stale_proposal(
                            parent_fd,
                            conflict_fd,
                            staged_name,
                            locator,
                            payload=payload,
                            payload_version=payload_version,
                            staged_stat=staged_stat,
                            writer_identity=effective_writer_identity,
                            written_at=written_at,
                        )
                        staged_name = artifact_rel.name
                        staged_dir_fd = parent_fd
                        staged_is_artifact = True
                        _require_anchored_directory_identity(
                            root_fd,
                            root,
                            relative_parent,
                            parent_fd,
                            conflict_fd,
                            locator,
                        )
                        try:
                            artifact_current = os.stat(
                                artifact_rel.name,
                                dir_fd=parent_fd,
                                follow_symlinks=False,
                            )
                            artifact_current_version = hashlib.sha256(
                                _read_entry(parent_fd, artifact_rel.name)
                            ).hexdigest()
                        except OSError as exc:
                            raise KnowledgeWriteConflict(
                                f"version mismatch for rewritten note {locator.path}: "
                                "staged conflict artifact changed before receipt"
                            ) from exc
                        if (
                            not _same_file_identity(artifact_current, artifact_stat)
                            or artifact_current_version != payload_version
                            or not _entry_has_identity(
                                parent_fd,
                                artifact_rel.name,
                                artifact_stat,
                            )
                        ):
                            raise KnowledgeWriteConflict(
                                f"version mismatch for rewritten note {locator.path}: "
                                "staged conflict artifact changed before receipt"
                            )
                        return WriteReceipt(
                            operation="write_note",
                            locator=locator,
                            adapter="fs_vault",
                            note_class=note_class,
                            writer_identity=effective_writer_identity,
                            written_at=written_at.isoformat(),
                            outcome="conflict_staged",
                            conflict_artifact=artifact_rel.as_posix(),
                        )

                    path_stat = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
                    if not _same_file_identity(path_stat, opened_stat):
                        raise KnowledgeWriteConflict(
                            f"version mismatch for rewritten note {locator.path}: "
                            "target was replaced"
                        )

                    # Re-read through the still-open descriptor immediately before the
                    # mutation. Path identity alone cannot detect an editor that saved
                    # through another descriptor to the same inode after our first read.
                    handle.seek(0)
                    latest_bytes = _read_handle(handle)
                    if hashlib.sha256(latest_bytes).hexdigest() != expected_version:
                        raise KnowledgeWriteConflict(
                            f"version mismatch for rewritten note {locator.path}: "
                            "target changed during version check"
                        )
                    os.chmod(
                        staged_name,
                        stat.S_IMODE(opened_stat.st_mode),
                        dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                    staged_sync_fd = os.open(
                        staged_name,
                        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                        dir_fd=parent_fd,
                    )
                    try:
                        os.fsync(staged_sync_fd)
                    finally:
                        os.close(staged_sync_fd)
                    opened_mode = stat.S_IMODE(opened_stat.st_mode)

                # The staging descriptor proves inode identity, not immutable
                # payload: another same-user writer can modify that inode in
                # place. Retain the caller's known intended bytes independently
                # before any other fallible recovery or precondition.
                _snapshot_payload_recovery(
                    payload,
                    opened_mode,
                    conflict_fd,
                    locator,
                )
                # Establish an independent, file-fsynced authority for the exact
                # checked original before the primary exchange. A path writer can
                # replace the hidden displaced name before the first hard-link
                # guard is published; the open target descriptor is the only
                # portable source of truth across that gap.
                _snapshot_descriptor_recovery(
                    target_guard_fd,
                    opened_stat,
                    conflict_fd,
                    locator,
                )
                _require_anchored_directory_identity(
                    root_fd,
                    root,
                    relative_parent,
                    parent_fd,
                    conflict_fd,
                    locator,
                )
                try:
                    _atomic_exchange_at(parent_fd, target.name, parent_fd, staged_name)
                except OSError as exc:
                    raise KnowledgeWriteConflict(
                        f"version mismatch for rewritten note {locator.path}: "
                        "atomic exchange failed"
                    ) from exc
                primary_exchange_completed = True

                # From the instant the exchange succeeds, the displaced entry must
                # survive every verification failure, including failure to stat
                # either exchanged name.
                preserve_staged_conflict = True
                staged_cleanup_stat = opened_stat

                # Bind the exchange to the exact target inode opened and checked
                # above. A leaf replacement can occur inside the final
                # check/exchange gap (for example, a same-content symlink to a
                # different note). POSIX has no inode-conditional exchange, so a
                # second "restore" exchange would have the same race and could
                # displace yet another canonical writer. Preserve all observed
                # versions and fail receiptlessly instead; canonical outcome is
                # deliberately indeterminate on this conflict path.
                post_exchange_target = os.stat(
                    target.name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
                post_exchange_displaced = os.stat(
                    staged_name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
                if not _same_file_identity(post_exchange_target, staged_stat):
                    preserve_staged_conflict = True
                    staged_cleanup_stat = post_exchange_displaced
                    _snapshot_descriptor_recovery(
                        staged_guard_fd,
                        staged_stat,
                        conflict_fd,
                        locator,
                    )
                    raise KnowledgeWriteConflict(
                        f"version mismatch for rewritten note {locator.path}: "
                        "target changed after atomic exchange"
                    )
                if not _same_file_identity(post_exchange_displaced, opened_stat):
                    preserve_staged_conflict = True
                    staged_cleanup_stat = post_exchange_displaced
                    _snapshot_descriptor_recovery(
                        staged_guard_fd,
                        staged_stat,
                        conflict_fd,
                        locator,
                    )
                    raise KnowledgeWriteConflict(
                        f"version mismatch for rewritten note {locator.path}: "
                        "target changed at atomic exchange"
                    )

                # The displaced inode must keep a durable path for the lifetime of any
                # already-open external descriptor. There is no portable way to know when
                # such descriptors close, so every successful optimistic exchange retains
                # this pre-exchange version as a standard conflicted copy.
                os.fsync(parent_fd)
                _require_anchored_directory_identity(
                    root_fd,
                    root,
                    relative_parent,
                    parent_fd,
                    conflict_fd,
                    locator,
                )
                retained_entry = _atomically_retain_controlled_entry(
                    parent_fd,
                    staged_name,
                    opened_stat,
                    conflict_fd,
                    locator,
                    retain_guard=True,
                )
                if retained_entry is None:
                    preserve_staged_conflict = True
                    raise KnowledgeWriteConflict(
                        f"version mismatch for rewritten note {locator.path}: "
                        "displaced entry was replaced before retention"
                    )
                retained_names = tuple(
                    name
                    for name in (retained_entry.name, retained_entry.guard_name)
                    if name is not None
                )
                try:
                    staged_name = next(
                        name
                        for name in retained_names
                        if _entry_has_identity(conflict_fd, name, opened_stat)
                    )
                except StopIteration:
                    preserve_staged_conflict = True
                    raise KnowledgeWriteConflict(
                        f"version mismatch for rewritten note {locator.path}: "
                        "displaced recovery identity changed before verification"
                    )
                displaced_bytes, displaced_stat = _read_stable_descriptor(
                    target_guard_fd
                )
                if not _same_file_identity(displaced_stat, opened_stat):
                    raise KnowledgeWriteConflict(
                        f"version mismatch for rewritten note {locator.path}: "
                        "displaced descriptor identity changed before verification"
                    )
                try:
                    staged_name = next(
                        name
                        for name in retained_names
                        if _entry_has_identity(conflict_fd, name, opened_stat)
                    )
                except StopIteration:
                    preserve_staged_conflict = True
                    raise KnowledgeWriteConflict(
                        f"version mismatch for rewritten note {locator.path}: "
                        "displaced recovery changed during descriptor snapshot"
                    )
                staged_dir_fd = conflict_fd
                staged_is_artifact = True

                displaced_version = hashlib.sha256(displaced_bytes).hexdigest()
                displaced_mode = stat.S_IMODE(displaced_stat.st_mode)
                if displaced_version != expected_version or displaced_mode != opened_mode:
                    preserve_staged_conflict = True
                    path_stat = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
                    if _same_file_identity(path_stat, staged_stat):
                        rollback_fd = -1
                        try:
                            for _attempt in range(9):
                                rollback_name = _conflict_artifact_name(locator)
                                try:
                                    rollback_fd = os.open(
                                        rollback_name,
                                        os.O_RDWR
                                        | os.O_CREAT
                                        | os.O_EXCL
                                        | getattr(os, "O_NOFOLLOW", 0),
                                        opened_mode,
                                        dir_fd=conflict_fd,
                                    )
                                except FileExistsError:
                                    continue
                                break
                            else:
                                raise KnowledgeCapabilityError(
                                    "could not allocate rollback snapshot for "
                                    f"rewritten note {locator.path}"
                            )
                            offset = 0
                            while offset < len(displaced_bytes):
                                written = os.write(
                                    rollback_fd,
                                    displaced_bytes[offset:],
                                )
                                if written <= 0:
                                    raise OSError(
                                        "rollback snapshot write made no progress"
                                    )
                                offset += written
                            os.fchmod(rollback_fd, displaced_mode)
                            os.fsync(rollback_fd)
                            rollback_stat = os.fstat(rollback_fd)
                            # A path writer can replace the proposal immediately
                            # before rollback exchange. Keep an independent
                            # descriptor-bound recovery snapshot before that
                            # pathname can be severed.
                            _snapshot_descriptor_recovery(
                                staged_guard_fd,
                                staged_stat,
                                conflict_fd,
                                locator,
                            )
                            _atomic_exchange_at(
                                parent_fd,
                                target.name,
                                conflict_fd,
                                rollback_name,
                            )
                            staged_cleanup_stat = staged_stat
                            staged_name = rollback_name
                            staged_dir_fd = conflict_fd
                            staged_is_artifact = True
                            os.fsync(parent_fd)
                            os.fsync(conflict_fd)
                            rollback_displaced = os.stat(
                                rollback_name,
                                dir_fd=conflict_fd,
                                follow_symlinks=False,
                            )
                            rollback_displaced_authorized = _same_file_identity(
                                rollback_displaced,
                                staged_stat,
                            )
                            if rollback_displaced_authorized:
                                try:
                                    (
                                        rollback_displaced_bytes,
                                        rollback_displaced_descriptor_stat,
                                    ) = _read_stable_descriptor(staged_guard_fd)
                                    rollback_displaced_authorized = (
                                        _same_file_identity(
                                            rollback_displaced_descriptor_stat,
                                            staged_stat,
                                        )
                                        and hashlib.sha256(
                                            rollback_displaced_bytes
                                        ).hexdigest()
                                        == payload_version
                                        and stat.S_IMODE(
                                            rollback_displaced_descriptor_stat.st_mode
                                        )
                                        == opened_mode
                                        and _entry_has_identity(
                                            conflict_fd,
                                            rollback_name,
                                            staged_stat,
                                        )
                                    )
                                except (OSError, KnowledgeWriteConflict):
                                    rollback_displaced_authorized = False
                            if not rollback_displaced_authorized:
                                raise KnowledgeWriteConflict(
                                    f"version mismatch for rewritten note {locator.path}: "
                                    "target changed during atomic snapshot rollback; "
                                    "canonical outcome is indeterminate"
                                )
                            restored_target = os.stat(
                                target.name,
                                dir_fd=parent_fd,
                                follow_symlinks=False,
                            )
                            if (
                                not _same_file_identity(
                                    restored_target,
                                    rollback_stat,
                                )
                                or hashlib.sha256(
                                    _read_entry(parent_fd, target.name)
                                ).hexdigest()
                                != displaced_version
                                or stat.S_IMODE(restored_target.st_mode)
                                != displaced_mode
                            ):
                                raise KnowledgeWriteConflict(
                                    f"version mismatch for rewritten note {locator.path}: "
                                    "atomic snapshot rollback verification failed; "
                                    "displaced content was preserved"
                                )
                        except OSError as exc:
                            raise KnowledgeWriteConflict(
                                f"version mismatch for rewritten note {locator.path}: "
                                "atomic rollback failed; displaced content was preserved"
                            ) from exc
                        finally:
                            if rollback_fd >= 0:
                                os.close(rollback_fd)
                    raise KnowledgeWriteConflict(
                        f"version mismatch for rewritten note {locator.path}: "
                        "target changed at atomic exchange"
                    )

                path_stat = os.stat(target.name, dir_fd=parent_fd, follow_symlinks=False)
                if not _same_file_identity(path_stat, staged_stat):
                    preserve_staged_conflict = True
                    raise KnowledgeWriteConflict(
                        f"version mismatch for rewritten note {locator.path}: "
                        "target changed after atomic exchange"
                    )
                if (
                    hashlib.sha256(_read_entry(parent_fd, target.name)).hexdigest()
                    != payload_version
                ):
                    raise KnowledgeWriteConflict(
                        f"version mismatch for rewritten note {locator.path}: "
                        "target content changed after atomic exchange"
                    )
                _require_anchored_directory_identity(
                    root_fd,
                    root,
                    relative_parent,
                    parent_fd,
                    conflict_fd,
                    locator,
                )
                if not any(
                    _entry_has_identity(conflict_fd, name, opened_stat)
                    for name in retained_names
                ):
                    raise KnowledgeWriteConflict(
                        f"version mismatch for rewritten note {locator.path}: "
                        "displaced recovery changed before receipt"
                    )
            except (FileNotFoundError, NotADirectoryError) as exc:
                raise KnowledgeWriteConflict(
                    f"version mismatch for rewritten note {locator.path}: target is missing"
                ) from exc
            except OSError as exc:
                raise KnowledgeWriteConflict(
                    f"version mismatch for rewritten note {locator.path}: "
                    "filesystem exchange verification failed; displaced content was preserved"
                ) from exc
            finally:
                late_displaced_recovery_error: Exception | None = None
                try:
                    if (
                        primary_exchange_completed
                        and target_guard_fd >= 0
                        and conflict_fd >= 0
                    ):
                        try:
                            guarded_original = os.fstat(target_guard_fd)
                            exact_retention_proven = any(
                                _entry_has_identity(
                                    conflict_fd,
                                    name,
                                    guarded_original,
                                )
                                for name in retained_names
                            )
                            if not exact_retention_proven:
                                _snapshot_descriptor_recovery(
                                    target_guard_fd,
                                    guarded_original,
                                    conflict_fd,
                                    locator,
                                )
                        except (
                            OSError,
                            KnowledgeCapabilityError,
                            KnowledgeWriteConflict,
                        ) as exc:
                            late_displaced_recovery_error = exc
                    try:
                        if preserve_staged_conflict:
                            if not staged_is_artifact:
                                if staged_cleanup_stat is not None:
                                    retained_entry = _atomically_retain_controlled_entry(
                                        staged_dir_fd,
                                        staged_name,
                                        staged_cleanup_stat,
                                        conflict_fd,
                                        locator,
                                    )
                                    if retained_entry is not None:
                                        staged_name = retained_entry.name
                                        staged_dir_fd = conflict_fd
                                        staged_is_artifact = True
                                    else:
                                        logger.warning(
                                            "rewritten-note staged entry changed identity; "
                                            "cleanup restored replacement untouched: %s",
                                            staged_name,
                                        )
                        elif staged_dir_fd >= 0 and staged_cleanup_stat is not None:
                            retained_entry = _atomically_retain_controlled_entry(
                                staged_dir_fd,
                                staged_name,
                                staged_cleanup_stat,
                                conflict_fd,
                                locator,
                            )
                            if retained_entry is not None:
                                staged_name = retained_entry.name
                                staged_dir_fd = conflict_fd
                                staged_is_artifact = True
                    except OSError:
                        logger.exception(
                            "rewritten-note swap cleanup failed; retained staged entry %s",
                            staged_name,
                        )
                finally:
                    if staged_fd >= 0:
                        os.close(staged_fd)
                    if target_guard_fd >= 0:
                        os.close(target_guard_fd)
                    if staged_guard_fd >= 0:
                        os.close(staged_guard_fd)
                    if conflict_fd >= 0:
                        os.close(conflict_fd)
                    if parent_fd >= 0:
                        os.close(parent_fd)
                    if root_fd >= 0:
                        os.close(root_fd)
                if late_displaced_recovery_error is not None:
                    raise KnowledgeWriteConflict(
                        f"version mismatch for rewritten note {locator.path}: "
                        "late displaced-content recovery failed"
                    ) from late_displaced_recovery_error
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return WriteReceipt(
            operation="write_note",
            locator=locator,
            adapter="fs_vault",
            note_class=note_class,
            writer_identity=effective_writer_identity,
            written_at=written_at.isoformat(),
        )

    def append_note(self, locator: NoteLocator, content: str) -> WriteReceipt:
        target = self._absolute_path(locator)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(content)
        return WriteReceipt(
            operation="append_note",
            locator=locator,
            adapter="fs_vault",
            note_class=self._classify_target(target, WriteOperation.APPEND),
            writer_identity="mimer.runtime",
            written_at=datetime.now(UTC).isoformat(),
        )

    def prepend_note(self, locator: NoteLocator, content: str) -> WriteReceipt:
        target = self._absolute_path(locator)
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content + existing, encoding="utf-8")
        return WriteReceipt(
            operation="prepend_note",
            locator=locator,
            adapter="fs_vault",
            note_class=self._classify_target(target, WriteOperation.PREPEND),
        )

    def _classify_target(self, target: Path, operation: WriteOperation) -> NoteClass:
        canonical_relative = target.relative_to(self.vault_root.resolve()).as_posix()
        capture_note_rel = self.capture_note_rel
        if capture_note_rel is None:
            capture_note_rel = (os.getenv("VAULT_CAPTURE_NOTE_REL") or "").strip() or None
        if capture_note_rel is None:
            try:
                from app.vault.paths import get_vault_inbox_dir_rel

                capture_note_rel = f"{get_vault_inbox_dir_rel(self.vault_root).strip('/')}/inbox.md"
            except (OSError, ValueError):
                # Generic filesystem adapters are also used against temporary
                # roots with no selected vault layout.
                capture_note_rel = None
        return classify_note(
            canonical_relative,
            operation,
            capture_note_rel=capture_note_rel,
            sources_root_rel=self.sources_root_rel,
        )

    def search_notes(self, vault: str, query: str, *, limit: int = 20) -> list[SearchHit]:
        from app.vault.manager import iter_vault_markdown_files

        hits: list[SearchHit] = []
        needle = query.lower().strip()
        if not needle:
            return hits
        for note in iter_vault_markdown_files(self.vault_root):
            if any(part.startswith(".obsidian") for part in note.parts):
                continue
            text = note.read_text(encoding="utf-8")
            idx = text.lower().find(needle)
            if idx < 0:
                continue
            rel = note.relative_to(self.vault_root).as_posix()
            excerpt = text[max(0, idx - 60) : idx + 120].replace("\n", " ")
            score = 1.0 / (1.0 + float(idx))
            hits.append(SearchHit(locator=make_note_locator(rel, vault=vault), score=score, excerpt=excerpt))
            if len(hits) >= limit:
                break
        return hits

    def open_note(self, locator: NoteLocator) -> None:
        # No-op: opening notes is a UX concern handled by the Obsidian adapter.
        return None


RunnerFn = Callable[..., subprocess.CompletedProcess[str]]

_TRANSPORT_ERROR_MARKERS = (
    "connection refused",
    "connection reset",
    "connection timed out",
    "econnrefused",
    "econnreset",
    "enotfound",
    "failed to connect",
    "network is unreachable",
    "not running",
    "service unavailable",
    "timed out",
)


def _is_transport_failure(detail: str) -> bool:
    lowered = detail.lower()
    return any(marker in lowered for marker in _TRANSPORT_ERROR_MARKERS)


class ObsidianCliAdapter:
    def __init__(self, *, cli_bin: str = "obsidian", runner: RunnerFn = subprocess.run) -> None:
        self.cli_bin = cli_bin
        self.runner = runner

    def _run(self, *, vault: str, args: Sequence[str], capture_output: bool = True) -> subprocess.CompletedProcess[str]:
        cmd = [self.cli_bin, *scoped_cli_args(vault, args)]
        try:
            return self.runner(cmd, check=True, capture_output=capture_output, text=True)
        except FileNotFoundError as exc:
            raise KnowledgeDependencyError(f"Obsidian CLI not found: {self.cli_bin}") from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            detail = f": {stderr}" if stderr else ""
            message = f"Obsidian CLI command failed{detail}"
            if _is_transport_failure(stderr):
                raise KnowledgeTransportError(message) from exc
            raise KnowledgeCapabilityError(message) from exc

    def read_note(self, locator: NoteLocator) -> str:
        proc = self._run(vault=locator.vault, args=["read", locator.path], capture_output=True)
        return proc.stdout or ""

    def write_note(
        self,
        locator: NoteLocator,
        content: str,
        *,
        expected_version: str | None = None,
        writer_identity: str | None = None,
    ) -> WriteReceipt:
        self._run(vault=locator.vault, args=["create", locator.path, content], capture_output=True)
        return WriteReceipt(
            operation="write_note",
            locator=locator,
            adapter="obsidian_cli",
            note_class=classify_note(locator.path, WriteOperation.WRITE),
            writer_identity=writer_identity or "obsidian-cli",
            written_at=datetime.now(UTC).isoformat(),
        )

    def append_note(self, locator: NoteLocator, content: str) -> WriteReceipt:
        self._run(vault=locator.vault, args=["append", locator.path, content], capture_output=True)
        return WriteReceipt(operation="append_note", locator=locator, adapter="obsidian_cli")

    def prepend_note(self, locator: NoteLocator, content: str) -> WriteReceipt:
        self._run(vault=locator.vault, args=["prepend", locator.path, content], capture_output=True)
        return WriteReceipt(operation="prepend_note", locator=locator, adapter="obsidian_cli")

    def search_notes(self, vault: str, query: str, *, limit: int = 20) -> list[SearchHit]:
        proc = self._run(vault=vault, args=["search", query], capture_output=True)
        text = (proc.stdout or "").strip()
        if not text:
            return []
        hits: list[SearchHit] = []
        for line in text.splitlines()[:limit]:
            rel = line.strip()
            if not rel:
                continue
            hits.append(SearchHit(locator=make_note_locator(rel, vault=vault), score=1.0, excerpt=""))
        return hits

    def open_note(self, locator: NoteLocator) -> None:
        self._run(vault=locator.vault, args=["open", locator.path], capture_output=True)


__all__ = ["FsVaultAdapter", "ObsidianCliAdapter", "RunnerFn"]
