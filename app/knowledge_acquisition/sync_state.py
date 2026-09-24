"""YSS-06 (#3921): durable scheduler state and the single-runner lease.

One small migration-owned key/value table, ``youtube_sync_state``, holding the
rows the sync tick needs to survive a restart. It follows
``app/episodes/engine_state.py``'s shape rather than inventing a second
pattern: generic key, JSON value, fail-loud schema preflight, no autocreate.

Row families:

- ``lease:youtube_sync`` — the single-runner lease (INV-YSS-6). Both the
  watcher sub-tick and any CLI-invoked run claim this one key, so an operator
  running "sync now" during a scheduled tick cannot double-enqueue. A lease
  past its expiry is taken over rather than honoured forever: the previous
  holder may simply have been killed.
- ``backoff:<binding_id>`` — consecutive poll failures per source. Kept here
  instead of in the registry row's ``last_error`` because that field is YSS-01's
  contract shape, not scheduler bookkeeping.
- ``last_tick`` — the heartbeat and per-tick counters YSS-09 will project.
  Consumers derive ``runner_offline`` from this row's staleness; the runner
  never self-reports being up, because a dead runner cannot.

The memory backend exists for the ``not_pg`` lane and is explicitly volatile;
``for_runtime`` resolves Postgres and fails loud rather than silently handing
back a volatile store that would let two runners both believe they hold the
lease.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

TABLE_NAME = "youtube_sync_state"

_MIGRATION_HINT = (
    f"table {TABLE_NAME!r} is missing; run `alembic upgrade head` "
    "(schema is migration-owned, there is no autocreate path)"
)


class SyncLeaseLostError(RuntimeError):
    """A discovery writer lost its durable lease; no further writes are allowed."""


class SyncStateSchemaMissingError(RuntimeError):
    """Raised when the migration-owned table is absent."""


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _column(row: Any, name: str) -> Any:
    """Read one column from a row whose factory may be dict or tuple shaped.

    ``app.db.db.conn_rw`` binds ``row_factory=dict_row``, so ``fetchone()``
    returns a mapping keyed by column name -- while the sibling KA stores use
    their own tuple-row connection. Indexing a dict row positionally raises
    ``KeyError(0)`` with the table fully present, which is exactly the failure
    an earlier revision of this module shipped: every tick died in the schema
    preflight and surfaced only as ``error: \"0\"``. Both shapes are handled
    here, the same way ``app/episodes/engine_state.py`` and ``app/db/db.py``
    already do.
    """
    return row[name] if isinstance(row, dict) else row[0]


class MemorySyncStateStore:
    """Volatile store for the ``not_pg`` lane and in-process tests."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._rows: dict[str, dict[str, Any]] = {}

    # -- lease ---------------------------------------------------------------

    def acquire_lease(
        self, *, key: str, holder: str, ttl_seconds: int, now: datetime
    ) -> bool:
        moment = _utc(now)
        with self._lock:
            current = self._rows.get(key)
            if current is not None:
                expires_at = datetime.fromisoformat(current["expires_at"])
                if current["holder"] != holder and moment < expires_at:
                    return False
            self._rows[key] = {
                "holder": holder,
                "acquired_at": moment.isoformat(),
                "expires_at": (moment + timedelta(seconds=ttl_seconds)).isoformat(),
            }
            return True

    def heartbeat_lease(
        self, *, key: str, holder: str, ttl_seconds: int, now: datetime
    ) -> bool:
        moment = _utc(now)
        with self._lock:
            current = self._rows.get(key)
            if current is None or current["holder"] != holder:
                return False
            current["expires_at"] = (moment + timedelta(seconds=ttl_seconds)).isoformat()
            return True

    def release_lease(self, *, key: str, holder: str) -> None:
        with self._lock:
            current = self._rows.get(key)
            if current is not None and current["holder"] == holder:
                self._rows.pop(key, None)

    # -- key/value -----------------------------------------------------------

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._rows.get(key)
            return dict(row) if row is not None else None

    def set(self, key: str, value: Mapping[str, Any]) -> None:
        with self._lock:
            self._rows[key] = dict(value)

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()


class PostgresSyncStateStore:
    """Durable store. The lease is enforced by the row, not by the caller."""

    def __init__(self) -> None:
        self._assert_schema()

    @staticmethod
    def _assert_schema() -> None:
        from app.db.db import conn_rw

        with conn_rw() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT to_regclass(%s) AS present", (f"public.{TABLE_NAME}",)
            )
            row = cur.fetchone()
            if not row or _column(row, "present") is None:
                raise SyncStateSchemaMissingError(_MIGRATION_HINT)

    def acquire_lease(
        self, *, key: str, holder: str, ttl_seconds: int, now: datetime
    ) -> bool:
        from app.db.db import conn_rw

        moment = _utc(now)
        expires_at = moment + timedelta(seconds=ttl_seconds)
        payload = json.dumps(
            {
                "holder": holder,
                "acquired_at": moment.isoformat(),
                "expires_at": expires_at.isoformat(),
            }
        )
        # One statement decides it: insert when free, or steal only when the
        # current holder is us or the lease has already expired. Two runners
        # racing therefore cannot both observe success.
        with conn_rw() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {TABLE_NAME} (key, value, updated_at)
                VALUES (%s, %s::jsonb, %s)
                ON CONFLICT (key) DO UPDATE
                   SET value = EXCLUDED.value,
                       updated_at = EXCLUDED.updated_at
                 WHERE {TABLE_NAME}.value ->> 'holder' = %s
                    OR ({TABLE_NAME}.value ->> 'expires_at')::timestamptz <= %s
                RETURNING key
                """,
                (key, payload, moment, holder, moment),
            )
            return cur.fetchone() is not None

    def heartbeat_lease(
        self, *, key: str, holder: str, ttl_seconds: int, now: datetime
    ) -> bool:
        from app.db.db import conn_rw

        moment = _utc(now)
        expires_at = moment + timedelta(seconds=ttl_seconds)
        with conn_rw() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {TABLE_NAME}
                   SET value = jsonb_set(value, '{{expires_at}}', to_jsonb(%s::text)),
                       updated_at = %s
                 WHERE key = %s AND value ->> 'holder' = %s
                RETURNING key
                """,
                (expires_at.isoformat(), moment, key, holder),
            )
            return cur.fetchone() is not None

    def release_lease(self, *, key: str, holder: str) -> None:
        from app.db.db import conn_rw

        with conn_rw() as conn, conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {TABLE_NAME} WHERE key = %s AND value ->> 'holder' = %s",
                (key, holder),
            )

    def get(self, key: str) -> dict[str, Any] | None:
        from app.db.db import conn_rw

        with conn_rw() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT value FROM {TABLE_NAME} WHERE key = %s", (key,))
            row = cur.fetchone()
        if not row:
            return None
        value = _column(row, "value")
        if value is None:
            return None
        return value if isinstance(value, dict) else json.loads(value)

    def set(self, key: str, value: Mapping[str, Any]) -> None:
        from app.db.db import conn_rw

        with conn_rw() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {TABLE_NAME} (key, value, updated_at)
                VALUES (%s, %s::jsonb, %s)
                ON CONFLICT (key) DO UPDATE
                   SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
                """,
                (key, json.dumps(dict(value)), datetime.now(timezone.utc)),
            )


def for_runtime() -> PostgresSyncStateStore:
    """The production store. Never silently volatile: the lease depends on it."""
    return PostgresSyncStateStore()


__all__ = [
    "TABLE_NAME",
    "MemorySyncStateStore",
    "PostgresSyncStateStore",
    "SyncStateSchemaMissingError",
    "for_runtime",
]
