"""Rebuild the derived ``standing_questions`` projection from vault Question notes.

The ``standing_questions`` table is a rebuildable Postgres projection over the
vault-canonical Question notes (DRI discipline). This module owns both the read
(parse notes) and write (TRUNCATE + replay) sides, inlining the one-transaction DB
write via ``app.db.db.conn_rw`` -- the same non-deprecated pattern the episodes and
decisions projection jobs use (``app/jobs/episodes_projection.py``,
``app/jobs/decisions_projection.py``), rather than a separate module under the
deprecated ``app.store`` package (ADR-0013).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import ValidationError

from app.db.db import conn_rw
from app.standing_questions.question_store import (
    QUESTION_DIRECTORY,
    parse_question_note,
    parse_rfc3339_datetime,
)
from app.vault.manager import iter_vault_markdown_files

STANDING_QUESTIONS_TABLE = "standing_questions"


class QuestionsDirectoryMissingError(FileNotFoundError):
    """Raised when the vault's ``questions/`` directory does not exist.

    Distinct from "directory present but legitimately empty" (zero valid notes,
    which is a normal empty projection). A rebuild must never TRUNCATE-and-replay
    against a missing directory -- that would silently wipe an existing projection
    on a transient or misconfigured missing dir. Callers should treat this as a
    hard failure, not an empty result.
    """


@dataclass(frozen=True)
class ProjectionRebuildSummary:
    inserted: int
    skipped_invalid: tuple[dict[str, Any], ...] = ()


def _read_question_notes(
    vault_root: Path | str,
) -> tuple[list[tuple[str, dict[str, Any]]], list[dict[str, Any]]]:
    """Parse every Question note under the vault's ``questions/`` directory.

    A note that fails frontmatter parsing or schema validation is skipped (collected,
    not raised) so one malformed file cannot abort the rebuild for every valid note.
    Raises :class:`QuestionsDirectoryMissingError` if the directory itself is absent.
    """
    resolved_root = Path(vault_root).expanduser().resolve()
    root = resolved_root / QUESTION_DIRECTORY
    if not root.exists():
        raise QuestionsDirectoryMissingError(
            f"questions/ directory not found under vault root: {resolved_root}"
        )
    notes: list[tuple[str, dict[str, Any]]] = []
    skipped: list[dict[str, Any]] = []
    # Reuses the shared vault walker (#2522 nested-vault boundary) instead of a hand-rolled
    # glob, so a nested child vault's notes are never projected into the parent's table.
    for path in sorted(iter_vault_markdown_files(resolved_root, subtree_root=root)):
        if not path.name.startswith("sq-"):
            continue
        source_path = path.relative_to(resolved_root).as_posix()
        try:
            note = parse_question_note(path.read_text(encoding="utf-8"))
        except (ValueError, ValidationError) as exc:
            skipped.append({"note_path": source_path, "reason": str(exc)})
            continue
        notes.append((source_path, note))
    return notes, skipped


def iter_question_notes(vault_root: Path | str) -> list[tuple[str, dict[str, Any]]]:
    """Return every schema-valid Question note under the vault. See
    :func:`rebuild_standing_questions_projection` for how skipped notes are reported."""
    notes, _skipped = _read_question_notes(vault_root)
    return notes


def _postgres_timestamptz_value(value: str | None) -> str | None:
    """Adapt a schema-valid RFC 3339 value to PostgreSQL's timestamp grammar.

    The vault remains canonical and retains ``value`` byte-for-byte. PostgreSQL 16
    rejects valid RFC 3339 offsets at and above 16 hours and does not accept year
    ``0000`` directly, so the query-only projection receives an equivalent UTC
    instant, with astronomical year zero rendered as PostgreSQL ``0001 BC``.
    """
    if value is None:
        return None
    timestamp = parse_rfc3339_datetime(value)
    if timestamp is None:
        raise ValueError(f"projection received an invalid RFC 3339 timestamp: {value!r}")
    year, month, day, hour, minute = timestamp.utc_date_and_minute()
    era = ""
    if year <= 0:
        year = 1 - year
        era = " BC"
    return (
        f"{year:04d}-{month:02d}-{day:02d} "
        f"{hour:02d}:{minute:02d}:{timestamp.second:02d}"
        f"{timestamp.fraction}+00{era}"
    )


def _replace_projection_rows(notes: list[tuple[str, dict[str, Any]]]) -> None:
    """Replace every derived row from vault-canonical Question notes in one transaction.

    The TRUNCATE and every replayed INSERT commit together, so a failure mid-replay
    leaves the prior projection intact -- mirroring the episodes projection job's
    single-transaction rebuild.
    """
    with conn_rw() as conn:
        with conn.cursor() as cur:
            cur.execute(f"TRUNCATE TABLE {STANDING_QUESTIONS_TABLE}")
            for source_path, note in notes:
                cur.execute(
                    f"""
                    INSERT INTO {STANDING_QUESTIONS_TABLE} (
                        question_id, scope, text, status, created_at, registered_via,
                        standing_answer_ref, candidate_answer_ref, evidence,
                        last_matched_at, last_refreshed_at, source_path
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                    """,
                    (
                        note["question_id"],
                        note["scope"],
                        note["text"],
                        note["status"],
                        _postgres_timestamptz_value(note["created_at"]),
                        note["registered_via"],
                        note.get("standing_answer_ref"),
                        note.get("candidate_answer_ref"),
                        json.dumps(note["evidence"]),
                        _postgres_timestamptz_value(note.get("last_matched_at")),
                        _postgres_timestamptz_value(note.get("last_refreshed_at")),
                        source_path,
                    ),
                )


def rebuild_standing_questions_projection(vault_root: Path | str) -> ProjectionRebuildSummary:
    """Replace every derived row with the canonical vault state in one transaction.

    A malformed note is skipped, not fatal, to the rest of the rebuild. If the
    ``questions/`` directory itself is missing, this raises instead of truncating the
    projection down to nothing -- see :class:`QuestionsDirectoryMissingError`.
    """
    notes, skipped = _read_question_notes(vault_root)
    _replace_projection_rows(notes)
    return ProjectionRebuildSummary(inserted=len(notes), skipped_invalid=tuple(skipped))


__all__ = [
    "ProjectionRebuildSummary",
    "QuestionsDirectoryMissingError",
    "STANDING_QUESTIONS_TABLE",
    "iter_question_notes",
    "rebuild_standing_questions_projection",
]
