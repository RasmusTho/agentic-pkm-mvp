"""Bounded PostgreSQL adapter for the Episode Debrief trigger.

Reuses migration-owned episodes, bindings, outbox and episode_engine_state.
The cursor is only a position; no separate owed-work table exists.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from pathlib import Path
from uuid import UUID

from app.db.db import conn_rw
from app.db.replay_projection_schema import assert_replay_projection_schema
from app.episodes.assignment import BINDING_STATE_ACTIVE, BINDING_TABLE
from app.episodes.engine_state import STATE_TABLE
from app.events.types import EPISODE_CLOSED
from app.instance.binding_ids import COMPATIBILITY_BINDING_ID

CONSUMER_ID = "episode_debrief.trigger"
CURSOR_KEY = f"cursor:episode.closed:{CONSUMER_ID}"


@dataclass(frozen=True)
class CursorPosition:
    created_at: datetime
    row_id: str


@dataclass(frozen=True)
class ClosureRow:
    position: CursorPosition
    payload: Any


@dataclass(frozen=True)
class EpisodeRow:
    episode_id: str
    note_path: str
    bound_artifact_count: int


def get_cursor(*, vault_binding_id: str = COMPATIBILITY_BINDING_ID) -> CursorPosition | None:
    with conn_rw() as conn:
        assert_replay_projection_schema(conn, STATE_TABLE)
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT value FROM {STATE_TABLE} WHERE vault_binding_id = %s AND key = %s",
                (vault_binding_id, CURSOR_KEY),
            )
            row = cur.fetchone()
    if row is None:
        return None
    value = row["value"] if isinstance(row, dict) else row[0]
    if isinstance(value, str):
        value = json.loads(value)
    # Corrupt durable state is a refusal, never an implicit rewind.
    try:
        created = datetime.fromisoformat(value["created_at"])
        row_id = str(UUID(value["id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("episode debrief cursor is corrupt") from exc
    if created.tzinfo is None:
        raise ValueError("episode debrief cursor requires an aware timestamp")
    return CursorPosition(created.astimezone(timezone.utc), row_id)


def read_closures(
    *, vault_binding_id: str = COMPATIBILITY_BINDING_ID, limit: int = 1000
) -> list[ClosureRow]:
    if limit < 1:
        raise ValueError("episode debrief batch limit must be positive")
    position = get_cursor(vault_binding_id=vault_binding_id)
    query = "SELECT id, payload, created_at FROM outbox WHERE topic = %s AND vault_binding_id = %s"
    params: list[Any] = [EPISODE_CLOSED, vault_binding_id]
    if position is not None:
        query += " AND (created_at, id) > (%s, %s::uuid)"
        params.extend((position.created_at, position.row_id))
    query += " ORDER BY created_at ASC, id ASC LIMIT %s"
    params.append(limit)
    with conn_rw() as conn:
        with conn.cursor() as cur:
            cur.execute(query, tuple(params))
            rows = cur.fetchall()
    return [
        ClosureRow(
            CursorPosition(
                row["created_at"] if isinstance(row, dict) else row[2],
                str(row["id"] if isinstance(row, dict) else row[0]),
            ),
            row["payload"] if isinstance(row, dict) else row[1],
        )
        for row in rows
    ]


def closed_episodes(*, vault_binding_id: str = COMPATIBILITY_BINDING_ID, episode_id: str | None = None) -> list[EpisodeRow]:
    """Re-derive eligibility from the projection and its current active bindings."""
    with conn_rw() as conn:
        assert_replay_projection_schema(conn, "episodes")
        assert_replay_projection_schema(conn, BINDING_TABLE)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT e.episode_id, e.note_path, count(b.artifact_ref) AS artifact_count
                FROM episodes e LEFT JOIN {BINDING_TABLE} b
                  ON b.vault_binding_id = e.vault_binding_id AND b.episode_id = e.episode_id
                 AND b.binding_state = %s
                WHERE e.vault_binding_id = %s AND e.closed = true AND (%s::text IS NULL OR e.episode_id = %s)
                GROUP BY e.episode_id, e.note_path ORDER BY e.episode_id
                """,
                (BINDING_STATE_ACTIVE, vault_binding_id, episode_id, episode_id),
            )
            rows = cur.fetchall()
    return [
        EpisodeRow(
            str(row["episode_id"] if isinstance(row, dict) else row[0]),
            str(row["note_path"] if isinstance(row, dict) else row[1]),
            int(row["artifact_count"] if isinstance(row, dict) else row[2]),
        )
        for row in rows
    ]


