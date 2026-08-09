"""Heimdal observation log: the append-only Heimdal <-> Mimer seam (#3039).

Slice A2 of Epic #3019 (Heimdal v1). Ratified by ADR-0049 §1 (Heimdal owns
watch -> fetch -> transcribe -> attribute -> published event; Mimer owns
cognition from the handoff) and specified by
``docs/HEIMDAL/FABLE_COMPANION.md`` §4.2 (Heimdal-owned append-only log +
per-consumer cursors, DB-native, outbox-disciplined) and §1.2 (envelope
reuse; ``timestamp`` = emission time only).

Contract (HEIM-1, append-only truth):

- The log is insert-only. There is no update or delete API at any layer —
  the Python store exposes only :func:`append`, and the Postgres backend
  additionally enforces the invariant with a trigger that rejects UPDATE/
  DELETE at the database level (defense in depth: even a hand-written SQL
  statement against the table cannot rewrite history).
- Corrections and revisions are new rows. This module does not special-case
  them; a caller publishing a correction/revision simply appends another
  event whose payload carries ``supersedes``/``revision_of`` (FABLE_COMPANION
  §1.3/§3.5) -- the log itself has no opinion on payload shape (out of
  scope: event payload schema, that is A4 / §11#3).

This module does **not** fork or alter the existing DB outbox
(`app/services/outbox.py`) -- it reuses that module's envelope
(`OutboxEvent`/`make_outbox_event`) and idempotency-key discipline
(`derive_idempotency_key`) verbatim, generalizing the *pattern* to a
canonical multi-consumer log rather than a single-consumer work queue
(FABLE_COMPANION §4.1/§4.2, §4.3(a) explicitly rejects reusing the `outbox`
table directly for this purpose).

Backend selection mirrors the existing dual-backend store convention
(`app.stores.resolve_object_store_port`): ``STORE_BACKEND=memory`` (or no
Postgres DSN configured) uses an in-process append-only list; a resolvable
Postgres DSN uses the real ``heimdal_observation_log`` table. Backend
resolution is fail-loud (KERNEL-03 / I-S4 precedent) -- a configured-but-
unreachable Postgres never silently degrades to memory.

Alembic is the sole production owner of this table's attached indexes,
reject-mutation trigger, and trigger function. Runtime startup is SELECT-only
for a present table; the explicit test autocreate flag may create the complete
fixture shape only when the table is absent.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.db.attached_schema import (
    MigrationOwnedTrigger,
    assert_migration_owned_attached_objects,
)
from app.events.schema import OutboxEvent
from app.heimdal._backend import resolve_heimdal_backend

_TABLE = "heimdal_observation_log"

_MIGRATION_HINT = (
    "heimdal_observation_log schema is migration-owned: run 'alembic upgrade head' "
    "against this database. See app/alembic/versions/ (HEIM observation log migration)."
)


class ObservationLogSchemaMissingError(RuntimeError):
    """Raised when the Postgres backend is selected but the log table/columns are absent."""


class AppendOnlyViolationError(RuntimeError):
    """Raised when a caller attempts to mutate an existing observation row.

    Never raised by this module's own code paths (there is no update/delete
    API) -- it is raised when the Postgres backend surfaces the DB trigger's
    rejection of an UPDATE/DELETE statement issued outside this module (e.g.
    a hand-written migration or an ad hoc SQL client), so the violation is
    reported in the caller's own vocabulary instead of a raw driver error.
    """


@dataclass(frozen=True)
class ObservationRow:
    """One durable, immutable row in the Heimdal observation log."""

    id: str
    topic: str
    idempotency_key: str
    envelope: Dict[str, Any]
    created_at: datetime
    sequence: int


def _normalize_envelope(event: OutboxEvent | Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(event, OutboxEvent):
        return event.model_dump(mode="json", exclude_none=True)
    if isinstance(event, dict):
        return dict(event)
    raise TypeError(f"expected OutboxEvent or dict envelope, got {type(event)!r}")


class _MemoryObservationLog:
    """In-process append-only log. Test/dev backend; volatile by design."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: List[ObservationRow] = []
        self._keys: set[str] = set()

    def append(
        self, *, topic: str, idempotency_key: str, envelope: Dict[str, Any]
    ) -> Optional[ObservationRow]:
        with self._lock:
            if idempotency_key in self._keys:
                return None
            row = ObservationRow(
                id=idempotency_key,
                topic=topic,
                idempotency_key=idempotency_key,
                envelope=dict(envelope),
                created_at=datetime.now(timezone.utc),
                sequence=len(self._rows),
            )
            self._rows.append(row)
            self._keys.add(idempotency_key)
            return row

    def read_from(self, sequence: int, *, limit: int | None = None) -> List[ObservationRow]:
        with self._lock:
            rows = [r for r in self._rows if r.sequence >= sequence]
        rows.sort(key=lambda r: r.sequence)
        if limit is not None:
            rows = rows[:limit]
        return rows

    def count(self) -> int:
        with self._lock:
            return len(self._rows)

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()
            self._keys.clear()


