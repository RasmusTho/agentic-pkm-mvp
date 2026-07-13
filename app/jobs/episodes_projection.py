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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db.db import conn_rw
from app.episodes.notes import EPISODE_NOTES_DIR, parse_validated_episode_note
from app.episodes.schema import EpisodeSchemaValidationError
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
    unreadable_vault_notes: list[dict[str, str]] = field(default_factory=list)


def _episode_note_paths(vault_root: Path) -> list[Path]:
    """Return every episode-note path; callers validate each raw note explicitly."""
    return list(
        iter_vault_markdown_files(vault_root, subtree_root=vault_root / EPISODE_NOTES_DIR)
    )


def row_tuple(fields: dict[str, Any], note_path: str) -> tuple[Any, ...]:
    """The row shape both the full rebuild INSERT and the incremental new-row INSERT
    (``app.episodes.segmenter._sync_new_episode_row``, #3532) use -- single-sourced so the
    two paths can never drift apart in column order."""
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
    note_paths = _episode_note_paths(vault_root)
    summary = RebuildSummary(total_notes=len(note_paths))
    validated_rows: list[tuple[dict[str, Any], str]] = []

    # Read and validate before entering the truncating transaction. Schema-invalid
    # notes are deliberately excluded from this derived index, while a vault I/O,
    # decode, or frontmatter parse failure preserves the prior projection.
    for path in note_paths:
        note_path = path.relative_to(vault_root).as_posix()
        try:
            fields = parse_validated_episode_note(path.read_text(encoding="utf-8"))
        except EpisodeSchemaValidationError as exc:
            summary.skipped_invalid.append({"note_path": note_path, "reason": str(exc)})
            continue
        validated_rows.append((fields, note_path))

    with conn_rw() as conn:
        with conn.cursor() as cur:
            cur.execute(f"TRUNCATE TABLE {EPISODES_TABLE}")

            for fields, note_path in validated_rows:
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
                    row_tuple(fields, note_path),
                )
                summary.inserted += 1

    return summary


def _norm_ts(value: Any) -> str | None:
    """Canonical UTC ISO string for a timestamp coming from either side of the
    comparison: a ``datetime`` (DB side) or an ISO-8601/RFC-3339 string (vault side --
    the note schema's ``format: date-time`` permits a ``Z`` suffix, which must compare
    equal to its ``+00:00`` spelling). Instant-based, never a raw string comparison.
    An unparseable string is returned verbatim so genuine garbage surfaces as drift
    instead of being masked."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return str(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _norm_json_list(value: Any) -> str:
    """Canonical JSON text for a list field. Accepts a Python list (vault-native, or
    psycopg's decoded jsonb) or -- only for a value known to come from a jsonb column --
    its JSON text. Never applied to scalar fields, so a title like '[Retro] Sprint 12'
    can never be mistaken for JSON."""
    if isinstance(value, str):
        value = json.loads(value)
    return json.dumps(value or [], sort_keys=True)


def _comparison_row(fields: dict[str, Any], note_path: str) -> tuple[Any, ...]:
    """Normalized comparison tuple built directly from the Python-native note fields.

    Purpose-made for the doctor: lists are serialized once (they are still lists
    here -- no dump/load round-trip through ``row_tuple``), scalar fields like
    ``title`` are carried verbatim with no format sniffing, and timestamps are
    normalized instant-wise via ``_norm_ts`` so a ``Z``-suffixed note compares equal
    to the DB's ``+00:00`` rendering."""
    time_fields = fields.get("time") or {}
    return (
        fields["episode_id"],
        fields["scope"],
        fields["title"],
        _norm_ts(time_fields.get("start")),
        _norm_ts(time_fields.get("end")),
        bool(time_fields.get("closed", False)),
        fields["segmentation"],
        fields.get("parent_episode"),
        _norm_json_list(fields.get("space")),
        _norm_json_list(fields.get("protagonists")),
        _norm_json_list(fields.get("goal")),
        _norm_json_list(fields.get("causation")),
        _norm_json_list(fields.get("derived_from")),
        note_path,
    )


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
                # Same normalized shape as _comparison_row, per-column by known type --
                # timestamps instant-normalized, jsonb list columns canonicalized,
                # scalar columns carried verbatim (no sniffing).
                rows.append(
                    (
                        values[0],
                        values[1],
                        values[2],
                        _norm_ts(values[3]),
                        _norm_ts(values[4]),
                        bool(values[5]),
                        values[6],
                        values[7],
                        _norm_json_list(values[8]),
                        _norm_json_list(values[9]),
                        _norm_json_list(values[10]),
                        _norm_json_list(values[11]),
                        _norm_json_list(values[12]),
                        values[13],
                    )
                )
    return sorted(rows, key=lambda row: row[0])


def _vault_projection_rows(
    vault_root: Path,
) -> tuple[list[tuple[Any, ...]], list[dict[str, str]]]:
    rows: list[tuple[Any, ...]] = []
    unreadable: list[dict[str, str]] = []
    for path in _episode_note_paths(vault_root):
        note_path = path.relative_to(vault_root).as_posix()
        try:
            fields = parse_validated_episode_note(path.read_text(encoding="utf-8"))
        except EpisodeSchemaValidationError:
            continue
        except Exception as exc:
            unreadable.append({"note_path": note_path, "reason": str(exc)})
            continue
        rows.append(_comparison_row(fields, note_path))
    return sorted(rows, key=lambda row: row[0]), unreadable


def doctor_episodes_projection(vault_root: Path) -> DoctorReport:
    """Assert the DB projection matches the vault notes row-for-row."""
    vault_rows, unreadable_vault_notes = _vault_projection_rows(vault_root)
    db_rows = _db_projection_rows()

    vault_counter = Counter(vault_rows)
    db_counter = Counter(db_rows)

    missing = list((vault_counter - db_counter).elements())
    extra = list((db_counter - vault_counter).elements())

    def _fmt(row: tuple[Any, ...]) -> dict[str, Any]:
        return {"episode_id": row[0], "note_path": row[-1]}

    return DoctorReport(
        ok=not missing and not extra and not unreadable_vault_notes,
        db_rows=len(db_rows),
        vault_rows=len(vault_rows),
        missing_in_db=[_fmt(r) for r in missing],
        extra_in_db=[_fmt(r) for r in extra],
        unreadable_vault_notes=unreadable_vault_notes,
    )


__all__ = [
    "DoctorReport",
    "EPISODES_TABLE",
    "RebuildSummary",
    "doctor_episodes_projection",
    "rebuild_episodes_projection",
    "row_tuple",
]
