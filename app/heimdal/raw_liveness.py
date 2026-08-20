"""Generation-aware raw-evidence liveness and response fencing.

This module is the authority for whether one exact ``heimraw:<record-id>``
generation is active, governed-erased, or unavailable.  It deliberately does
not infer erasure from absence: only an append-only deletion tombstone can
produce the erased state.

The same per-content fence is used by response-lease issuance, raw insertion,
and both retention writers.  PostgreSQL uses a transaction-scoped advisory
lock followed by the immutable generation row lock; memory uses one re-entrant
lock with the same ordering.  A governed deletion commits its deletion
receipt, tombstone, all representation deletes, and identity delete in one
transaction.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, Literal, Mapping, Optional
from uuid import UUID, uuid4

from app.heimdal._backend import resolve_heimdal_backend

_GENERATION_TABLE = "heimdal_raw_liveness_generation"
_TOMBSTONE_TABLE = "heimdal_raw_deletion_tombstone"
_LEASE_TABLE = "heimdal_raw_response_lease"
_DELETION_RECEIPT_TABLE = "heimdal_raw_deletion_receipt"
_RAW_REF_PREFIX = "heimraw:"
_RETENTION_GUARD_SETTING = "app.heimdal_retention_bypass"

RESPONSE_LEASE_SECONDS = 30

_MIGRATION_HINT = (
    "raw liveness is migration-owned: run 'alembic upgrade head' against this "
    "database. See revision c5d8a1e4f2b7."
)


class RawLivenessSchemaMissingError(RuntimeError):
    """The durable liveness authority is absent or structurally incomplete."""


class RawLivenessUnavailableError(RuntimeError):
    """No authoritative active/erased answer can be made for an exact raw ref."""


class RawEvidenceErasedError(RuntimeError):
    """The exact raw generation has a governed deletion tombstone."""

    def __init__(self, tombstone: "RawDeletionTombstone") -> None:
        self.tombstone = tombstone
        super().__init__(
            f"raw evidence {tombstone.raw_ref} generation {tombstone.generation} "
            "was governed-erased"
        )


@dataclass(frozen=True)
class RawLivenessGeneration:
    content_identity: str
    generation: int
    record_id: str
    raw_ref: str
    activated_at: datetime
    sequence: int


@dataclass(frozen=True)
class RawResponseLease:
    lease_id: str
    content_identity: str
    generation: int
    record_id: str
    raw_ref: str
    issued_at: datetime
    expires_at: datetime
    sequence: int

    def as_response_field(self) -> Dict[str, Any]:
        return {
            "lease_id": self.lease_id,
            "raw_ref": self.raw_ref,
            "liveness_generation": self.generation,
            "issued_at": _iso_timestamp(self.issued_at),
            "expires_at": _iso_timestamp(self.expires_at),
        }


@dataclass(frozen=True)
class DeletionReceipt:
    id: str
    record_id: str
    content_identity: str
    reason: str
    retention_window_days: int
    deleted_at: datetime
    payload: Dict[str, Any]
    sequence: int
    receipted: bool = True


@dataclass(frozen=True)
class RawDeletionTombstone:
    id: str
    content_identity: str
    generation: int
    record_id: str
    raw_ref: str
    deletion_receipt_id: str
    reason: str
    erased_at: datetime
    sequence: int


@dataclass(frozen=True)
class RawLivenessProjection:
    outcome: Literal["active", "erased"]
    generation: RawLivenessGeneration
    response_lease: Optional[RawResponseLease] = None
    tombstone: Optional[RawDeletionTombstone] = None


@dataclass(frozen=True)
class GovernedDeletionResult:
    outcome: Literal["deleted", "lease_valid", "already_erased"]
    receipt: Optional[DeletionReceipt] = None
    tombstone: Optional[RawDeletionTombstone] = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso_timestamp(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _record_id_from_raw_ref(raw_ref: str) -> str:
    if not isinstance(raw_ref, str) or not raw_ref.startswith(_RAW_REF_PREFIX):
        raise RawLivenessUnavailableError(f"invalid raw reference {raw_ref!r}")
    record_id = raw_ref[len(_RAW_REF_PREFIX) :]
    try:
        return str(UUID(record_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise RawLivenessUnavailableError(f"invalid raw reference {raw_ref!r}") from exc


def raw_ref_for_record_id(record_id: str) -> str:
    return f"{_RAW_REF_PREFIX}{record_id}"


_MEMORY_FENCE = threading.RLock()


class _MemoryAuthority:
    def __init__(self) -> None:
        self.generations_by_record: Dict[str, RawLivenessGeneration] = {}
        self.generations_by_content: Dict[str, list[RawLivenessGeneration]] = {}
        self.tombstones_by_record: Dict[str, RawDeletionTombstone] = {}
        self.leases: list[RawResponseLease] = []
        self.deletion_receipts: list[DeletionReceipt] = []
        self.tombstones: list[RawDeletionTombstone] = []


_MEMORY = _MemoryAuthority()


def memory_fence() -> threading.RLock:
    """Return the shared memory liveness fence for raw-store lock ordering."""

    return _MEMORY_FENCE


def register_memory_generation(
    *, record_id: str, content_identity: str, activated_at: datetime
) -> RawLivenessGeneration:
    """Append or validate one active memory generation under the shared fence."""

    with _MEMORY_FENCE:
        existing = _MEMORY.generations_by_record.get(record_id)
        if existing is not None:
            if (
                existing.content_identity != content_identity
                or existing.raw_ref != raw_ref_for_record_id(record_id)
                or record_id in _MEMORY.tombstones_by_record
            ):
                raise RawLivenessUnavailableError(
                    "raw generation replay does not match active liveness authority"
                )
            return existing
        prior = _MEMORY.generations_by_content.get(content_identity, [])
        if any(item.record_id not in _MEMORY.tombstones_by_record for item in prior):
            raise RawLivenessUnavailableError(
                "content identity already has a different untombstoned generation"
            )
        generation = RawLivenessGeneration(
            content_identity=content_identity,
            generation=(max((item.generation for item in prior), default=0) + 1),
            record_id=record_id,
            raw_ref=raw_ref_for_record_id(record_id),
            activated_at=_as_utc(activated_at),
            sequence=sum(len(items) for items in _MEMORY.generations_by_content.values()),
        )
        _MEMORY.generations_by_record[record_id] = generation
        _MEMORY.generations_by_content.setdefault(content_identity, []).append(generation)
        return generation


def assert_memory_generation_active(
    *, record_id: str, content_identity: str
) -> RawLivenessGeneration:
    with _MEMORY_FENCE:
        generation = _MEMORY.generations_by_record.get(record_id)
        if generation is None or generation.content_identity != content_identity:
            raise RawLivenessUnavailableError(
                "raw identity has no matching durable liveness generation"
            )
        tombstone = _MEMORY.tombstones_by_record.get(record_id)
        if tombstone is not None:
            raise RawEvidenceErasedError(tombstone)
        return generation


def _memory_raw_is_exact_active(generation: RawLivenessGeneration) -> bool:
    from app.heimdal import raw_store

    return raw_store._MEMORY_STORE.validate_exact_active(  # noqa: SLF001
        generation.record_id, generation.content_identity
    )


def _memory_projection_locked(
    *, raw_ref: str, content_identity: str, issued_at: datetime
) -> RawLivenessProjection:
    record_id = _record_id_from_raw_ref(raw_ref)
    generation = _MEMORY.generations_by_record.get(record_id)
    if (
        generation is None
        or generation.content_identity != content_identity
        or generation.raw_ref != raw_ref
    ):
        raise RawLivenessUnavailableError(
            "receipt raw ref has no matching durable liveness generation"
        )
    tombstone = _MEMORY.tombstones_by_record.get(record_id)
    raw_active = _memory_raw_is_exact_active(generation)
    if tombstone is not None:
        if raw_active:
            raise RawLivenessUnavailableError(
                "tombstoned raw generation still has an active representation"
            )
        return RawLivenessProjection(
            outcome="erased", generation=generation, tombstone=tombstone
        )
    if not raw_active:
        raise RawLivenessUnavailableError(
            "untombstoned raw generation is missing its exact active representation"
        )
    lease = RawResponseLease(
        lease_id=str(uuid4()),
        content_identity=content_identity,
        generation=generation.generation,
        record_id=record_id,
        raw_ref=raw_ref,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(seconds=RESPONSE_LEASE_SECONDS),
        sequence=len(_MEMORY.leases),
    )
    _MEMORY.leases.append(lease)
    _response_lease_stage_hook("after_lease_append")
    return RawLivenessProjection(
        outcome="active", generation=generation, response_lease=lease
    )


def _pg_connect(*, autocommit: bool = False) -> Any:
    import psycopg

    from app.db.dsn import resolve_dsn

    url = os.environ.get("DATABASE_URL") or os.environ.get("DB_DSN")
    if not url:
        raise RuntimeError("DATABASE_URL or DB_DSN not set")
    return psycopg.connect(resolve_dsn(url), autocommit=autocommit)


def _schema_autocreate_enabled() -> bool:
    return (os.environ.get("STORE_SCHEMA_AUTOCREATE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _assert_pg_schema(conn: Any) -> None:
    cur = conn.cursor()
    tables = (
        _GENERATION_TABLE,
        _TOMBSTONE_TABLE,
        _LEASE_TABLE,
        _DELETION_RECEIPT_TABLE,
    )
    cur.execute("SELECT " + ", ".join("to_regclass(%s)" for _ in tables), tables)
    row = cur.fetchone()
    if not row or not all(row):
        raise RawLivenessSchemaMissingError(
            "Missing raw-liveness/deletion authority table. " + _MIGRATION_HINT
        )
    required: Mapping[str, set[str]] = {
        _GENERATION_TABLE: {
            "content_identity",
            "generation",
            "record_id",
            "raw_ref",
            "activated_at",
            "sequence",
        },
        _TOMBSTONE_TABLE: {
            "id",
            "content_identity",
            "generation",
            "record_id",
            "raw_ref",
            "deletion_receipt_id",
            "reason",
            "erased_at",
            "sequence",
        },
        _LEASE_TABLE: {
            "lease_id",
            "content_identity",
            "generation",
            "record_id",
            "raw_ref",
            "issued_at",
            "expires_at",
            "sequence",
        },
        _DELETION_RECEIPT_TABLE: {
            "id",
            "record_id",
            "content_identity",
            "reason",
            "retention_window_days",
            "deleted_at",
            "payload",
            "sequence",
        },
    }
    cur.execute(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = ANY(%s)
        """,
        (list(tables),),
    )
    actual: Dict[str, set[str]] = {table: set() for table in tables}
    for table_name, column_name in cur.fetchall():
        actual[str(table_name)].add(str(column_name))
    if any(not columns.issubset(actual[table]) for table, columns in required.items()):
        raise RawLivenessSchemaMissingError(
            "Raw-liveness/deletion columns do not match the migration-owned schema. "
            + _MIGRATION_HINT
        )
    cur.execute(
        """
        SELECT trigger_name
        FROM information_schema.triggers
        WHERE trigger_schema = current_schema()
          AND trigger_name IN (
              'heimdal_raw_liveness_generation_no_mutation',
              'heimdal_raw_deletion_tombstone_no_mutation',
              'heimdal_raw_response_lease_no_mutation',
              'heimdal_raw_deletion_receipt_no_update'
          )
        """
    )
    triggers = {str(item[0]) for item in cur.fetchall()}
    expected = {
        "heimdal_raw_liveness_generation_no_mutation",
        "heimdal_raw_deletion_tombstone_no_mutation",
        "heimdal_raw_response_lease_no_mutation",
        "heimdal_raw_deletion_receipt_no_update",
    }
    if triggers != expected:
        raise RawLivenessSchemaMissingError(
            "Raw-liveness append-only triggers are incomplete. " + _MIGRATION_HINT
        )
    cur.execute(
        f"""
        SELECT r.id
        FROM heimdal_raw_record AS r
        LEFT JOIN {_GENERATION_TABLE} AS g ON g.record_id = r.id
        LEFT JOIN {_TOMBSTONE_TABLE} AS t ON t.record_id = r.id
        GROUP BY r.id
        HAVING count(g.record_id) <> 1 OR count(t.record_id) <> 0
        LIMIT 1
        """
    )
    if cur.fetchone() is not None:
        raise RawLivenessSchemaMissingError(
            "Active raw identities are not covered by exactly one untombstoned "
            "liveness generation. "
            + _MIGRATION_HINT
        )


