"""Rebuild the derived ``standing_questions`` projection from vault Question notes."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.store.standing_questions_projection import replace_standing_questions_projection
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
    replace_standing_questions_projection(notes)
    return ProjectionRebuildSummary(inserted=len(notes))


__all__ = ["ProjectionRebuildSummary", "iter_question_notes", "rebuild_standing_questions_projection"]
