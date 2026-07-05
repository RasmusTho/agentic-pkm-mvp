"""Per-consumer cursor store for the Heimdal observation log (#3039).

FABLE_COMPANION §4.2: "each consumer (v1: exactly one, the Mimer projector)
owns a durable ``(consumer_id, cursor)`` position and polls forward. Replay =
rewind your own cursor; it cannot affect other consumers or the log."

Contract:

- Each ``consumer_id`` has its own cursor position (the next log ``sequence``
  it has not yet read). Advancing one consumer's cursor never reads or
  writes another consumer's row.
- A new, never-before-seen ``consumer_id`` starts at sequence 0 -- it can
  rebuild the full projection from event zero without any special
  bootstrap step.
- The cursor is a position, not a subscription: it is only ever moved
  forward explicitly by :func:`advance_cursor`. There is no cross-consumer
  coupling at any layer.

Backend selection mirrors ``app.heimdal.observation_log`` (dual-backend,
fail-loud resolution via ``app.heimdal._backend.resolve_heimdal_backend``).
"""

from __future__ import annotations

import os
import threading
from typing import Any, Dict

from app.heimdal._backend import resolve_heimdal_backend

_TABLE = "heimdal_observation_cursor"

_MIGRATION_HINT = (
    "heimdal_observation_cursor schema is migration-owned: run 'alembic upgrade head' "
    "against this database. See app/alembic/versions/ (HEIM observation log migration)."
)


class ObservationCursorSchemaMissingError(RuntimeError):
    """Raised when the Postgres backend is selected but the cursor table is absent."""


class _MemoryCursorStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cursors: Dict[str, int] = {}

    def get(self, consumer_id: str) -> int:
        with self._lock:
            return self._cursors.get(consumer_id, 0)

    def set(self, consumer_id: str, position: int) -> None:
        with self._lock:
            current = self._cursors.get(consumer_id, 0)
            self._cursors[consumer_id] = max(current, position)

    def clear(self) -> None:
        with self._lock:
            self._cursors.clear()


_MEMORY_CURSORS = _MemoryCursorStore()


def reset_memory_cursor_store() -> None:
    """Test-only reset hook."""
    _MEMORY_CURSORS.clear()


def _pg_connect() -> Any:
    import psycopg

    from app.db.dsn import resolve_dsn

    url = os.environ.get("DATABASE_URL") or os.environ.get("DB_DSN")
    if not url:
        raise RuntimeError("DATABASE_URL or DB_DSN not set")
    return psycopg.connect(resolve_dsn(url), autocommit=True)


def _schema_autocreate_enabled() -> bool:
    return (os.environ.get("STORE_SCHEMA_AUTOCREATE") or "").strip().lower() in {"1", "true", "yes"}


def _assert_pg_schema(conn: Any) -> None:
    cur = conn.cursor()
    cur.execute("SELECT to_regclass(%s)", (_TABLE,))
    row = cur.fetchone()
    oid = row[0] if row else None
    if not oid:
        raise ObservationCursorSchemaMissingError(f"Missing table '{_TABLE}'. {_MIGRATION_HINT}")


def _bootstrap_pg(conn: Any) -> None:
    if not _schema_autocreate_enabled():
        _assert_pg_schema(conn)
        return
    cur = conn.cursor()
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            consumer_id text PRIMARY KEY,
            position bigint NOT NULL DEFAULT 0,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


class _PgCursorStore:
    def __init__(self) -> None:
        conn = _pg_connect()
        try:
            _bootstrap_pg(conn)
        finally:
            conn.close()

    def get(self, consumer_id: str) -> int:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(f"SELECT position FROM {_TABLE} WHERE consumer_id = %s", (consumer_id,))
            row = cur.fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()

    def set(self, consumer_id: str, position: int) -> None:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            # GREATEST(...) guards against a stale/out-of-order caller moving
            # a cursor backwards -- advancing is monotone by construction.
            cur.execute(
                f"""
                INSERT INTO {_TABLE} (consumer_id, position, updated_at)
                VALUES (%s, %s, now())
                ON CONFLICT (consumer_id) DO UPDATE
                SET position = GREATEST({_TABLE}.position, EXCLUDED.position),
                    updated_at = now()
                """,
                (consumer_id, position),
            )
        finally:
            conn.close()


def _backend() -> "_MemoryCursorStore | _PgCursorStore":
    if resolve_heimdal_backend() == "pg":
        return _PgCursorStore()
    return _MEMORY_CURSORS


def get_cursor(consumer_id: str) -> int:
    """Return ``consumer_id``'s current cursor position (next unread sequence).

    A consumer that has never been seen before returns ``0`` -- it can
    always rebuild from event zero.
    """
    if not isinstance(consumer_id, str) or not consumer_id.strip():
        raise ValueError(f"get_cursor requires a non-empty consumer_id, got {consumer_id!r}")
    return _backend().get(consumer_id)


def advance_cursor(consumer_id: str, position: int) -> None:
    """Move ``consumer_id``'s cursor forward to ``position``.

    Monotone: moving to a position behind the current one is a no-op (never
    silently rewinds -- explicit rewind for replay is a separate, deliberate
    operation this module does not expose in v1, per FABLE_COMPANION §4.2's
    "replay = rewind your own cursor" being consumer-initiated policy, not a
    log/cursor-store mechanism this slice builds).
    """
    if not isinstance(consumer_id, str) or not consumer_id.strip():
        raise ValueError(f"advance_cursor requires a non-empty consumer_id, got {consumer_id!r}")
    if position < 0:
        raise ValueError(f"position must be >= 0, got {position}")
    _backend().set(consumer_id, position)


__all__ = [
    "ObservationCursorSchemaMissingError",
    "advance_cursor",
    "get_cursor",
    "reset_memory_cursor_store",
]