def advance_cursor(
    position: CursorPosition, *, vault_binding_id: str = COMPATIBILITY_BINDING_ID
) -> None:
    """Atomic monotone advancement, including concurrent/stale tick completion.

    Compare PostgreSQL timestamps and UUIDs, not ISO string ordering. Only this
    binding's consumer row can change. A failed transaction leaves it unchanged.
    """
    value = {"created_at": position.created_at.astimezone(timezone.utc).isoformat(), "id": position.row_id}
    with conn_rw() as conn:
        assert_replay_projection_schema(conn, STATE_TABLE)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {STATE_TABLE} (vault_binding_id, key, value, updated_at)
                VALUES (%s, %s, %s::jsonb, now())
                ON CONFLICT (vault_binding_id, key) DO UPDATE
                   SET value = EXCLUDED.value, updated_at = now()
                 WHERE (({STATE_TABLE}.value->>'created_at')::timestamptz,
                        ({STATE_TABLE}.value->>'id')::uuid)
                     < ((EXCLUDED.value->>'created_at')::timestamptz,
                        (EXCLUDED.value->>'id')::uuid)
                """,
                (vault_binding_id, CURSOR_KEY, json.dumps(value)),
            )


def synthesis_inputs(
    episode_id: str, *, projection_binding_ids: tuple[str, ...],
) -> tuple[EpisodeRow, tuple[tuple[str, str], ...], str]:
    """Resolve the same winning projection as DEBRIEF-01 plus its active members."""
    candidates = [
        (row, binding)
        for binding in projection_binding_ids
        for row in closed_episodes(vault_binding_id=binding, episode_id=episode_id)
        if row.episode_id == episode_id
    ]
    if not candidates:
        raise ValueError("debrief episode is missing or not closed")
    row, binding = max(candidates, key=lambda item: item[0].bound_artifact_count)
    with conn_rw() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT artifact_ref, scope FROM {BINDING_TABLE} "
                "WHERE vault_binding_id = %s AND episode_id = %s AND binding_state = 'active' "
                "ORDER BY artifact_ref", (binding, episode_id),
            )
            rows = cur.fetchall()
    return row, tuple(
        (item['artifact_ref'], item['scope']) if isinstance(item, dict) else (item[0], item[1])
        for item in rows
    ), binding


@dataclass(frozen=True)
class SynthesisArtifact:
    identity: str
    provenance_ref: str
    content_hash: str | None = None
    observed_at: float | None = None
    content_fingerprint: str | None = None


def canonical_note_identity(vault_uuid: str, *, vault_binding_id: str) -> str:
    from app.objects.identity import resolve_vault_uuid_with_connection
    with conn_rw() as conn:
        return resolve_vault_uuid_with_connection(conn, vault_uuid, vault_binding_id=vault_binding_id)


def resolve_synthesis_artifact(
    ref: str, *, vault_binding_id: str, vault_root: "Path",
) -> SynthesisArtifact:
    """Resolve ordinary watcher events using the canonical contained-note identity seam."""
    from pathlib import Path
    from app.episodes.vault_activity_stream import _resolve_note_path
    from app.episode_debrief.trigger import _assert_selected_vault_owns_path
    from app.ingest.vault_alpha import resolve_vault_note_identity
    from app.knowledge.write_ops import read_note_text_with_version
    from scripts.yaml_roundtrip import load_frontmatter
    if not ref.startswith("vault.activity:"):
        return SynthesisArtifact(ref, ref)
    row_id = str(UUID(ref.removeprefix("vault.activity:")))
    with conn_rw() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT payload FROM outbox WHERE id=%s::uuid AND vault_binding_id=%s", (row_id, vault_binding_id))
            row = cur.fetchone()
    if row is None:
        raise ValueError("bound activity provenance cannot be resolved")
    value = row['payload'] if isinstance(row, dict) else row[0]
    if isinstance(value, str):
        value = json.loads(value)
    payload = value.get('payload', value)
    identity = payload.get('object_id') or payload.get('uuid')
    if not isinstance(identity, str) or not identity:
        path = _resolve_note_path(payload, vault_root=Path(vault_root))
        if path is None:
            raise ValueError("bound activity has no contained retained note")
        _assert_selected_vault_owns_path(vault_root, path, "bound activity note")
        raw, _ = read_note_text_with_version(path)
        fields, body = load_frontmatter(raw)
        note_identity = resolve_vault_note_identity(path, vault_root=vault_root, frontmatter=fields, body=body)
        identity = canonical_note_identity(note_identity.note_uuid, vault_binding_id=vault_binding_id)
    from app.episode_debrief.evidence import commitment_content_fingerprint
    extensions = payload.get("extensions") or {}
    content_fingerprint = extensions.get("episode_debrief_content_fingerprint")
    if isinstance(payload.get("frontmatter"), dict):
        content_fingerprint = commitment_content_fingerprint(payload["frontmatter"], payload.get("content", ""))
    observed_at = payload.get("mtime")
    if observed_at is None and extensions.get("observed_at"):
        observed_at = datetime.fromisoformat(extensions["observed_at"].replace("Z", "+00:00")).timestamp()
    return SynthesisArtifact(identity, ref, payload.get('hash'), observed_at, content_fingerprint)


def trigger_for_episode(episode_id: str, *, vault_binding_id: str) -> dict[str, Any]:
    """CLI replay consumes existing durable intent, never invents a human-triggered draft."""
    with conn_rw() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM outbox WHERE topic='debrief.trigger.created' "
                "AND vault_binding_id=%s AND payload->'payload'->>'episode_id'=%s "
                "ORDER BY created_at, id LIMIT 1", (vault_binding_id, episode_id),
            )
            row = cur.fetchone()
    if row is None:
        raise ValueError("no durable debrief trigger exists for this Episode")
    value = row['payload'] if isinstance(row, dict) else row[0]
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value['payload'])


def bound_heimdal_observations(refs: list[str], *, scope: str, episode_id: str,
                               binding_ids: set[str] | None) -> list[Any]:
    """Read immutable observation envelopes through exact active Episode membership."""
    with conn_rw() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ON (b.artifact_ref) b.artifact_ref, h.payload
                FROM episode_artifact_binding b JOIN heimdal_observation_log h
                  ON b.artifact_ref = 'heimdal.observations:' || (h.payload->'payload'->>'observation_id')
                WHERE b.artifact_ref = ANY(%s) AND b.episode_id=%s AND b.scope=%s
                  AND b.binding_state='active' AND b.vault_binding_id = ANY(%s)
                ORDER BY b.artifact_ref, h.sequence DESC
            """, (refs, episode_id, scope, sorted(binding_ids if binding_ids is not None else {COMPATIBILITY_BINDING_ID})))
            rows = cur.fetchall()
    return rows
