"""Rebuild the ``episodes`` Postgres projection from vault-canonical Episode notes.

Spec: ``docs/EPISODE_RESOLUTION_ENGINE/EPISODE_NOTE_STORE_AND_PROJECTION.md`` (ERE-02).

Episode notes (``app/episodes/store.py``, one markdown note per episode under
``episodes/`` in the vault) are the canonical record (ADR-0051 OD-1/OD-2); the
``episodes`` table is a rebuildable projection index over them (DRI discipline), following
the ``decisions`` projection precedent (``app/jobs/decisions_projection.py``). This module:

- ``rebuild_episodes_projection()`` -- truncate the ``episodes`` table and replay every
  episode note found under the vault's ``episodes/`` subtree back into it. A note that fails
  schema validation is skipped as an orphan (never partially inserted), so a rebuild never
  silently corrupts the projection from a malformed note.
- ``doctor_episodes_projection()`` -- assert the DB projection equals the vault notes
  row-for-row (verify-the-verifier). Returns a structured report; ``ok`` is ``True`` only when
  they match.

Both operate on the durable Postgres path only, matching the ``decisions`` projection's scope.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.db.db import conn_rw
from app.episodes.notes import EPISODE_NOTES_DIR, parse_episode_note
from app.episodes.schema import EpisodeSchemaValidationError, validate_episode_note_fields
from app.vault.manager import iter_vault_markdown_files

EPISODES_TABLE = "episodes"


@dataclass
class RebuildSummary:
    total_notes: int = 0
    inserted: int = 0
    skipped_invalid: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DoctorReport:
    ok: bool
    db_rows: int
    vault_rows: int
    missing_in_db: list[dict[str, Any]] = field(default_factory=list)
    extra_in_db: list[dict[str, Any]] = field(default_factory=list)


def _iter_episode_notes(vault_root: Path) -> list[tuple[str, dict[str, Any]]]:
    """Yield ``(note_rel_path, fields)`` for every schema-valid episode note under
    ``vault_root/episodes``. Skips (does not raise on) malformed notes -- callers collect
    those as orphans."""
    subtree = vault_root / EPISODE_NOTES_DIR
    out: list[tuple[str, dict[str, Any]]] = []
    for path in iter_vault_markdown_files(vault_root, subtree_root=subtree):
        rel = path.relative_to(vault_root).as_posix()
        text = path.read_text(encoding="utf-8")
        fields = parse_episode_note(text)
        out.append((rel, fields))
    return out


def _row_tuple(fields: dict[str, Any], note_path: str) -> tuple[Any, ...]:
    time_fields = fields.get("time") or {}
    return (
        fields["episode_id"],
        fields["scope"],
        fields["title"],
        time_fields.get("start"),
        time_fields.get("end"),
        bool(time_fields.get("closed", False)),
        fields["segmentation"],
        fields.get("parent_episode"),
        json.dumps(fields.get("space") or []),
        json.dumps(fields.get("protagonists") or []),
        json.dumps(fields.get("goal") or []),
        json.dumps(fields.get("causation") or []),
        json.dumps(fields.get("derived_from") or []),
        note_path,
    )


def rebuild_episodes_projection(vault_root: Path) -> RebuildSummary:
    """Truncate and repopulate the ``episodes`` table from vault episode notes.

    Runs in one transaction: the truncate and every replayed insert commit together, so a
    failure mid-replay leaves the prior projection intact.
    """
    notes = _iter_episode_notes(vault_root)
    summary = RebuildSummary(total_notes=len(notes))

    with conn_rw() as conn:
        with conn.cursor() as cur:
            cur.execute(f"TRUNCATE TABLE {EPISODES_TABLE}")

            for note_path, fields in notes:
                try:
                    validate_episode_note_fields(fields)
                except EpisodeSchemaValidationError as exc:
                    summary.skipped_invalid.append(
                        {"note_path": note_path, "reason": str(exc)}
                    )
                    continue

                cur.execute(
                    f"""
                    INSERT INTO {EPISODES_TABLE} (
                        episode_id, scope, title, time_start, time_end, closed,
                        segmentation, parent_episode, space, protagonists, goal,
                        causation, derived_from, note_path
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s
                    )
                    """,
                    _row_tuple(fields, note_path),
                )
                summary.inserted += 1

    return summary


def _db_projection_rows() -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    with conn_rw() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT episode_id, scope, title, time_start, time_end, closed,
                       segmentation, parent_episode, space, protagonists, goal,
                       causation, derived_from, note_path
                FROM {EPISODES_TABLE}
                """
            )
            for r in cur.fetchall():
                if isinstance(r, dict):
                    values = (
                        r["episode_id"], r["scope"], r["title"], r["time_start"],
                        r["time_end"], r["closed"], r["segmentation"], r["parent_episode"],
                        r["space"], r["protagonists"], r["goal"], r["causation"],
                        r["derived_from"], r["note_path"],
                    )
                else:
                    values = tuple(r)
                rows.append(_normalize_row(values))
    return sorted(rows, key=lambda row: row[0])


def _normalize_row(values: tuple[Any, ...]) -> tuple[Any, ...]:
    def _norm(v: Any) -> Any:
        if isinstance(v, (list, dict)):
            return json.dumps(v, sort_keys=True)
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return v

    return tuple(_norm(v) for v in values)


def _vault_projection_rows(vault_root: Path) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for note_path, fields in _iter_episode_notes(vault_root):
        try:
            validate_episode_note_fields(fields)
        except EpisodeSchemaValidationError:
            continue
        raw = _row_tuple(fields, note_path)
        # _row_tuple pre-serializes list fields to JSON text already; leave scalars as-is.
        rows.append(tuple(json.loads(v) if isinstance(v, str) and v.startswith(("[", "{")) else v for v in raw))
    return sorted(rows, key=lambda row: row[0])


def doctor_episodes_projection(vault_root: Path) -> DoctorReport:
    """Assert the DB projection matches the vault notes row-for-row."""
    vault_rows = [_normalize_row(r) for r in _vault_projection_rows(vault_root)]
    db_rows = _db_projection_rows()

    vault_counter = Counter(vault_rows)
    db_counter = Counter(db_rows)

    missing = list((vault_counter - db_counter).elements())
    extra = list((db_counter - vault_counter).elements())

    def _fmt(row: tuple[Any, ...]) -> dict[str, Any]:
        return {"episode_id": row[0], "note_path": row[-1]}

    return DoctorReport(
        ok=not missing and not extra,
        db_rows=len(db_rows),
        vault_rows=len(vault_rows),
        missing_in_db=[_fmt(r) for r in missing],
        extra_in_db=[_fmt(r) for r in extra],
    )


__all__ = [
    "DoctorReport",
    "EPISODES_TABLE",
    "RebuildSummary",
    "doctor_episodes_projection",
    "rebuild_episodes_projection",
]
