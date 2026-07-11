"""Episode Resolution Engine tick-runtime persisted state (ERE-04, #3179).

Migration ``a1b2c3d4e5f6`` creates one small generic key/value table,
``episode_engine_state``, holding two logically distinct row families the
segmentation tick needs to survive a restart (spec Restart/Durability
Posture: "cursors are durable DB rows; a restart resumes from cursors and
re-derives open segments"):

- ``cursor:vault.activity:<consumer_id>`` -- the segmenter's own durable read
  position over the DB ``outbox`` table's vault-activity topics
  (:mod:`app.episodes.vault_activity_stream`). A NEW per-consumer cursor
  primitive over the shared ``outbox`` table, independent of that table's
  single ``delivered_at`` flag (the worker dispatcher's own shared delivery
  marker) -- this module never reads or writes ``delivered_at``.
- ``open_segment:<scope>`` -- the accumulated situation-model state of one
  scope's currently-open (not yet proposed) segment
  (:mod:`app.episodes.segmenter`).

``heimdal.observations`` reuses the EXISTING ``heimdal_observation_cursor``
table via ``app.heimdal.publish`` (``read_observations_for_consumer`` /
``advance_cursor_for_consumer``) and never touches this module -- this table
exists only for state that has no existing durable-cursor primitive.

Never authoritative: pure tick-runtime bookkeeping, fully replayable from the
underlying streams. Losing it only means the engine re-derives open segments
from event zero on the next tick, never a knowledge loss.
"""

from __future__ import annotations

import json
from typing import Any

from app.db.db import conn_rw

STATE_TABLE = "episode_engine_state"


def get_state(key: str) -> dict[str, Any] | None:
    """Return the JSON value stored at ``key``, or ``None`` if absent."""
    with conn_rw() as conn:
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
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {STATE_TABLE} WHERE key = %s", (key,))


def all_state_with_prefix(prefix: str) -> dict[str, dict[str, Any]]:
    """Return every ``key -> value`` pair whose key starts with ``prefix``.

    Used to load every currently-open segment (``open_segment:``) at tick
    start without enumerating scopes ahead of time.
    """
    out: dict[str, dict[str, Any]] = {}
    with conn_rw() as conn:
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
    "all_state_with_prefix",
    "delete_state",
    "get_state",
    "set_state",
]
