"""Episode Resolution Engine tick-runtime persisted state (ERE-04, #3179).

Migration ``a1b2c3d4e5f6`` creates one small generic key/value table,
``episode_engine_state``, holding the row families the segmentation tick
needs to survive a restart (spec Restart/Durability Posture: "cursors are
durable DB rows; a restart resumes from cursors and re-derives open
segments"):

- ``cursor:vault.activity:<consumer_id>`` -- the segmenter's own durable read
  position over the DB ``outbox`` table's vault-activity topics
  (:mod:`app.episodes.vault_activity_stream`). A NEW per-consumer cursor
  primitive over the shared ``outbox`` table, independent of that table's
  single ``delivered_at`` flag (the worker dispatcher's own shared delivery
  marker) -- this module never reads or writes ``delivered_at``.
- ``open_segment:<scope>`` -- the accumulated situation-model state of one
  scope's currently-open (not yet proposed) segment
  (:mod:`app.episodes.segmenter`).
- ``calendar_consumed_signal:<scope>:<signal_id>`` -- exact calendar signal
  identities whose segments closed under the fixed-window calendar poller.
  These rows outlive an open segment's deletion after closure, preventing a
  later poll from replaying stale calendar evidence into a new segment while
  preserving eligibility for changed identities.

Quiescence-closure frontiers are NOT persisted here: the segmenter computes a
per-scope observed frontier fresh from each tick's own consumed signals
(:func:`app.episodes.segmenter.run_segmentation_tick`), so there is no
durable ``stream_watermark`` row family.

``heimdal.observations`` reuses the EXISTING ``heimdal_observation_cursor``
table via ``app.heimdal.publish`` (``read_observations_for_consumer`` /
``advance_cursor_for_consumer``) and never touches this module -- this table
exists only for state that has no existing durable-cursor primitive.

Never authoritative: pure tick-runtime bookkeeping, fully replayable from the
underlying streams. Losing it only means the engine re-derives open segments
from event zero on the next tick, never a knowledge loss. Recovery posture
(see the migration docstring): reset this table together with this engine's
``heimdal_observation_cursor`` row -- full both-stream replay is
deterministic and emission-deduped; a single-stream reset is a skewed replay
and is not a supported operator action.

Fail-loud schema preflight (invariant -> producers rule, mirroring
``app.heimdal.cursor_store._assert_pg_schema``): every public function
asserts the table exists before querying it, raising
:class:`EngineStateSchemaMissingError` with a migration hint instead of a raw
``UndefinedTable`` traceback from inside a query. Schema is migration-owned;
there is no autocreate path here.
"""

from __future__ import annotations

import json
from typing import Any

from app.db.db import conn_rw

STATE_TABLE = "episode_engine_state"

_MIGRATION_HINT = (
    "episode_engine_state schema is migration-owned: run 'alembic upgrade head' "
    "against this database. See app/alembic/versions/a1b2c3d4e5f6_ere04_segmentation_engine_state.py."
)


class EngineStateSchemaMissingError(RuntimeError):
    """Raised when the episode_engine_state table is absent (pre-migration database)."""


def _assert_schema(conn: Any) -> None:
    """Fail-loud preflight: the state table must exist before any query touches it."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (STATE_TABLE,))
        row = cur.fetchone()
    oid = (row.get("to_regclass") if isinstance(row, dict) else row[0]) if row else None
    if not oid:
        raise EngineStateSchemaMissingError(f"Missing table '{STATE_TABLE}'. {_MIGRATION_HINT}")


def get_state(key: str) -> dict[str, Any] | None:
    """Return the JSON value stored at ``key``, or ``None`` if absent."""
    with conn_rw() as conn:
        _assert_schema(conn)
        with conn.cursor() as cur:
            cur.execute(f"SELECT value FROM {STATE_TABLE} WHERE key = %s", (key,))
            row = cur.fetchone()
    if row is None:
        return None
    value = row["value"] if isinstance(row, dict) else row[0]
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if value is not None else None


def set_state(key: str, value: dict[str, Any]) -> None:
    """Upsert the JSON value at ``key`` (last-write-wins, single tick-runtime writer)."""
    with conn_rw() as conn:
        _assert_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {STATE_TABLE} (key, value, updated_at)
                VALUES (%s, %s::jsonb, now())
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
                """,
                (key, json.dumps(value)),
            )


def delete_state(key: str) -> None:
    """Remove the row at ``key`` (a closed segment no longer needs its open-state row)."""
    with conn_rw() as conn:
        _assert_schema(conn)
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {STATE_TABLE} WHERE key = %s", (key,))


def all_state_with_prefix(prefix: str) -> dict[str, dict[str, Any]]:
    """Return every ``key -> value`` pair whose key starts with ``prefix``.

    Used to load every currently-open segment (``open_segment:``) at tick
    start without enumerating scopes ahead of time.
    """
    out: dict[str, dict[str, Any]] = {}
    with conn_rw() as conn:
        _assert_schema(conn)
        with conn.cursor() as cur:
            cur.execute(f"SELECT key, value FROM {STATE_TABLE} WHERE key LIKE %s", (f"{prefix}%",))
            rows = cur.fetchall()
    for r in rows:
        key = r["key"] if isinstance(r, dict) else r[0]
        value = r["value"] if isinstance(r, dict) else r[1]
        if isinstance(value, str):
            value = json.loads(value)
        out[str(key)] = dict(value or {})
    return out


__all__ = [
    "STATE_TABLE",
    "EngineStateSchemaMissingError",
    "all_state_with_prefix",
    "delete_state",
    "get_state",
    "set_state",
]