_MEMORY_LOG = _MemoryObservationLog()


def reset_memory_observation_log() -> None:
    """Test-only reset hook, mirroring the other memory-backend reset helpers."""
    _MEMORY_LOG.clear()


def _pg_connect() -> Any:
    import psycopg

    from app.db.dsn import resolve_dsn

    url = os.environ.get("DATABASE_URL") or os.environ.get("DB_DSN")
    if not url:
        raise RuntimeError("DATABASE_URL or DB_DSN not set")
    return psycopg.connect(resolve_dsn(url), autocommit=True)


def _schema_autocreate_enabled() -> bool:
    """Explicit test-fixture opt-in, mirroring KERNEL-04/KERNEL-05 precedent.

    Production/runtime Postgres never auto-creates this table; only test
    environments set STORE_SCHEMA_AUTOCREATE=1 (tests/conftest.py).
    """
    return (os.environ.get("STORE_SCHEMA_AUTOCREATE") or "").strip().lower() in {"1", "true", "yes"}


def _assert_pg_schema(conn: Any) -> None:
    assert_migration_owned_attached_objects(
        conn,
        table=_TABLE,
        indexes=("heimdal_observation_log_seq_idx", "heimdal_observation_log_topic_idx"),
        trigger=MigrationOwnedTrigger(
            "heimdal_observation_log_no_update",
            "heimdal_observation_log_reject_mutation",
            ("TG_OP", "RAISE EXCEPTION"),
        ),
        error_type=ObservationLogSchemaMissingError,
        migration_hint=_MIGRATION_HINT,
    )


def _bootstrap_pg(conn: Any) -> None:
    cur = conn.cursor()
    if not _schema_autocreate_enabled():
        _assert_pg_schema(conn)
        return
    for table in (_TABLE,):
        cur.execute("SELECT to_regclass(%s) IS NOT NULL AS present", (table,))
        row = cur.fetchone()
        present = bool(row and (row.get("present") if isinstance(row, dict) else row[0]))
        if present:
            _assert_pg_schema(conn)
            continue
        cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_TABLE} (
                id uuid PRIMARY KEY,
                topic text NOT NULL,
                payload jsonb NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now(),
                sequence bigserial NOT NULL
            )
            """
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS heimdal_observation_log_seq_idx ON {_TABLE} (sequence)"
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS heimdal_observation_log_topic_idx ON {_TABLE} (topic)"
        )
        # Test-fixture parity only; Alembic owns the production trigger.
        cur.execute(
            """
            CREATE OR REPLACE FUNCTION heimdal_observation_log_reject_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'heimdal_observation_log is append-only (HEIM-1): % is not permitted', TG_OP;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        cur.execute(f"DROP TRIGGER IF EXISTS heimdal_observation_log_no_update ON {_TABLE}")
        cur.execute(
            f"""
            CREATE TRIGGER heimdal_observation_log_no_update
            BEFORE UPDATE OR DELETE ON {_TABLE}
            FOR EACH ROW EXECUTE FUNCTION heimdal_observation_log_reject_mutation()
            """
        )


