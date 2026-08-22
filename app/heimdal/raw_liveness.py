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
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, Literal, Mapping, Optional
from uuid import UUID, uuid4

from app.heimdal._backend import resolve_heimdal_backend

_GENERATION_TABLE = "heimdal_raw_liveness_generation"
_TOMBSTONE_TABLE = "heimdal_raw_deletion_tombstone"
_LEASE_TABLE = "heimdal_raw_response_lease"
_RETENTION_CLAIM_TABLE = "heimdal_raw_retention_claim"
_DELETION_RECEIPT_TABLE = "heimdal_raw_deletion_receipt"
_RAW_REF_PREFIX = "heimraw:"
_RETENTION_GUARD_SETTING = "app.heimdal_retention_bypass"
_RETENTION_RECONCILE_GUARD_SETTING = "app.heimdal_retention_reconcile"

RESPONSE_LEASE_SECONDS = 30

_MIGRATION_HINT = (
    "raw liveness is migration-owned: run 'alembic upgrade head' against this "
    "database. See revision c5d8a1e4f2b7."
)

_RECEIPT_TRIGGER_BODY = (
    "if tg_op = 'update' and current_setting('app.heimdal_retention_reconcile', true) = 'true' "
    "and new.id is not distinct from old.id and new.record_id is not distinct from old.record_id "
    "and new.content_identity is not distinct from old.content_identity and new.reason is not distinct from old.reason "
    "and new.retention_window_days is not distinct from old.retention_window_days "
    "and new.deleted_at is not distinct from old.deleted_at and new.sequence is not distinct from old.sequence "
    "and (new.payload - 'cold_cleanup_location_refs') is not distinct from (old.payload - 'cold_cleanup_location_refs') "
    "and heimdal_raw_cleanup_queue_is_subsequence( old.payload->'cold_cleanup_location_refs', new.payload->'cold_cleanup_location_refs' ) "
    "then return new; end if; raise exception 'heimdal_raw_deletion_receipt is append-only: % is not permitted', tg_op;"
)

_CLEANUP_QUEUE_HELPER_BODY = (
    "declare old_refs text[] := array( select jsonb_array_elements_text(coalesce(old_payload, '[]'::jsonb)) ); "
    "new_ref text; old_index integer := 1; old_length integer := coalesce(array_length(old_refs, 1), 0); "
    "begin for new_ref in select jsonb_array_elements_text(coalesce(new_payload, '[]'::jsonb)) loop "
    "while old_index <= old_length and old_refs[old_index] <> new_ref loop old_index := old_index + 1; end loop; "
    "if old_index > old_length then return false; end if; old_index := old_index + 1; end loop; "
    "return true; end;"
)


def _receipt_trigger_is_migration_ready(function_def: str, trigger_def: str) -> bool:
    """Accept only the canonical guarded-update/append-only trigger shape."""
    normalized = re.sub(r"\s+", " ", function_def).lower()
    normalized_trigger = re.sub(r"\s+", " ", trigger_def).lower()
    body_match = re.search(r"\bbegin\s+(.*?)\bend\s*;", normalized, re.IGNORECASE)
    body = body_match.group(1).strip() if body_match else ""
    return bool(
        body == _RECEIPT_TRIGGER_BODY
        and re.fullmatch(
            r"create trigger heimdal_raw_deletion_receipt_no_update "
            r"before delete or update on (?:[a-z_][a-z0-9_]*\.)?heimdal_raw_deletion_receipt "
            r"for each row execute function "
            r"(?:[a-z_][a-z0-9_]*\.)?heimdal_raw_deletion_receipt_reject_mutation\(\)",
            normalized_trigger,
        )
    )


