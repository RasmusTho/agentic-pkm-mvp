"""Postgres writer for the rebuildable Standing Questions projection."""
from __future__ import annotations

import json
from typing import Any

from app.db.db import conn_rw


def replace_standing_questions_projection(notes: list[tuple[str, dict[str, Any]]]) -> None:
    """Replace derived rows from vault-canonical Question notes in one transaction."""
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


__all__ = ["replace_standing_questions_projection"]
