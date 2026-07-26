from __future__ import annotations

import ctypes
import ctypes.util
import hashlib
import logging
import os
import stat
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Callable, Sequence

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


def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _entry_has_identity(
    dir_fd: int, name: str, expected: os.stat_result
) -> bool:
    try:
        current = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return _same_file_identity(current, expected)


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


def _stage_initial_stale_proposal(
    parent_fd: int,
    staged_name: str,
    locator: NoteLocator,
    *,
    payload: bytes,
    payload_version: str,
    staged_stat: os.stat_result,
    writer_identity: str,
    written_at: datetime,
) -> PurePosixPath:
    """Publish a durable, no-clobber sibling artifact for an initially stale write."""

    candidate_name = f".{PurePosixPath(locator.path).name}.{uuid.uuid4().hex}.conflict-stage"
    candidate_fd = -1
    candidate_stat: os.stat_result | None = None
    artifact_rel: PurePosixPath | None = None
    try:
        candidate_fd = os.open(
            candidate_name,
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_fd,
        )
        open_candidate_fd = candidate_fd
        candidate_fd = -1
        with os.fdopen(open_candidate_fd, "wb") as candidate_handle:
            candidate_handle.write(payload)
            candidate_handle.flush()
            os.fsync(candidate_handle.fileno())
            candidate_stat = os.fstat(candidate_handle.fileno())

        for attempt in range(9):
            artifact_writer = (
                writer_identity
                if attempt == 0
                else f"{writer_identity}-{uuid.uuid4().hex}"
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

        # Persist the human-visible name before removing hidden names. Cleanup
        # is identity-guarded so a concurrent directory writer cannot make this
        # operation unlink a replacement that it did not create.
        os.fsync(parent_fd)
        if _entry_has_identity(parent_fd, staged_name, staged_stat):
            os.unlink(staged_name, dir_fd=parent_fd)
        if _entry_has_identity(parent_fd, candidate_name, candidate_stat):
            os.unlink(candidate_name, dir_fd=parent_fd)
        os.fsync(parent_fd)

        if (
            not _entry_has_identity(parent_fd, artifact_rel.name, candidate_stat)
            or hashlib.sha256(_read_entry(parent_fd, artifact_rel.name)).hexdigest()
            != payload_version
        ):
            raise KnowledgeWriteConflict(
                f"version mismatch for rewritten note {locator.path}: "
                "staged conflict artifact changed before receipt"
            )
        return artifact_rel
    finally:
        if candidate_fd >= 0:
            os.close(candidate_fd)
        if (
            candidate_stat is not None
            and _entry_has_identity(parent_fd, candidate_name, candidate_stat)
        ):
            try:
                os.unlink(candidate_name, dir_fd=parent_fd)
                os.fsync(parent_fd)
            except FileNotFoundError:
                pass


def _read_entry(dir_fd: int, name: str) -> bytes:
    fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=dir_fd)
    with os.fdopen(fd, "rb") as handle:
        return handle.read()


def _read_handle(handle) -> bytes:  # type: ignore[no-untyped-def]
    return handle.read()


