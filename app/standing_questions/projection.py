"""Rebuild the derived ``standing_questions`` projection from vault Question notes."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import ValidationError

from app.store.standing_questions_projection import replace_standing_questions_projection
from app.standing_questions.question_store import QUESTION_DIRECTORY, parse_question_note
from app.vault.manager import iter_vault_markdown_files


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


def rebuild_standing_questions_projection(vault_root: Path | str) -> ProjectionRebuildSummary:
    """Replace every derived row with the canonical vault state in one transaction.

    A malformed note is skipped, not fatal, to the rest of the rebuild. If the
    ``questions/`` directory itself is missing, this raises instead of truncating the
    projection down to nothing -- see :class:`QuestionsDirectoryMissingError`.
    """
    notes, skipped = _read_question_notes(vault_root)
    replace_standing_questions_projection(notes)
    return ProjectionRebuildSummary(inserted=len(notes), skipped_invalid=tuple(skipped))


__all__ = [
    "ProjectionRebuildSummary",
    "QuestionsDirectoryMissingError",
    "iter_question_notes",
    "rebuild_standing_questions_projection",
]