def _append_only_sql(function_name: str, table_name: str, trigger_name: str) -> tuple[str, str]:
    function = f"""
        CREATE OR REPLACE FUNCTION {function_name}()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '{table_name} is append-only: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
    """
    trigger = f"""
        CREATE TRIGGER {trigger_name}
        BEFORE UPDATE OR DELETE ON {table_name}
        FOR EACH ROW EXECUTE FUNCTION {function_name}()
    """
    return function, trigger


def _bootstrap_pg(conn: Any) -> None:
    if not _schema_autocreate_enabled():
        _assert_pg_schema(conn)
        return
    cur = conn.cursor()
    cur.execute(
        "SELECT to_regclass(%s), to_regclass(%s), to_regclass(%s)",
        (_GENERATION_TABLE, _TOMBSTONE_TABLE, _LEASE_TABLE),
    )
    existing = cur.fetchone()
    if existing and any(existing):
        _assert_pg_schema(conn)
        return
    cur.execute("SELECT count(*) FROM heimdal_raw_record")
    if int(cur.fetchone()[0]) != 0:
        raise RawLivenessSchemaMissingError(
            "Test autocreate refuses to invent liveness generations for existing raw rows. "
            + _MIGRATION_HINT
        )
    cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_DELETION_RECEIPT_TABLE} (
            id uuid PRIMARY KEY,
            record_id uuid NOT NULL,
            content_identity text NOT NULL,
            reason text NOT NULL,
            retention_window_days integer NOT NULL,
            deleted_at timestamptz NOT NULL,
            payload jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            sequence bigserial NOT NULL
        )
        """
    )
    cur.execute(
        f"CREATE INDEX IF NOT EXISTS heimdal_raw_deletion_receipt_seq_idx "
        f"ON {_DELETION_RECEIPT_TABLE} (sequence)"
    )
    cur.execute(
        f"CREATE INDEX IF NOT EXISTS heimdal_raw_deletion_receipt_record_id_idx "
        f"ON {_DELETION_RECEIPT_TABLE} (record_id)"
    )
    receipt_function, receipt_trigger = _append_only_sql(
        "heimdal_raw_deletion_receipt_reject_mutation",
        _DELETION_RECEIPT_TABLE,
        "heimdal_raw_deletion_receipt_no_update",
    )
    cur.execute(receipt_function)
    cur.execute(
        f"DROP TRIGGER IF EXISTS heimdal_raw_deletion_receipt_no_update "
        f"ON {_DELETION_RECEIPT_TABLE}"
    )
    cur.execute(receipt_trigger)
    cur.execute(
        f"""
        CREATE TABLE {_GENERATION_TABLE} (
            content_identity text NOT NULL,
            generation integer NOT NULL CHECK (generation > 0),
            record_id uuid NOT NULL UNIQUE,
            raw_ref text NOT NULL UNIQUE CHECK (raw_ref LIKE '{_RAW_REF_PREFIX}%'),
            activated_at timestamptz NOT NULL,
            sequence bigserial NOT NULL,
            PRIMARY KEY (content_identity, generation)
        )
        """
    )
    cur.execute(
        f"CREATE INDEX heimdal_raw_liveness_generation_record_idx "
        f"ON {_GENERATION_TABLE} (record_id)"
    )
    cur.execute(
        f"""
        CREATE TABLE {_TOMBSTONE_TABLE} (
            id uuid PRIMARY KEY,
            content_identity text NOT NULL,
            generation integer NOT NULL,
            record_id uuid NOT NULL UNIQUE,
            raw_ref text NOT NULL UNIQUE,
            deletion_receipt_id uuid NOT NULL UNIQUE
                REFERENCES {_DELETION_RECEIPT_TABLE}(id) ON DELETE RESTRICT,
            reason text NOT NULL,
            erased_at timestamptz NOT NULL,
            sequence bigserial NOT NULL,
            FOREIGN KEY (content_identity, generation)
                REFERENCES {_GENERATION_TABLE}(content_identity, generation)
                ON DELETE RESTRICT
        )
        """
    )
    cur.execute(
        f"CREATE INDEX heimdal_raw_deletion_tombstone_identity_idx "
        f"ON {_TOMBSTONE_TABLE} (content_identity, generation)"
    )
    cur.execute(
        f"""
        CREATE TABLE {_LEASE_TABLE} (
            lease_id uuid PRIMARY KEY,
            content_identity text NOT NULL,
            generation integer NOT NULL,
            record_id uuid NOT NULL,
            raw_ref text NOT NULL,
            issued_at timestamptz NOT NULL,
            expires_at timestamptz NOT NULL CHECK (expires_at > issued_at),
            sequence bigserial NOT NULL,
            FOREIGN KEY (content_identity, generation)
                REFERENCES {_GENERATION_TABLE}(content_identity, generation)
                ON DELETE RESTRICT
        )
        """
    )
    cur.execute(
        f"CREATE INDEX heimdal_raw_response_lease_active_idx "
        f"ON {_LEASE_TABLE} (record_id, expires_at)"
    )
    for function_name, table_name, trigger_name in (
        (
            "heimdal_raw_liveness_generation_reject_mutation",
            _GENERATION_TABLE,
            "heimdal_raw_liveness_generation_no_mutation",
        ),
        (
            "heimdal_raw_deletion_tombstone_reject_mutation",
            _TOMBSTONE_TABLE,
            "heimdal_raw_deletion_tombstone_no_mutation",
        ),
        (
            "heimdal_raw_response_lease_reject_mutation",
            _LEASE_TABLE,
            "heimdal_raw_response_lease_no_mutation",
        ),
    ):
        function, trigger = _append_only_sql(function_name, table_name, trigger_name)
        cur.execute(function)
        cur.execute(trigger)
    cur.execute(
        f"""
        CREATE OR REPLACE FUNCTION heimdal_raw_record_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE'
               AND current_setting('{_RETENTION_GUARD_SETTING}', true) = 'true'
               AND EXISTS (
                   SELECT 1 FROM {_TOMBSTONE_TABLE} WHERE record_id = OLD.id
               ) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'heimdal_raw_record is append-only: % is not permitted '
                'outside the governed tombstone transaction', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    cur.execute(
        f"""
        CREATE OR REPLACE FUNCTION heimdal_raw_representation_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND current_setting('app.heimdal_representation_activation', true) = 'true'
               AND NEW.id IS NOT DISTINCT FROM OLD.id
               AND NEW.record_id IS NOT DISTINCT FROM OLD.record_id
               AND NEW.storage_kind IS NOT DISTINCT FROM OLD.storage_kind
               AND NEW.location_ref IS NOT DISTINCT FROM OLD.location_ref
               AND NEW.ciphertext IS NOT DISTINCT FROM OLD.ciphertext
               AND NEW.nonce IS NOT DISTINCT FROM OLD.nonce
               AND NEW.key_ref IS NOT DISTINCT FROM OLD.key_ref
               AND NEW.registered_at IS NOT DISTINCT FROM OLD.registered_at
               AND NEW.sequence IS NOT DISTINCT FROM OLD.sequence THEN
                RETURN NEW;
            END IF;
            IF TG_OP = 'DELETE'
               AND current_setting('{_RETENTION_GUARD_SETTING}', true) = 'true'
               AND EXISTS (
                   SELECT 1 FROM {_TOMBSTONE_TABLE} WHERE record_id = OLD.record_id
               ) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION
                'heimdal_raw_representation mutation is governed: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    _assert_pg_schema(conn)


def acquire_pg_fence(cur: Any, content_identity: str) -> None:
    """Acquire the shared transaction fence before any generation-row lock."""

    cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (content_identity,))


def register_pg_generation(
    cur: Any,
    *,
    record_id: str,
    content_identity: str,
    activated_at: datetime,
) -> RawLivenessGeneration:
    """Append one generation in the caller's raw-insert transaction."""

    cur.execute(
        f"SELECT generation, record_id, raw_ref, activated_at, sequence "
        f"FROM {_GENERATION_TABLE} WHERE content_identity = %s "
        "ORDER BY generation DESC FOR UPDATE",
        (content_identity,),
    )
    prior_rows = cur.fetchall()
    for generation, prior_record_id, raw_ref, prior_activated_at, sequence in prior_rows:
        if str(prior_record_id) == record_id:
            cur.execute(
                f"SELECT 1 FROM {_TOMBSTONE_TABLE} WHERE record_id = %s", (record_id,)
            )
            if cur.fetchone() is not None:
                raise RawEvidenceErasedError(
                    _load_pg_tombstone(cur, record_id=record_id)
                )
            return RawLivenessGeneration(
                content_identity=content_identity,
                generation=int(generation),
                record_id=record_id,
                raw_ref=str(raw_ref),
                activated_at=prior_activated_at,
                sequence=int(sequence),
            )
    if prior_rows:
        cur.execute(
            f"""
            SELECT 1
            FROM {_GENERATION_TABLE} AS g
            LEFT JOIN {_TOMBSTONE_TABLE} AS t ON t.record_id = g.record_id
            WHERE g.content_identity = %s AND t.record_id IS NULL
            LIMIT 1
            """,
            (content_identity,),
        )
        if cur.fetchone() is not None:
            raise RawLivenessUnavailableError(
                "content identity already has a different untombstoned generation"
            )
    next_generation = max((int(row[0]) for row in prior_rows), default=0) + 1
    cur.execute(
        f"""
        INSERT INTO {_GENERATION_TABLE} (
            content_identity, generation, record_id, raw_ref, activated_at
        ) VALUES (%s, %s, %s, %s, %s)
        RETURNING sequence
        """,
        (
            content_identity,
            next_generation,
            record_id,
            raw_ref_for_record_id(record_id),
            _as_utc(activated_at),
        ),
    )
    sequence = int(cur.fetchone()[0])
    return RawLivenessGeneration(
        content_identity=content_identity,
        generation=next_generation,
        record_id=record_id,
        raw_ref=raw_ref_for_record_id(record_id),
        activated_at=_as_utc(activated_at),
        sequence=sequence,
    )


def assert_pg_generation_active(
    cur: Any, *, record_id: str, content_identity: str
) -> RawLivenessGeneration:
    cur.execute(
        f"""
        SELECT generation, raw_ref, activated_at, sequence
        FROM {_GENERATION_TABLE}
        WHERE record_id = %s AND content_identity = %s
        FOR UPDATE
        """,
        (record_id, content_identity),
    )
    row = cur.fetchone()
    if row is None:
        raise RawLivenessUnavailableError(
            "raw identity has no matching durable liveness generation"
        )
    cur.execute(f"SELECT 1 FROM {_TOMBSTONE_TABLE} WHERE record_id = %s", (record_id,))
    if cur.fetchone() is not None:
        raise RawEvidenceErasedError(_load_pg_tombstone(cur, record_id=record_id))
    return RawLivenessGeneration(
        content_identity=content_identity,
        generation=int(row[0]),
        record_id=record_id,
        raw_ref=str(row[1]),
        activated_at=row[2],
        sequence=int(row[3]),
    )


def _load_pg_generation(cur: Any, *, record_id: str) -> Optional[RawLivenessGeneration]:
    cur.execute(
        f"""
        SELECT content_identity, generation, raw_ref, activated_at, sequence
        FROM {_GENERATION_TABLE}
        WHERE record_id = %s
        FOR UPDATE
        """,
        (record_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return RawLivenessGeneration(
        content_identity=str(row[0]),
        generation=int(row[1]),
        record_id=record_id,
        raw_ref=str(row[2]),
        activated_at=row[3],
        sequence=int(row[4]),
    )


def _load_pg_tombstone(cur: Any, *, record_id: str) -> RawDeletionTombstone:
    cur.execute(
        f"""
        SELECT id, content_identity, generation, raw_ref, deletion_receipt_id,
               reason, erased_at, sequence
        FROM {_TOMBSTONE_TABLE}
        WHERE record_id = %s
        """,
        (record_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise RawLivenessUnavailableError("expected governed deletion tombstone is absent")
    return RawDeletionTombstone(
        id=str(row[0]),
        content_identity=str(row[1]),
        generation=int(row[2]),
        record_id=record_id,
        raw_ref=str(row[3]),
        deletion_receipt_id=str(row[4]),
        reason=str(row[5]),
        erased_at=row[6],
        sequence=int(row[7]),
    )


def _pg_exact_active(cur: Any, generation: RawLivenessGeneration) -> bool:
    cur.execute(
        """
        SELECT count(*) FILTER (WHERE p.active),
               count(*) FILTER (
                   WHERE p.active
                     AND p.storage_kind = 'postgres_hot'
                     AND p.location_ref LIKE 'heimloc:%'
                     AND p.ciphertext IS NOT NULL
                     AND p.nonce IS NOT NULL
                     AND p.key_ref IS NOT NULL
               )
        FROM heimdal_raw_record AS r
        LEFT JOIN heimdal_raw_representation AS p ON p.record_id = r.id
        WHERE r.id = %s AND r.content_identity = %s
        GROUP BY r.id
        """,
        (generation.record_id, generation.content_identity),
    )
    row = cur.fetchone()
    return bool(row and int(row[0]) == 1 and int(row[1]) == 1)


def _pg_raw_exists(cur: Any, record_id: str) -> bool:
    cur.execute("SELECT 1 FROM heimdal_raw_record WHERE id = %s", (record_id,))
    return cur.fetchone() is not None


def project_with_response_leases(
    requests: Iterable[tuple[str, str]], *, now: Optional[datetime] = None
) -> Dict[str, RawLivenessProjection]:
    """Project exact liveness and issue one response lease per unique raw ref.

    The operation is all-or-nothing for a batch.  An unavailable item raises
    and no admitted response is produced; an erased item is returned only when
    its exact generation has a governed tombstone.
    """

    unique = sorted(set(requests), key=lambda item: (item[1], item[0]))
    issued_at = _as_utc(now or _utc_now())
    if not unique:
        return {}
    if resolve_heimdal_backend() == "memory":
        with _MEMORY_FENCE:
            lease_count = len(_MEMORY.leases)
            try:
                return {
                    raw_ref: _memory_projection_locked(
                        raw_ref=raw_ref,
                        content_identity=content_identity,
                        issued_at=issued_at,
                    )
                    for raw_ref, content_identity in unique
                }
            except Exception:
                del _MEMORY.leases[lease_count:]
                raise

    from app.heimdal import raw_store

    conn = _pg_connect(autocommit=False)
    try:
        raw_store._assert_pg_schema(conn)  # noqa: SLF001
        cur = conn.cursor()
        for content_identity in sorted({content for _, content in unique}):
            acquire_pg_fence(cur, content_identity)
        projections: Dict[str, RawLivenessProjection] = {}
        for raw_ref, content_identity in unique:
            record_id = _record_id_from_raw_ref(raw_ref)
            generation = _load_pg_generation(cur, record_id=record_id)
            if (
                generation is None
                or generation.content_identity != content_identity
                or generation.raw_ref != raw_ref
            ):
                raise RawLivenessUnavailableError(
                    "receipt raw ref has no matching durable liveness generation"
                )
            cur.execute(
                f"SELECT 1 FROM {_TOMBSTONE_TABLE} WHERE record_id = %s", (record_id,)
            )
            tombstoned = cur.fetchone() is not None
            raw_active = _pg_exact_active(cur, generation)
            if tombstoned:
                if _pg_raw_exists(cur, record_id):
                    raise RawLivenessUnavailableError(
                        "tombstoned raw generation still has durable raw state"
                    )
                tombstone = _load_pg_tombstone(cur, record_id=record_id)
                projections[raw_ref] = RawLivenessProjection(
                    outcome="erased", generation=generation, tombstone=tombstone
                )
                continue
            if not raw_active:
                raise RawLivenessUnavailableError(
                    "untombstoned raw generation is missing its exact active representation"
                )
            lease_id = str(uuid4())
            expires_at = issued_at + timedelta(seconds=RESPONSE_LEASE_SECONDS)
            cur.execute(
                f"""
                INSERT INTO {_LEASE_TABLE} (
                    lease_id, content_identity, generation, record_id, raw_ref,
                    issued_at, expires_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING sequence
                """,
                (
                    lease_id,
                    content_identity,
                    generation.generation,
                    record_id,
                    raw_ref,
                    issued_at,
                    expires_at,
                ),
            )
            lease = RawResponseLease(
                lease_id=lease_id,
                content_identity=content_identity,
                generation=generation.generation,
                record_id=record_id,
                raw_ref=raw_ref,
                issued_at=issued_at,
                expires_at=expires_at,
                sequence=int(cur.fetchone()[0]),
            )
            projections[raw_ref] = RawLivenessProjection(
                outcome="active", generation=generation, response_lease=lease
            )
        _response_lease_stage_hook("after_lease_append")
        conn.commit()
        return projections
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def issue_response_lease(
    *, raw_ref: str, content_identity: str, now: Optional[datetime] = None
) -> RawResponseLease:
    projection = project_with_response_leases([(raw_ref, content_identity)], now=now)[raw_ref]
    if projection.outcome == "erased":
        assert projection.tombstone is not None
        raise RawEvidenceErasedError(projection.tombstone)
    if projection.response_lease is None:
        raise RawLivenessUnavailableError("active liveness projection has no response lease")
    return projection.response_lease


def _new_receipt(
    *,
    record_id: str,
    content_identity: str,
    reason: str,
    retention_window_days: int,
    deleted_at: datetime,
    payload: Mapping[str, Any],
    sequence: int,
) -> DeletionReceipt:
    return DeletionReceipt(
        id=str(uuid4()),
        record_id=record_id,
        content_identity=content_identity,
        reason=reason,
        retention_window_days=retention_window_days,
        deleted_at=_as_utc(deleted_at),
        payload=dict(payload),
        sequence=sequence,
    )


def _governed_delete_memory(
    *,
    record_id: str,
    reason: str,
    retention_window_days: int,
    deleted_at: datetime,
    payload: Mapping[str, Any],
) -> GovernedDeletionResult:
    from app.heimdal import raw_store

    _retention_fence_hook(record_id)
    with _MEMORY_FENCE:
        generation = _MEMORY.generations_by_record.get(record_id)
        if generation is None:
            raise RawLivenessUnavailableError(
                "retention target has no durable liveness generation"
            )
        existing_tombstone = _MEMORY.tombstones_by_record.get(record_id)
        raw_active = _memory_raw_is_exact_active(generation)
        if existing_tombstone is not None:
            if raw_active:
                raise RawLivenessUnavailableError(
                    "tombstoned retention target still has active raw state"
                )
            return GovernedDeletionResult(
                outcome="already_erased", tombstone=existing_tombstone
            )
        if not raw_active:
            raise RawLivenessUnavailableError(
                "untombstoned retention target is missing its active representation"
            )
        reference_time = _as_utc(deleted_at)
        if any(
            lease.record_id == record_id and lease.expires_at > reference_time
            for lease in _MEMORY.leases
        ):
            return GovernedDeletionResult(outcome="lease_valid")

        receipt = _new_receipt(
            record_id=record_id,
            content_identity=generation.content_identity,
            reason=reason,
            retention_window_days=retention_window_days,
            deleted_at=reference_time,
            payload=payload,
            sequence=len(_MEMORY.deletion_receipts),
        )
        tombstone = RawDeletionTombstone(
            id=str(uuid4()),
            content_identity=generation.content_identity,
            generation=generation.generation,
            record_id=record_id,
            raw_ref=generation.raw_ref,
            deletion_receipt_id=receipt.id,
            reason=reason,
            erased_at=reference_time,
            sequence=len(_MEMORY.tombstones),
        )
        raw_snapshot = raw_store._MEMORY_STORE.snapshot_state()  # noqa: SLF001
        _MEMORY.deletion_receipts.append(receipt)
        try:
            _retention_stage_hook("after_deletion_receipt")
            _MEMORY.tombstones.append(tombstone)
            _MEMORY.tombstones_by_record[record_id] = tombstone
            _retention_stage_hook("after_tombstone")
            if not raw_store._MEMORY_STORE.hard_delete(record_id):  # noqa: SLF001
                raise RawLivenessUnavailableError(
                    "retention target disappeared without a governed tombstone commit"
                )
            _retention_stage_hook("after_raw_delete")
        except Exception:
            raw_store._MEMORY_STORE.restore_state(raw_snapshot)  # noqa: SLF001
            if _MEMORY.deletion_receipts and _MEMORY.deletion_receipts[-1] == receipt:
                _MEMORY.deletion_receipts.pop()
            if _MEMORY.tombstones and _MEMORY.tombstones[-1] == tombstone:
                _MEMORY.tombstones.pop()
            _MEMORY.tombstones_by_record.pop(record_id, None)
            raise
        return GovernedDeletionResult(
            outcome="deleted", receipt=receipt, tombstone=tombstone
        )


_DELETION_RECEIPT_COLUMNS = (
    "id, record_id, content_identity, reason, retention_window_days, "
    "deleted_at, payload, sequence"
)


def _deletion_receipt_from_row(row: tuple[Any, ...]) -> DeletionReceipt:
    payload = row[6] if isinstance(row[6], dict) else json.loads(row[6] or "{}")
    return DeletionReceipt(
        id=str(row[0]),
        record_id=str(row[1]),
        content_identity=str(row[2]),
        reason=str(row[3]),
        retention_window_days=int(row[4]),
        deleted_at=row[5],
        payload=dict(payload),
        sequence=int(row[7]),
    )


def _governed_delete_pg(
    *,
    record_id: str,
    reason: str,
    retention_window_days: int,
    deleted_at: datetime,
    payload: Mapping[str, Any],
) -> GovernedDeletionResult:
    from app.heimdal import raw_store

    conn = _pg_connect(autocommit=False)
    try:
        raw_store._assert_pg_schema(conn)  # noqa: SLF001
        cur = conn.cursor()
        cur.execute(
            f"SELECT content_identity FROM {_GENERATION_TABLE} WHERE record_id = %s",
            (record_id,),
        )
        identity_row = cur.fetchone()
        if identity_row is None:
            raise RawLivenessUnavailableError(
                "retention target has no durable liveness generation"
            )
        content_identity = str(identity_row[0])
        _retention_fence_hook(record_id)
        acquire_pg_fence(cur, content_identity)
        generation = _load_pg_generation(cur, record_id=record_id)
        assert generation is not None
        cur.execute(
            f"SELECT 1 FROM {_TOMBSTONE_TABLE} WHERE record_id = %s", (record_id,)
        )
        tombstoned = cur.fetchone() is not None
        raw_active = _pg_exact_active(cur, generation)
        if tombstoned:
            if _pg_raw_exists(cur, record_id):
                raise RawLivenessUnavailableError(
                    "tombstoned retention target still has durable raw state"
                )
            tombstone = _load_pg_tombstone(cur, record_id=record_id)
            conn.rollback()
            return GovernedDeletionResult(outcome="already_erased", tombstone=tombstone)
        if not raw_active:
            raise RawLivenessUnavailableError(
                "untombstoned retention target is missing its active representation"
            )
        reference_time = _as_utc(deleted_at)
        cur.execute(
            f"SELECT 1 FROM {_LEASE_TABLE} "
            "WHERE record_id = %s AND expires_at > %s LIMIT 1",
            (record_id, reference_time),
        )
        if cur.fetchone() is not None:
            conn.rollback()
            return GovernedDeletionResult(outcome="lease_valid")

        receipt_id = str(uuid4())
        cur.execute(
            f"""
            INSERT INTO {_DELETION_RECEIPT_TABLE} (
                id, record_id, content_identity, reason, retention_window_days,
                deleted_at, payload
            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING {_DELETION_RECEIPT_COLUMNS}
            """,
            (
                receipt_id,
                record_id,
                content_identity,
                reason,
                retention_window_days,
                reference_time,
                json.dumps(dict(payload)),
            ),
        )
        receipt = _deletion_receipt_from_row(cur.fetchone())
        _retention_stage_hook("after_deletion_receipt")
        tombstone_id = str(uuid4())
        cur.execute(
            f"""
            INSERT INTO {_TOMBSTONE_TABLE} (
                id, content_identity, generation, record_id, raw_ref,
                deletion_receipt_id, reason, erased_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING sequence
            """,
            (
                tombstone_id,
                content_identity,
                generation.generation,
                record_id,
                generation.raw_ref,
                receipt.id,
                reason,
                reference_time,
            ),
        )
        tombstone = RawDeletionTombstone(
            id=tombstone_id,
            content_identity=content_identity,
            generation=generation.generation,
            record_id=record_id,
            raw_ref=generation.raw_ref,
            deletion_receipt_id=receipt.id,
            reason=reason,
            erased_at=reference_time,
            sequence=int(cur.fetchone()[0]),
        )
        _retention_stage_hook("after_tombstone")
        cur.execute("SELECT set_config(%s, 'true', true)", (_RETENTION_GUARD_SETTING,))
        cur.execute("DELETE FROM heimdal_raw_representation WHERE record_id = %s", (record_id,))
        cur.execute(
            "SELECT 1 FROM heimdal_raw_representation WHERE record_id = %s LIMIT 1",
            (record_id,),
        )
        if cur.fetchone() is not None:
            raise RawLivenessUnavailableError(
                "registered representation remained after all-copy deletion"
            )
        cur.execute("DELETE FROM heimdal_raw_record WHERE id = %s", (record_id,))
        if cur.rowcount != 1:
            raise RawLivenessUnavailableError(
                "raw identity disappeared before governed deletion commit"
            )
        _retention_stage_hook("after_raw_delete")
        conn.commit()
        return GovernedDeletionResult(
            outcome="deleted", receipt=receipt, tombstone=tombstone
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def governed_delete_raw_record(
    *,
    record_id: str,
    reason: str,
    retention_window_days: int,
    deleted_at: datetime,
    payload: Optional[Mapping[str, Any]] = None,
) -> GovernedDeletionResult:
    """Apply the one fenced, receipted raw-erasure transaction."""

    if resolve_heimdal_backend() == "memory":
        return _governed_delete_memory(
            record_id=record_id,
            reason=reason,
            retention_window_days=retention_window_days,
            deleted_at=deleted_at,
            payload=dict(payload or {}),
        )
    return _governed_delete_pg(
        record_id=record_id,
        reason=reason,
        retention_window_days=retention_window_days,
        deleted_at=deleted_at,
        payload=dict(payload or {}),
    )


def all_deletion_receipts() -> list[DeletionReceipt]:
    if resolve_heimdal_backend() == "memory":
        with _MEMORY_FENCE:
            return list(_MEMORY.deletion_receipts)
    conn = _pg_connect(autocommit=True)
    try:
        _assert_pg_schema(conn)
        cur = conn.cursor()
        cur.execute(
            f"SELECT {_DELETION_RECEIPT_COLUMNS} "
            f"FROM {_DELETION_RECEIPT_TABLE} ORDER BY sequence"
        )
        return [_deletion_receipt_from_row(row) for row in cur.fetchall()]
    finally:
        conn.close()


def all_deletion_tombstones() -> list[RawDeletionTombstone]:
    if resolve_heimdal_backend() == "memory":
        with _MEMORY_FENCE:
            return list(_MEMORY.tombstones)
    conn = _pg_connect(autocommit=True)
    try:
        _assert_pg_schema(conn)
        cur = conn.cursor()
        cur.execute(
            f"SELECT record_id FROM {_TOMBSTONE_TABLE} ORDER BY sequence"
        )
        return [_load_pg_tombstone(cur, record_id=str(row[0])) for row in cur.fetchall()]
    finally:
        conn.close()


def reset_memory_raw_liveness() -> None:
    with _MEMORY_FENCE:
        _MEMORY.generations_by_record.clear()
        _MEMORY.generations_by_content.clear()
        _MEMORY.tombstones_by_record.clear()
        _MEMORY.leases.clear()
        _MEMORY.deletion_receipts.clear()
        _MEMORY.tombstones.clear()


def reset_memory_deletion_receipts() -> None:
    with _MEMORY_FENCE:
        _MEMORY.tombstones_by_record.clear()
        _MEMORY.deletion_receipts.clear()
        _MEMORY.tombstones.clear()
        _MEMORY.leases.clear()


_response_lease_stage_hook: Callable[[str], None] = lambda _stage: None
_retention_stage_hook: Callable[[str], None] = lambda _stage: None
_retention_fence_hook: Callable[[str], None] = lambda _record_id: None


__all__ = [
    "DeletionReceipt",
    "GovernedDeletionResult",
    "RESPONSE_LEASE_SECONDS",
    "RawDeletionTombstone",
    "RawEvidenceErasedError",
    "RawLivenessProjection",
    "RawLivenessSchemaMissingError",
    "RawLivenessUnavailableError",
    "RawResponseLease",
    "all_deletion_receipts",
    "all_deletion_tombstones",
    "governed_delete_raw_record",
    "issue_response_lease",
    "project_with_response_leases",
    "reset_memory_deletion_receipts",
]