def _require_anchored_directory_identity(
    parent_fd: int,
    parent_path: Path,
    conflict_fd: int,
    locator: NoteLocator,
) -> None:
    try:
        current_parent = os.stat(parent_path, follow_symlinks=False)
        anchored_parent = os.fstat(parent_fd)
        current_conflict = os.stat(
            "_conflicts", dir_fd=parent_fd, follow_symlinks=False
        )
        anchored_conflict = os.fstat(conflict_fd)
    except OSError as exc:
        raise KnowledgeWriteConflict(
            f"version mismatch for rewritten note {locator.path}: "
            "anchored write directory changed"
        ) from exc
    if (
        not stat.S_ISDIR(current_parent.st_mode)
        or not _same_file_identity(current_parent, anchored_parent)
        or not stat.S_ISDIR(current_conflict.st_mode)
        or not _same_file_identity(current_conflict, anchored_conflict)
    ):
        raise KnowledgeWriteConflict(
            f"version mismatch for rewritten note {locator.path}: "
            "anchored write directory changed"
        )


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
        target = self._absolute_path(locator)
        note_class = self._classify(locator.path, WriteOperation.WRITE)
        effective_writer_identity = writer_identity or "mimer.runtime"
        written_at = datetime.now(UTC)
        # Opt-in optimistic concurrency (VMW-01 enactment-gap model; owner decision
        # 2026-07-13). Enforcement applies ONLY when the caller opts in by passing
        # ``expected_version``: a versionless write is performed normally so legacy
        # writers are never broken during progressive migration (#3570) -- the
        # structured outcome is still recorded on the receipt's ``note_class``. When a
        # caller DOES pass ``expected_version``, a REWRITTEN note whose current bytes no
        # longer match preserves the caller's proposed bytes as a provenance-bearing
        # sibling conflict artifact and returns a legible staged-conflict outcome.
        # Races after this initial comparison retain the hardened atomic exchange,
        # rollback, displaced-inode, and fail-closed behavior.
        if expected_version is not None and note_class is NoteClass.REWRITTEN:
            parent_fd = -1
            conflict_fd = -1
            staged_fd = -1
            staged_dir_fd = -1
            staged_name = f".{target.name}.{uuid.uuid4().hex}.rewrite-swap"
            preserve_staged_conflict = False
            staged_is_artifact = False
            staged_stat: os.stat_result | None = None
            staged_cleanup_stat: os.stat_result | None = None
            try:
                parent_fd = os.open(target.parent, _DIRECTORY_OPEN_FLAGS)
                conflict_fd = _open_conflict_directory(parent_fd)
                staged_dir_fd = parent_fd
                staged_fd = os.open(
                    staged_name,
                    os.O_RDWR | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=parent_fd,
                )
                payload = content.encode("utf-8")
                open_staged_fd = staged_fd
                staged_fd = -1
                with os.fdopen(open_staged_fd, "wb") as staged_handle:
                    staged_handle.write(payload)
                    staged_handle.flush()
                    os.fsync(staged_handle.fileno())
                    staged_stat = os.fstat(staged_handle.fileno())
                if staged_stat is None:
                    raise KnowledgeCapabilityError(
                        f"could not stat staged rewrite for note {locator.path}"
                    )
                staged_cleanup_stat = staged_stat
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
                    current_bytes = _read_handle(handle)
                    current_version = hashlib.sha256(current_bytes).hexdigest()
                    if current_version != expected_version:
                        preserve_staged_conflict = True
                        _require_anchored_directory_identity(
                            parent_fd, target.parent, conflict_fd, locator
                        )
                        artifact_rel = _stage_initial_stale_proposal(
                            parent_fd,
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
                            parent_fd, target.parent, conflict_fd, locator
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

                    path_stat = os.stat(
                        target.name, dir_fd=parent_fd, follow_symlinks=False
                    )
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

                _require_anchored_directory_identity(
                    parent_fd, target.parent, conflict_fd, locator
                )
                try:
                    _atomic_exchange_at(
                        parent_fd, target.name, parent_fd, staged_name
                    )
                except OSError as exc:
                    raise KnowledgeWriteConflict(
                        f"version mismatch for rewritten note {locator.path}: "
                        "atomic exchange failed"
                    ) from exc

                # The displaced inode must keep a durable path for the lifetime of any
                # already-open external descriptor. There is no portable way to know when
                # such descriptors close, so every successful optimistic exchange retains
                # this pre-exchange version as a standard conflicted copy.
                preserve_staged_conflict = True
                staged_cleanup_stat = opened_stat
                os.fsync(parent_fd)
                _require_anchored_directory_identity(
                    parent_fd, target.parent, conflict_fd, locator
                )
                artifact_name = _conflict_artifact_name(locator)
                os.rename(
                    staged_name,
                    artifact_name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=conflict_fd,
                )
                staged_name = artifact_name
                staged_dir_fd = conflict_fd
                staged_is_artifact = True
                os.fsync(parent_fd)
                os.fsync(conflict_fd)

                displaced_version = hashlib.sha256(
                    _read_entry(conflict_fd, staged_name)
                ).hexdigest()
                displaced_mode = stat.S_IMODE(
                    os.stat(
                        staged_name,
                        dir_fd=conflict_fd,
                        follow_symlinks=False,
                    ).st_mode
                )
                if displaced_version != expected_version or displaced_mode != opened_mode:
                    preserve_staged_conflict = True
                    path_stat = os.stat(
                        target.name, dir_fd=parent_fd, follow_symlinks=False
                    )
                    if _same_file_identity(path_stat, staged_stat):
                        try:
                            _atomic_exchange_at(
                                parent_fd,
                                target.name,
                                conflict_fd,
                                staged_name,
                            )
                            staged_cleanup_stat = staged_stat
                            os.fsync(parent_fd)
                            os.fsync(conflict_fd)
                        except OSError as exc:
                            raise KnowledgeWriteConflict(
                                f"version mismatch for rewritten note {locator.path}: "
                                "atomic rollback failed; displaced content was preserved"
                            ) from exc
                    if hashlib.sha256(
                        _read_entry(staged_dir_fd, staged_name)
                    ).hexdigest() == payload_version:
                        preserve_staged_conflict = False
                    raise KnowledgeWriteConflict(
                        f"version mismatch for rewritten note {locator.path}: "
                        "target changed at atomic exchange"
                    )

                path_stat = os.stat(
                    target.name, dir_fd=parent_fd, follow_symlinks=False
                )
                if not _same_file_identity(path_stat, staged_stat):
                    preserve_staged_conflict = True
                    raise KnowledgeWriteConflict(
                        f"version mismatch for rewritten note {locator.path}: "
                        "target changed after atomic exchange"
                    )
                if hashlib.sha256(
                    _read_entry(parent_fd, target.name)
                ).hexdigest() != payload_version:
                        raise KnowledgeWriteConflict(
                            f"version mismatch for rewritten note {locator.path}: "
                            "target content changed after atomic exchange"
                        )
                _require_anchored_directory_identity(
                    parent_fd, target.parent, conflict_fd, locator
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
                if staged_fd >= 0:
                    os.close(staged_fd)
                try:
                    if preserve_staged_conflict:
                        if not staged_is_artifact:
                            if (
                                staged_cleanup_stat is not None
                                and _entry_has_identity(
                                    staged_dir_fd,
                                    staged_name,
                                    staged_cleanup_stat,
                                )
                            ):
                                artifact_name = _conflict_artifact_name(locator)
                                os.rename(
                                    staged_name,
                                    artifact_name,
                                    src_dir_fd=staged_dir_fd,
                                    dst_dir_fd=conflict_fd,
                                )
                                staged_name = artifact_name
                                staged_dir_fd = conflict_fd
                                staged_is_artifact = True
                                os.fsync(parent_fd)
                                os.fsync(conflict_fd)
                            else:
                                logger.warning(
                                    "rewritten-note staged entry changed identity; "
                                    "cleanup left replacement untouched: %s",
                                    staged_name,
                                )
                    elif staged_dir_fd >= 0:
                        if (
                            staged_cleanup_stat is not None
                            and _entry_has_identity(
                                staged_dir_fd,
                                staged_name,
                                staged_cleanup_stat,
                            )
                        ):
                            try:
                                os.unlink(staged_name, dir_fd=staged_dir_fd)
                                os.fsync(staged_dir_fd)
                            except FileNotFoundError:
                                pass
                except OSError:
                    logger.exception(
                        "rewritten-note swap cleanup failed; retained staged entry %s",
                        staged_name,
                    )
                if conflict_fd >= 0:
                    os.close(conflict_fd)
                if parent_fd >= 0:
                    os.close(parent_fd)
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
            note_class=self._classify(locator.path, WriteOperation.APPEND),
            writer_identity="mimer.runtime",
            written_at=datetime.now(UTC).isoformat(),
        )

    def prepend_note(self, locator: NoteLocator, content: str) -> WriteReceipt:
        target = self._absolute_path(locator)
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content + existing, encoding="utf-8")
        return WriteReceipt(operation="prepend_note", locator=locator, adapter="fs_vault")

    def _classify(self, path: str, operation: WriteOperation) -> NoteClass:
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
            path,
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
