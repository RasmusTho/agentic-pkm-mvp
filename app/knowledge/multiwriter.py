"""ADR-0055 execution vocabulary shared by vault write and ingest slices.

This module represents the published note-class table.  It deliberately does
not stage conflicts or quarantine scan results; those behaviours belong to
VMW-02 and VMW-03.  Keeping the classification and artifact grammar here
prevents those slices from inventing incompatible policies.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath


class NoteClass(StrEnum):
    REWRITTEN = "rewritten"
    APPEND_ONLY = "append-only"
    CREATE_ONCE = "create-once"


class WriteOperation(StrEnum):
    WRITE = "write"
    APPEND = "append"
    PREPEND = "prepend"


_APPEND_ONLY_CONTROL_BODIES = frozenset(
    {
        "_heimdal/steering.log.md",
        "_heimdal/watchlist.md",
        "_heimdal/never.md",
    }
)
_ICLOUD_CONFLICT_RE = re.compile(r"\s\(conflicted copy(?:\s|\))", re.IGNORECASE)
_SAFE_WRITER_ID = re.compile(r"[^A-Za-z0-9._-]+")


def classify_note(
    path: str | PurePosixPath,
    operation: WriteOperation,
    *,
    capture_note_rel: str | PurePosixPath | None = None,
    sources_root_rel: str | PurePosixPath = "Sources",
) -> NoteClass:
    """Return the ADR-0055 class for a vault-relative path and operation."""

    normalized = PurePosixPath(path).as_posix().lstrip("/")
    lowered = normalized.casefold()
    if operation is WriteOperation.APPEND and lowered in _APPEND_ONLY_CONTROL_BODIES:
        return NoteClass.APPEND_ONLY
    capture_path = PurePosixPath(capture_note_rel).as_posix().lstrip("/").casefold() if capture_note_rel else None
    if operation is WriteOperation.APPEND and capture_path == lowered:
        return NoteClass.APPEND_ONLY
    if lowered.startswith("event-log/") or lowered.startswith("events/"):
        return NoteClass.APPEND_ONLY
    sources_root = PurePosixPath(sources_root_rel).as_posix().strip("/").casefold()
    if lowered == sources_root or lowered.startswith(f"{sources_root}/"):
        return NoteClass.CREATE_ONCE
    return NoteClass.REWRITTEN


def classify_note_in_vault(
    path: str | Path | PurePosixPath,
    operation: WriteOperation,
    *,
    vault_root: Path | str | None,
    capture_note_rel: str | PurePosixPath | None = None,
    sources_root_rel: str | PurePosixPath | None = None,
) -> NoteClass:
    """Classify a note while honoring filesystem aliases of the Sources root."""

    note_class = classify_note(
        str(path),
        operation,
        capture_note_rel=capture_note_rel,
        sources_root_rel=sources_root_rel or "Sources",
    )
    if (
        note_class is NoteClass.CREATE_ONCE
        or vault_root is None
        or sources_root_rel is None
    ):
        return note_class

    # The published classifier is intentionally lexical and filesystem-agnostic.
    # Runtime adapters also know the selected vault and must preserve create-once
    # behavior when either side is addressed through a symlink or Unicode alias.
    from app.vault.path_overlap import vault_path_is_within

    if vault_path_is_within(path, sources_root_rel, vault_root=Path(vault_root)):
        return NoteClass.CREATE_ONCE
    return note_class


def conflict_artifact_path(
    canonical_path: str | PurePosixPath,
    *,
    writer_identity: str,
    written_at: datetime,
) -> PurePosixPath:
    """Create the shared staged-conflict filename using iCloud-compatible wording."""

    path = PurePosixPath(canonical_path)
    safe_writer = _SAFE_WRITER_ID.sub("-", writer_identity.strip()).strip("-") or "unknown-writer"
    timestamp = written_at.astimezone(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    suffix = path.suffix or ".md"
    stem = path.name[: -len(suffix)] if path.suffix else path.name
    return path.with_name(f"{stem} (conflicted copy {safe_writer} {timestamp}){suffix}")


def is_conflict_artifact(path: str | PurePosixPath) -> bool:
    """Recognize both iCloud conflict copies and VMW-02 staged artifacts."""

    return bool(_ICLOUD_CONFLICT_RE.search(PurePosixPath(path).name))


__all__ = [
    "NoteClass",
    "WriteOperation",
    "classify_note",
    "classify_note_in_vault",
    "conflict_artifact_path",
    "is_conflict_artifact",
]
