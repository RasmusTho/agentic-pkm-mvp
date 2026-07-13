from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
import stat
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime
import hashlib
from pathlib import Path
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


def _atomic_exchange(first: Path, second: Path) -> None:
    """Atomically swap two same-filesystem paths or fail closed.

    Python does not expose the exchange variants of rename. Linux and macOS do,
    and both are used by the supported runtime/CI environments. An unsupported
    platform must reject optimistic rewritten-note writes rather than degrade to
    a non-atomic check-then-write sequence.
    """
    libc = ctypes.CDLL(ctypes.util.find_library("c") or None, use_errno=True)
    first_raw = os.fsencode(first)
    second_raw = os.fsencode(second)
    if sys.platform == "darwin":
        rename_exchange = getattr(libc, "renamex_np", None)
        if rename_exchange is None:
            raise KnowledgeCapabilityError("atomic path exchange is unavailable")
        rename_exchange.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename_exchange.restype = ctypes.c_int
        result = rename_exchange(first_raw, second_raw, 0x00000002)  # RENAME_SWAP
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
        result = rename_exchange(-100, first_raw, -100, second_raw, 0x00000002)
    else:
        raise KnowledgeCapabilityError("atomic path exchange is unavailable")
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), str(first))


def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _preserve_displaced_conflict(
    staged: Path, vault_root: Path, locator: NoteLocator
) -> Path:
    artifact_rel = conflict_artifact_path(
        locator.path,
        writer_identity=f"concurrent-save-{uuid.uuid4().hex}",
        written_at=datetime.now(UTC),
    )
    artifact = vault_root.resolve() / "_conflicts" / Path(artifact_rel)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    os.rename(staged, artifact)
    return artifact


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
        # Opt-in optimistic concurrency (VMW-01 enactment-gap model; owner decision
        # 2026-07-13). Enforcement applies ONLY when the caller opts in by passing
        # ``expected_version``: a versionless write is performed normally so legacy
        # writers are never broken during progressive migration (#3570) -- the
        # structured outcome is still recorded on the receipt's ``note_class``. When a
        # caller DOES pass ``expected_version``, a REWRITTEN note whose current bytes no
        # longer match is refused with ``KnowledgeWriteConflict`` (INV-VW1: no silent
        # overwrite of a concurrently-changed note).
        if expected_version is not None and note_class is NoteClass.REWRITTEN:
            try:
                staged_fd, staged_name = tempfile.mkstemp(
                    prefix=f".{target.name}.", suffix=".rewrite-swap", dir=target.parent
                )
            except FileNotFoundError as exc:
                raise KnowledgeWriteConflict(
                    f"version mismatch for rewritten note {locator.path}: target is missing"
                ) from exc
            staged = Path(staged_name)
            preserve_staged_conflict = False
            staged_is_artifact = False
            try:
                payload = content.encode("utf-8")
                with os.fdopen(staged_fd, "wb") as staged_handle:
                    staged_fd = -1
                    staged_handle.write(payload)
                    staged_handle.flush()
                    os.fsync(staged_handle.fileno())
                staged_stat = staged.stat()
                payload_version = hashlib.sha256(payload).hexdigest()

                # Validate twice through one descriptor, then use an atomic path exchange
                # as the linearization point. The displaced original remains addressable at
                # ``staged`` so a same-inode save in the final check/exchange gap can be
                # detected and atomically rolled back instead of being silently overwritten.
                with target.open("r+b") as handle:
                    opened_stat = os.fstat(handle.fileno())
                    current_bytes = handle.read()
                    current_version = hashlib.sha256(current_bytes).hexdigest()
                    if current_version != expected_version:
                        raise KnowledgeWriteConflict(
                            f"version mismatch for rewritten note {locator.path}"
                        )

                    path_stat = target.stat()
                    if not _same_file_identity(path_stat, opened_stat):
                        raise KnowledgeWriteConflict(
                            f"version mismatch for rewritten note {locator.path}: "
                            "target was replaced"
                        )

                    # Re-read through the still-open descriptor immediately before the
                    # mutation. Path identity alone cannot detect an editor that saved
                    # through another descriptor to the same inode after our first read.
                    handle.seek(0)
                    latest_bytes = handle.read()
                    if hashlib.sha256(latest_bytes).hexdigest() != expected_version:
                        raise KnowledgeWriteConflict(
                            f"version mismatch for rewritten note {locator.path}: "
                            "target changed during version check"
                        )
                    os.chmod(staged, stat.S_IMODE(opened_stat.st_mode))
                    opened_mode = stat.S_IMODE(opened_stat.st_mode)

                try:
                    _atomic_exchange(target, staged)
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
                staged = _preserve_displaced_conflict(staged, self.vault_root, locator)
                staged_is_artifact = True

                displaced_version = hashlib.sha256(staged.read_bytes()).hexdigest()
                displaced_mode = stat.S_IMODE(staged.stat().st_mode)
                if displaced_version != expected_version or displaced_mode != opened_mode:
                    preserve_staged_conflict = True
                    path_stat = target.stat()
                    if _same_file_identity(path_stat, staged_stat):
                        try:
                            _atomic_exchange(target, staged)
                        except OSError as exc:
                            raise KnowledgeWriteConflict(
                                f"version mismatch for rewritten note {locator.path}: "
                                "atomic rollback failed; displaced content was preserved"
                            ) from exc
                    if staged.exists() and hashlib.sha256(staged.read_bytes()).hexdigest() == (
                        payload_version
                    ):
                        preserve_staged_conflict = False
                    raise KnowledgeWriteConflict(
                        f"version mismatch for rewritten note {locator.path}: "
                        "target changed at atomic exchange"
                    )

                path_stat = target.stat()
                if not _same_file_identity(path_stat, staged_stat):
                    preserve_staged_conflict = True
                    raise KnowledgeWriteConflict(
                        f"version mismatch for rewritten note {locator.path}: "
                        "target changed after atomic exchange"
                    )
                if hashlib.sha256(target.read_bytes()).hexdigest() != payload_version:
                        raise KnowledgeWriteConflict(
                            f"version mismatch for rewritten note {locator.path}: "
                            "target content changed after atomic exchange"
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
                    if preserve_staged_conflict and staged.exists():
                        if not staged_is_artifact:
                            staged = _preserve_displaced_conflict(
                                staged, self.vault_root, locator
                            )
                            staged_is_artifact = True
                    else:
                        staged.unlink(missing_ok=True)
                except OSError:
                    logger.exception(
                        "rewritten-note swap cleanup failed; retained staged content at %s",
                        staged,
                    )
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return WriteReceipt(
            operation="write_note",
            locator=locator,
            adapter="fs_vault",
            note_class=note_class,
            writer_identity=writer_identity or "mimer.runtime",
            written_at=datetime.now(UTC).isoformat(),
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