class _PgObservationLog:
    """Postgres-backed append-only log; append-only enforced by DB trigger."""

    def __init__(self) -> None:
        conn = _pg_connect()
        try:
            _bootstrap_pg(conn)
        finally:
            conn.close()

    def append(
        self, *, topic: str, idempotency_key: str, envelope: Dict[str, Any]
    ) -> Optional[ObservationRow]:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"""
                INSERT INTO {_TABLE} (id, topic, payload, created_at)
                VALUES (%s, %s, %s::jsonb, now())
                ON CONFLICT (id) DO NOTHING
                RETURNING id, created_at, sequence
                """,
                (idempotency_key, topic, json.dumps(envelope)),
            )
            row = cur.fetchone()
            if row is None:
                return None
            row_id, created_at, sequence = row[0], row[1], row[2]
            return ObservationRow(
                id=str(row_id),
                topic=topic,
                idempotency_key=idempotency_key,
                envelope=dict(envelope),
                created_at=created_at,
                sequence=int(sequence),
            )
        finally:
            conn.close()

    def read_from(self, sequence: int, *, limit: int | None = None) -> List[ObservationRow]:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            sql = f"SELECT id, topic, payload, created_at, sequence FROM {_TABLE} WHERE sequence >= %s ORDER BY sequence ASC"
            params: tuple[Any, ...] = (sequence,)
            if limit is not None:
                sql += " LIMIT %s"
                params = (sequence, limit)
            cur.execute(sql, params)
            rows = cur.fetchall()
            out: List[ObservationRow] = []
            for row_id, topic, payload, created_at, seq in rows:
                envelope = payload if isinstance(payload, dict) else json.loads(payload)
                out.append(
                    ObservationRow(
                        id=str(row_id),
                        topic=str(topic),
                        idempotency_key=str(row_id),
                        envelope=envelope,
                        created_at=created_at,
                        sequence=int(seq),
                    )
                )
            return out
        finally:
            conn.close()

    def count(self) -> int:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(f"SELECT count(*) FROM {_TABLE}")
            row = cur.fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()


def _backend() -> "_MemoryObservationLog | _PgObservationLog":
    if resolve_heimdal_backend() == "pg":
        return _PgObservationLog()
    return _MEMORY_LOG


def append_observation(
    event: OutboxEvent | Dict[str, Any], *, idempotency_key: str
) -> Optional[ObservationRow]:
    """Append one observation event to the log.

    Idempotent by ``idempotency_key`` (derive with
    ``app.services.outbox.derive_idempotency_key``, per publish.py): a
    duplicate key returns ``None`` (no new row written -- mirrors
    ``write_outbox_event``'s ``ON CONFLICT DO NOTHING`` -> ``""`` convention,
    adapted to ``None`` since this store returns rows, not ids). A revision
    or correction must derive a **distinct** key (different content
    fingerprint) to produce a new row -- that discipline lives in
    ``publish.py``, not here.

    There is deliberately no ``update``/``delete`` function in this module.
    """
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise ValueError(
            f"append_observation requires a non-empty idempotency_key, got {idempotency_key!r}"
        )
    envelope = _normalize_envelope(event)
    topic = str(envelope.get("event") or envelope.get("event_type") or "")
    if not topic:
        raise ValueError("observation envelope is missing its topic ('event' field)")
    return _backend().append(topic=topic, idempotency_key=idempotency_key, envelope=envelope)


def read_observations_from(sequence: int, *, limit: int | None = None) -> List[ObservationRow]:
    """Read all observations at or after ``sequence``, in log order.

    Read-only. Consumers must use this function (or the cursor-scoped
    ``app.heimdal.cursor_store``/``app.heimdal.publish`` helpers built on it)
    -- never import a backend-specific store class directly, and never
    reach into the table with hand-written SQL, so the seam stays
    cursor-shaped (issue Constraints: "no direct DB imports across
    boundaries").
    """
    if sequence < 0:
        raise ValueError(f"sequence must be >= 0, got {sequence}")
    return _backend().read_from(sequence, limit=limit)


def count_observations() -> int:
    """Total row count in the log (diagnostic/test helper)."""
    return _backend().count()


__all__ = [
    "AppendOnlyViolationError",
    "ObservationLogSchemaMissingError",
    "ObservationRow",
    "append_observation",
    "count_observations",
    "read_observations_from",
    "reset_memory_observation_log",
]