def _cleanup_queue_helper_is_migration_ready(
    function_def: str, arguments: str, volatility: str, is_strict: bool
) -> bool:
    """Accept only the canonical order-preserving queue helper."""
    normalized = re.sub(r"\s+", " ", function_def).lower()
    body_match = re.search(r"\bdeclare\s+(.*?)\bend\s*;", normalized, re.IGNORECASE)
    body = body_match.group(0).strip() if body_match else ""
    return bool(
        arguments.strip().lower() == "old_payload jsonb, new_payload jsonb"
        and volatility == "i"
        and is_strict
        and body == _CLEANUP_QUEUE_HELPER_BODY
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
class RawRetentionClaim:
    id: str
    content_identity: str
    generation: int
    record_id: str
    raw_ref: str
    reason: str
    retention_window_days: int
    claimed_at: datetime
    drain_after: datetime
    payload: Dict[str, Any]
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
        self.retention_claims_by_record: Dict[str, RawRetentionClaim] = {}
        self.retention_claims: list[RawRetentionClaim] = []
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
    if record_id in _MEMORY.retention_claims_by_record:
        raise RawLivenessUnavailableError(
            "raw generation is retiring under a durable retention claim"
        )
    for existing_lease in reversed(_MEMORY.leases):
        if (
            existing_lease.record_id == record_id
            and existing_lease.generation == generation.generation
            and existing_lease.expires_at > issued_at
        ):
            return RawLivenessProjection(
                outcome="active", generation=generation, response_lease=existing_lease
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
        _RETENTION_CLAIM_TABLE,
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
        _RETENTION_CLAIM_TABLE: {
            "id",
            "content_identity",
            "generation",
            "record_id",
            "raw_ref",
            "reason",
            "retention_window_days",
            "claimed_at",
            "drain_after",
            "payload",
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
              'heimdal_raw_retention_claim_no_mutation',
              'heimdal_raw_response_lease_reject_retiring',
              'heimdal_raw_deletion_receipt_no_update'
          )
        """
    )
    triggers = {str(item[0]) for item in cur.fetchall()}
    expected = {
        "heimdal_raw_liveness_generation_no_mutation",
        "heimdal_raw_deletion_tombstone_no_mutation",
        "heimdal_raw_response_lease_no_mutation",
        "heimdal_raw_retention_claim_no_mutation",
        "heimdal_raw_response_lease_reject_retiring",
        "heimdal_raw_deletion_receipt_no_update",
    }
    if triggers != expected:
        raise RawLivenessSchemaMissingError(
            "Raw-liveness append-only triggers are incomplete. " + _MIGRATION_HINT
        )
    # The trigger must remain bound to both mutation events, while the function
    # must admit exactly the guarded UPDATE path and reject everything else.
    # Normalize PostgreSQL's pretty-printed body before checking the complete
    # control-flow shape; independent token presence is insufficient here.
    cur.execute(
        """
        SELECT pg_get_functiondef(t.tgfoid), pg_get_triggerdef(t.oid)
        FROM pg_trigger AS t
        JOIN pg_class AS c ON c.oid = t.tgrelid
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = current_schema()
          AND c.relname = %s
          AND t.tgname = 'heimdal_raw_deletion_receipt_no_update'
          AND NOT t.tgisinternal
        """,
        (_DELETION_RECEIPT_TABLE,),
    )
    trigger_rows = cur.fetchall()
    if not any(
        _receipt_trigger_is_migration_ready(str(row[0]), str(row[1]))
        for row in trigger_rows
    ):
        raise RawLivenessSchemaMissingError(
            "Deletion-receipt reconciliation trigger is not migration-ready. "
            + _MIGRATION_HINT
        )
    cur.execute(
        """
        SELECT pg_get_functiondef(p.oid), pg_get_function_arguments(p.oid),
               p.provolatile, p.proisstrict
        FROM pg_proc AS p
        JOIN pg_namespace AS n ON n.oid = p.pronamespace
        WHERE n.nspname = current_schema()
          AND p.proname = 'heimdal_raw_cleanup_queue_is_subsequence'
          AND p.proargtypes = ARRAY['jsonb'::regtype, 'jsonb'::regtype]::oidvector
        """
    )
    helper_rows = cur.fetchall()
    if not any(
        _cleanup_queue_helper_is_migration_ready(
            str(row[0]), str(row[1]), str(row[2]), bool(row[3])
        )
        for row in helper_rows
    ):
        raise RawLivenessSchemaMissingError(
            "Deletion-receipt queue helper is not migration-ready. " + _MIGRATION_HINT
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


def assert_runtime_schema() -> None:
    """Fail closed when the migration-owned liveness authority is unavailable.

    Memory-backed test fixtures have no durable schema to check. PostgreSQL
    callers use a fresh read-only connection so startup/status can report an
    incomplete migration before the first media admission.
    """
    if resolve_heimdal_backend() != "pg":
        return
    conn = _pg_connect(autocommit=True)
    try:
        _assert_pg_schema(conn)
    finally:
        conn.close()


def _bootstrap_pg(conn: Any) -> None:
    if not _schema_autocreate_enabled():
        _assert_pg_schema(conn)
        return
    cur = conn.cursor()
    cur.execute(
        "SELECT to_regclass(%s), to_regclass(%s), to_regclass(%s), to_regclass(%s)",
        (_GENERATION_TABLE, _TOMBSTONE_TABLE, _LEASE_TABLE, _RETENTION_CLAIM_TABLE),
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
            deleted_at timestamptz NOT NULL DEFAULT now(),
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
    cur.execute(
        """
        CREATE OR REPLACE FUNCTION heimdal_raw_cleanup_queue_is_subsequence(
            old_payload jsonb, new_payload jsonb
        ) RETURNS boolean AS $$
        DECLARE
            old_refs text[] := ARRAY(
                SELECT jsonb_array_elements_text(COALESCE(old_payload, '[]'::jsonb))
            );
            new_ref text;
            old_index integer := 1;
            old_length integer := COALESCE(array_length(old_refs, 1), 0);
        BEGIN
            FOR new_ref IN SELECT jsonb_array_elements_text(COALESCE(new_payload, '[]'::jsonb)) LOOP
                WHILE old_index <= old_length AND old_refs[old_index] <> new_ref LOOP
                    old_index := old_index + 1;
                END LOOP;
                IF old_index > old_length THEN
                    RETURN false;
                END IF;
                old_index := old_index + 1;
            END LOOP;
            RETURN true;
        END;
        $$ LANGUAGE plpgsql IMMUTABLE STRICT
        """
    )
    cur.execute(
        f"""
        CREATE OR REPLACE FUNCTION heimdal_raw_deletion_receipt_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND current_setting('{_RETENTION_RECONCILE_GUARD_SETTING}', true) = 'true'
               AND NEW.id IS NOT DISTINCT FROM OLD.id
               AND NEW.record_id IS NOT DISTINCT FROM OLD.record_id
               AND NEW.content_identity IS NOT DISTINCT FROM OLD.content_identity
               AND NEW.reason IS NOT DISTINCT FROM OLD.reason
               AND NEW.retention_window_days IS NOT DISTINCT FROM OLD.retention_window_days
               AND NEW.deleted_at IS NOT DISTINCT FROM OLD.deleted_at
               AND NEW.sequence IS NOT DISTINCT FROM OLD.sequence
               AND (NEW.payload - 'cold_cleanup_location_refs')
                   IS NOT DISTINCT FROM (OLD.payload - 'cold_cleanup_location_refs')
               AND heimdal_raw_cleanup_queue_is_subsequence(
                   OLD.payload->'cold_cleanup_location_refs',
                   NEW.payload->'cold_cleanup_location_refs'
               ) THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'heimdal_raw_deletion_receipt is append-only: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    cur.execute(
        f"DROP TRIGGER IF EXISTS heimdal_raw_deletion_receipt_no_update "
        f"ON {_DELETION_RECEIPT_TABLE}"
    )
    cur.execute(
        f"""
        CREATE TRIGGER heimdal_raw_deletion_receipt_no_update
        BEFORE UPDATE OR DELETE ON {_DELETION_RECEIPT_TABLE}
        FOR EACH ROW EXECUTE FUNCTION heimdal_raw_deletion_receipt_reject_mutation()
        """
    )
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
    cur.execute(
        f"""
        CREATE TABLE {_RETENTION_CLAIM_TABLE} (
            id uuid PRIMARY KEY,
            content_identity text NOT NULL,
            generation integer NOT NULL,
            record_id uuid NOT NULL UNIQUE,
            raw_ref text NOT NULL UNIQUE,
            reason text NOT NULL,
            retention_window_days integer NOT NULL,
            claimed_at timestamptz NOT NULL,
            drain_after timestamptz NOT NULL,
            payload jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            sequence bigserial NOT NULL,
            FOREIGN KEY (content_identity, generation)
                REFERENCES {_GENERATION_TABLE}(content_identity, generation)
                ON DELETE RESTRICT
        )
        """
    )
    cur.execute(
        f"CREATE INDEX heimdal_raw_retention_claim_record_idx "
        f"ON {_RETENTION_CLAIM_TABLE} (record_id)"
    )
    cur.execute(
        """
        CREATE OR REPLACE FUNCTION heimdal_raw_liveness_generation_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'heimdal_raw_liveness_generation is append-only: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    cur.execute(
        f"""
        CREATE TRIGGER heimdal_raw_liveness_generation_no_mutation
        BEFORE UPDATE OR DELETE ON {_GENERATION_TABLE}
        FOR EACH ROW EXECUTE FUNCTION heimdal_raw_liveness_generation_reject_mutation()
        """
    )
    cur.execute(
        """
        CREATE OR REPLACE FUNCTION heimdal_raw_deletion_tombstone_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'heimdal_raw_deletion_tombstone is append-only: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    cur.execute(
        f"""
        CREATE TRIGGER heimdal_raw_deletion_tombstone_no_mutation
        BEFORE UPDATE OR DELETE ON {_TOMBSTONE_TABLE}
        FOR EACH ROW EXECUTE FUNCTION heimdal_raw_deletion_tombstone_reject_mutation()
        """
    )
    cur.execute(
        """
        CREATE OR REPLACE FUNCTION heimdal_raw_response_lease_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'heimdal_raw_response_lease is append-only: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    cur.execute(
        f"""
        CREATE TRIGGER heimdal_raw_response_lease_no_mutation
        BEFORE UPDATE OR DELETE ON {_LEASE_TABLE}
        FOR EACH ROW EXECUTE FUNCTION heimdal_raw_response_lease_reject_mutation()
        """
    )
    cur.execute(
        f"""
        CREATE OR REPLACE FUNCTION heimdal_raw_response_lease_reject_retiring()
        RETURNS trigger AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended(NEW.content_identity, 0));
            IF EXISTS (
                SELECT 1 FROM {_RETENTION_CLAIM_TABLE}
                WHERE record_id = NEW.record_id
            ) THEN
                RAISE EXCEPTION
                    'heimdal_raw_response_lease cannot be issued for a retiring raw generation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    cur.execute(
        f"""
        CREATE TRIGGER heimdal_raw_response_lease_reject_retiring
        BEFORE INSERT ON {_LEASE_TABLE}
        FOR EACH ROW EXECUTE FUNCTION heimdal_raw_response_lease_reject_retiring()
        """
    )
    cur.execute(
        """
        CREATE OR REPLACE FUNCTION heimdal_raw_retention_claim_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'heimdal_raw_retention_claim is append-only: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    cur.execute(
        f"""
        CREATE TRIGGER heimdal_raw_retention_claim_no_mutation
        BEFORE UPDATE OR DELETE ON {_RETENTION_CLAIM_TABLE}
        FOR EACH ROW EXECUTE FUNCTION heimdal_raw_retention_claim_reject_mutation()
        """
    )
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


def _load_pg_retention_claim(
    cur: Any, *, record_id: str
) -> Optional[RawRetentionClaim]:
    cur.execute(
        f"""
        SELECT id, content_identity, generation, raw_ref, reason,
               retention_window_days, claimed_at, drain_after, payload, sequence
        FROM {_RETENTION_CLAIM_TABLE}
        WHERE record_id = %s
        """,
        (record_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    payload = row[8] if isinstance(row[8], dict) else json.loads(row[8] or "{}")
    return RawRetentionClaim(
        id=str(row[0]),
        content_identity=str(row[1]),
        generation=int(row[2]),
        record_id=record_id,
        raw_ref=str(row[3]),
        reason=str(row[4]),
        retention_window_days=int(row[5]),
        claimed_at=row[6],
        drain_after=row[7],
        payload=dict(payload),
        sequence=int(row[9]),
    )


def _pg_exact_active(cur: Any, generation: RawLivenessGeneration) -> bool:
    cur.execute(
        """
        SELECT count(*) FILTER (WHERE p.active),
               count(*) FILTER (
                   WHERE p.active
                   AND p.storage_kind IN ('postgres_hot', 'encrypted_local_cold')
                   AND p.location_ref LIKE 'heimloc:%%'
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
            cur.execute(
                f"SELECT 1 FROM {_RETENTION_CLAIM_TABLE} WHERE record_id = %s",
                (record_id,),
            )
            if cur.fetchone() is not None:
                raise RawLivenessUnavailableError(
                    "raw generation is retiring under a durable retention claim"
                )
            cur.execute(
                f"""
                SELECT lease_id, issued_at, expires_at, sequence
                FROM {_LEASE_TABLE}
                WHERE record_id = %s AND generation = %s AND expires_at > %s
                ORDER BY sequence DESC
                LIMIT 1
                """,
                (record_id, generation.generation, issued_at),
            )
            existing_lease = cur.fetchone()
            if existing_lease is not None:
                projections[raw_ref] = RawLivenessProjection(
                    outcome="active",
                    generation=generation,
                    response_lease=RawResponseLease(
                        lease_id=str(existing_lease[0]),
                        content_identity=content_identity,
                        generation=generation.generation,
                        record_id=record_id,
                        raw_ref=raw_ref,
                        issued_at=existing_lease[1],
                        expires_at=existing_lease[2],
                        sequence=int(existing_lease[3]),
                    ),
                )
                continue
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


def _memory_claim_retention_locked(
    *,
    generation: RawLivenessGeneration,
    reason: str,
    retention_window_days: int,
    claimed_at: datetime,
    payload: Mapping[str, Any],
) -> RawRetentionClaim:
    existing = _MEMORY.retention_claims_by_record.get(generation.record_id)
    if existing is not None:
        return existing
    active_expiries = [
        lease.expires_at
        for lease in _MEMORY.leases
        if lease.record_id == generation.record_id and lease.expires_at > claimed_at
    ]
    drain_after = max([claimed_at, *active_expiries])
    claim = RawRetentionClaim(
        id=str(uuid4()),
        content_identity=generation.content_identity,
        generation=generation.generation,
        record_id=generation.record_id,
        raw_ref=generation.raw_ref,
        reason=reason,
        retention_window_days=retention_window_days,
        claimed_at=claimed_at,
        drain_after=drain_after,
        payload=dict(payload),
        sequence=len(_MEMORY.retention_claims),
    )
    _MEMORY.retention_claims.append(claim)
    _MEMORY.retention_claims_by_record[generation.record_id] = claim
    return claim


def _reconcile_memory_cold_cleanup(tombstone: RawDeletionTombstone) -> None:
    from app.heimdal import raw_store

    receipt = next(
        (item for item in _MEMORY.deletion_receipts if item.id == tombstone.deletion_receipt_id),
        None,
    )
    if receipt is None:
        return
    refs = list(receipt.payload.get("cold_cleanup_location_refs", []))
    remaining = list(refs)
    for location_ref in refs:
        object_path = raw_store._cold_object_path(str(location_ref))  # noqa: SLF001
        if object_path is None:
            raise raw_store.RawRepresentationDeletionError(
                "cold representation resolver is unavailable"
            )
        try:
            raw_store._delete_cold_object_path(object_path)  # noqa: SLF001
        except raw_store.RawRepresentationDeletionError:
            raise raw_store.RawRepresentationDeletionError("cold representation deletion failed")
        remaining.remove(str(location_ref))
        receipt.payload["cold_cleanup_location_refs"] = list(remaining)
    if remaining:
        raise raw_store.RawRepresentationDeletionError("cold representation deletion failed")


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
            _reconcile_memory_cold_cleanup(existing_tombstone)
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
        claim_was_new = record_id not in _MEMORY.retention_claims_by_record
        claim = _memory_claim_retention_locked(
            generation=generation,
            reason=reason,
            retention_window_days=retention_window_days,
            claimed_at=reference_time,
            payload=payload,
        )
        if reference_time < claim.drain_after:
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
        cold_paths = []
        for representation in raw_store.all_raw_representations(record_id):
            if representation.storage_kind == "encrypted_local_cold":
                object_path = raw_store._cold_object_path(representation.location_ref)  # noqa: SLF001
                if object_path is None:
                    raise raw_store.RawRepresentationDeletionError(
                        "cold representation resolver is unavailable"
                    )
                cold_paths.append((representation.location_ref, object_path))
        if cold_paths:
            receipt.payload["cold_cleanup_location_refs"] = [ref for ref, _path in cold_paths]
        _MEMORY.deletion_receipts.append(receipt)
        raw_deleted = False
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
            raw_deleted = True
            _reconcile_memory_cold_cleanup(tombstone)
        except Exception:
            if raw_deleted:
                raise
            raw_store._MEMORY_STORE.restore_state(raw_snapshot)  # noqa: SLF001
            if claim_was_new and _MEMORY.retention_claims and _MEMORY.retention_claims[-1] == claim:
                _MEMORY.retention_claims.pop()
                _MEMORY.retention_claims_by_record.pop(record_id, None)
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


def _reconcile_pg_cold_cleanup(cur: Any, record_id: str, *, conn: Any | None = None) -> None:
    from app.heimdal import raw_store

    cur.execute(
        f"SELECT deletion_receipt_id FROM {_TOMBSTONE_TABLE} WHERE record_id = %s",
        (record_id,),
    )
    tombstone_row = cur.fetchone()
    if tombstone_row is None:
        return
    cur.execute(
        f"SELECT payload FROM {_DELETION_RECEIPT_TABLE} WHERE id = %s",
        (tombstone_row[0],),
    )
    receipt_row = cur.fetchone()
    payload = receipt_row[0] if receipt_row else {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    remaining = [str(ref) for ref in payload.get("cold_cleanup_location_refs", [])]
    for location_ref in list(remaining):
        object_path = raw_store._cold_object_path(str(location_ref))  # noqa: SLF001
        if object_path is None:
            raise raw_store.RawRepresentationDeletionError(
                "cold representation resolver is unavailable"
            )
        try:
            raw_store._delete_cold_object_path(object_path)  # noqa: SLF001
        except raw_store.RawRepresentationDeletionError:
            updated_payload = dict(payload)
            updated_payload["cold_cleanup_location_refs"] = remaining
            if conn is not None:
                cur.execute(
                    "SELECT set_config(%s, 'true', true)",
                    (_RETENTION_RECONCILE_GUARD_SETTING,),
                )
            cur.execute(
                f"UPDATE {_DELETION_RECEIPT_TABLE} SET payload = %s::jsonb WHERE id = %s",
                (json.dumps(updated_payload), tombstone_row[0]),
            )
            if conn is not None:
                conn.commit()
            raise raw_store.RawRepresentationDeletionError("cold representation deletion failed")
        remaining.remove(location_ref)
        updated_payload = dict(payload)
        updated_payload["cold_cleanup_location_refs"] = remaining
        if conn is not None:
            cur.execute(
                "SELECT set_config(%s, 'true', true)",
                (_RETENTION_RECONCILE_GUARD_SETTING,),
            )
        cur.execute(
            f"UPDATE {_DELETION_RECEIPT_TABLE} SET payload = %s::jsonb WHERE id = %s",
            (json.dumps(updated_payload), tombstone_row[0]),
        )
        if conn is not None:
            conn.commit()


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
            cur.execute(
                "SELECT set_config(%s, 'true', true)",
                (_RETENTION_RECONCILE_GUARD_SETTING,),
            )
            try:
                _reconcile_pg_cold_cleanup(cur, record_id, conn=conn)
            except Exception:
                conn.commit()
                raise
            conn.commit()
            return GovernedDeletionResult(outcome="already_erased", tombstone=tombstone)
        if not raw_active:
            raise RawLivenessUnavailableError(
                "untombstoned retention target is missing its active representation"
            )
        reference_time = _as_utc(deleted_at)
        claim = _load_pg_retention_claim(cur, record_id=record_id)
        if claim is None:
            cur.execute(
                f"SELECT max(expires_at) FROM {_LEASE_TABLE} "
                "WHERE record_id = %s AND expires_at > %s",
                (record_id, reference_time),
            )
            lease_row = cur.fetchone()
            drain_after = max(reference_time, lease_row[0]) if lease_row[0] else reference_time
            claim_id = str(uuid4())
            cur.execute(
                f"""
                INSERT INTO {_RETENTION_CLAIM_TABLE} (
                    id, content_identity, generation, record_id, raw_ref,
                    reason, retention_window_days, claimed_at, drain_after, payload
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                RETURNING id, content_identity, generation, raw_ref, reason,
                          retention_window_days, claimed_at, drain_after, payload, sequence
                """,
                (
                    claim_id,
                    content_identity,
                    generation.generation,
                    record_id,
                    generation.raw_ref,
                    reason,
                    retention_window_days,
                    reference_time,
                    drain_after,
                    json.dumps(dict(payload)),
                ),
            )
            claim_row = cur.fetchone()
            claim = RawRetentionClaim(
                id=str(claim_row[0]),
                content_identity=str(claim_row[1]),
                generation=int(claim_row[2]),
                record_id=record_id,
                raw_ref=str(claim_row[3]),
                reason=str(claim_row[4]),
                retention_window_days=int(claim_row[5]),
                claimed_at=claim_row[6],
                drain_after=claim_row[7],
                payload=(
                    claim_row[8]
                    if isinstance(claim_row[8], dict)
                    else json.loads(claim_row[8] or "{}")
                ),
                sequence=int(claim_row[9]),
            )
        if reference_time < claim.drain_after:
            conn.commit()
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
        cold_location_refs: list[str] = []
        try:
            cur.execute(
                "SELECT 1 FROM heimdal_raw_record WHERE id = %s FOR UPDATE",
                (record_id,),
            )
            if cur.fetchone() is None:
                raise RawLivenessUnavailableError(
                    "raw identity disappeared before governed deletion"
                )
            locations = raw_store._cold_location_paths_for_pg_cursor(cur, record_id)  # noqa: SLF001
            cold_location_refs = [location_ref for location_ref, _path in locations]
            if cold_location_refs:
                cleanup_payload = dict(receipt.payload)
                cleanup_payload["cold_cleanup_location_refs"] = cold_location_refs
                cur.execute(
                    "SELECT set_config(%s, 'true', true)",
                    (_RETENTION_RECONCILE_GUARD_SETTING,),
                )
                cur.execute(
                    f"UPDATE {_DELETION_RECEIPT_TABLE} SET payload = %s::jsonb WHERE id = %s",
                    (json.dumps(cleanup_payload), receipt.id),
                )
            cur.execute(
                "DELETE FROM heimdal_raw_representation WHERE record_id = %s",
                (record_id,),
            )
        except Exception as exc:
            raise raw_store.RawRepresentationDeletionError(
                "governed all-copy deletion failed; no identity was removed"
            ) from exc
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
        try:
            if cold_location_refs:
                acquire_pg_fence(cur, content_identity)
                cur.execute(
                    "SELECT set_config(%s, 'true', true)",
                    (_RETENTION_RECONCILE_GUARD_SETTING,),
                )
                _reconcile_pg_cold_cleanup(cur, record_id, conn=conn)
                conn.commit()
        except Exception:
            # The DB erasure is already committed. Preserve any reduced queue
            # update so the next retry converges instead of replaying refs.
            conn.commit()
            raise
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


def all_retention_claims() -> list[RawRetentionClaim]:
    if resolve_heimdal_backend() == "memory":
        with _MEMORY_FENCE:
            return list(_MEMORY.retention_claims)
    conn = _pg_connect(autocommit=True)
    try:
        _assert_pg_schema(conn)
        cur = conn.cursor()
        cur.execute(
            f"SELECT record_id FROM {_RETENTION_CLAIM_TABLE} ORDER BY sequence"
        )
        claims = []
        for row in cur.fetchall():
            claim = _load_pg_retention_claim(cur, record_id=str(row[0]))
            if claim is not None:
                claims.append(claim)
        return claims
    finally:
        conn.close()


def reset_memory_raw_liveness() -> None:
    with _MEMORY_FENCE:
        _MEMORY.generations_by_record.clear()
        _MEMORY.generations_by_content.clear()
        _MEMORY.tombstones_by_record.clear()
        _MEMORY.leases.clear()
        _MEMORY.retention_claims_by_record.clear()
        _MEMORY.retention_claims.clear()
        _MEMORY.deletion_receipts.clear()
        _MEMORY.tombstones.clear()


def reset_memory_deletion_receipts() -> None:
    with _MEMORY_FENCE:
        _MEMORY.tombstones_by_record.clear()
        _MEMORY.retention_claims_by_record.clear()
        _MEMORY.retention_claims.clear()
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
    "RawRetentionClaim",
    "RawResponseLease",
    "all_deletion_receipts",
    "all_deletion_tombstones",
    "all_retention_claims",
    "governed_delete_raw_record",
    "issue_response_lease",
    "project_with_response_leases",
    "reset_memory_deletion_receipts",
]
