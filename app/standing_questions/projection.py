"""Rebuild the derived ``standing_questions`` projection from vault Question notes."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.db.db import conn_rw
from app.standing_questions.question_store import QUESTION_DIRECTORY, parse_question_note


@dataclass(frozen=True)
class ProjectionRebuildSummary:
    inserted: int


def iter_question_notes(vault_root: Path | str) -> list[tuple[str, dict[str, Any]]]:
    root = Path(vault_root).expanduser().resolve() / QUESTION_DIRECTORY
    if not root.exists():
        return []
    notes: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(root.glob("sq-*.md")):
        source_path = path.relative_to(Path(vault_root).expanduser().resolve()).as_posix()
        notes.append((source_path, parse_question_note(path.read_text(encoding="utf-8"))))
    return notes


def rebuild_standing_questions_projection(vault_root: Path | str) -> ProjectionRebuildSummary:
    """Replace every derived row with the canonical vault state in one transaction."""
    notes = iter_question_notes(vault_root)
    with conn_rw() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE standing_questions")
            for source_path, note in notes:
                cur.execute(
                    """
                    INSERT INTO standing_questions (
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
                        note["created_at"],
                        note["registered_via"],
                        note.get("standing_answer_ref"),
                        note.get("candidate_answer_ref"),
                        json.dumps(note["evidence"]),
                        note.get("last_matched_at"),
                        note.get("last_refreshed_at"),
                        source_path,
                    ),
                )
    return ProjectionRebuildSummary(inserted=len(notes))


__all__ = ["ProjectionRebuildSummary", "iter_question_notes", "rebuild_standing_questions_projection"]
