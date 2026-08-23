"""Generation-aware raw-evidence liveness and response fencing.

This module is the authority for whether one exact ``heimraw:<record-id>``
generation is active, governed-erased, or unavailable.  It deliberately does
not infer erasure from absence: only an append-only deletion tombstone can
produce the erased state.

The same per-content fence is used by response-lease issuance, raw insertion,
and both retention writers.  PostgreSQL uses a transaction-scoped advisory
lock followed by the immutable generation row lock; memory uses one re-entrant
lock with the same ordering.  A governed deletion commits its deletion
receipt, tombstone, all registry deletes, and identity delete in one
transaction, then drains durable cold object/manifest cleanup before liveness
may project terminal ``erased``.
"""

from __future__ import annotations

from contextlib import contextmanager
import copy
import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, Iterator, Literal, Mapping, Optional
from uuid import UUID, uuid4

from app.heimdal._backend import resolve_heimdal_backend

_GENERATION_TABLE = "heimdal_raw_liveness_generation"
_TOMBSTONE_TABLE = "heimdal_raw_deletion_tombstone"
_LEASE_TABLE = "heimdal_raw_response_lease"
_RETENTION_CLAIM_TABLE = "heimdal_raw_retention_claim"
_DELETION_RECEIPT_TABLE = "heimdal_raw_deletion_receipt"
_CONSENT_ASSOCIATION_TABLE = "heimdal_raw_consent_association"
_RAW_REF_PREFIX = "heimraw:"
_RETENTION_GUARD_SETTING = "app.heimdal_retention_bypass"
_RETENTION_RECONCILE_GUARD_SETTING = "app.heimdal_retention_reconcile"
_COLD_CLEANUP_PAYLOAD_KEY = "cold_cleanup_location_refs"
_COLD_CLEANUP_BINDINGS_PAYLOAD_KEY = "cold_cleanup_archive_bindings"
CONSENT_GRANT_DIGEST_PAYLOAD_KEY = "consent_grant_digest"
CONSENT_GRANT_DIGESTS_PAYLOAD_KEY = "consent_grant_digests"
RAW_MODALITY_PAYLOAD_KEY = "raw_modality"

RESPONSE_LEASE_SECONDS = 30

_MIGRATION_HINT = (
    "raw liveness is migration-owned: run 'alembic upgrade head' against this "
    "database. See revisions c5d8a1e4f2b7, e2f3a4b5c6d7, f4b6c8d0e2a1, "
    "and a9d7c5e3b1f0."
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

_PRE_HAR04_RECEIPT_TRIGGER_BODY = "raise exception 'heimdal_raw_deletion_receipt is append-only (heim-1): % is not permitted', tg_op;"

_CONSENT_TRIGGER_BODY = (
    "if tg_op = 'insert' then "
    "if new.legacy_lineage_ambiguous and current_setting('app.heimdal_legacy_lineage_backfill', true) "
    "is distinct from 'true' then raise exception 'legacy lineage ambiguity is migration-only authority'; "
    "end if; select content_identity into authority_identity "
    "from heimdal_raw_liveness_generation where record_id = new.record_id and generation = new.generation; "
    "if authority_identity is null then raise exception 'consent association has no matching raw generation'; "
    "end if; perform pg_advisory_xact_lock(hashtextextended(authority_identity, 0)); "
    "if exists (select 1 from heimdal_raw_retention_claim where record_id = new.record_id) "
    "or exists (select 1 from heimdal_raw_deletion_tombstone where record_id = new.record_id) then "
    "raise exception 'consent association cannot admit a retiring raw generation'; end if; "
    "return new; end if; if tg_op = 'delete' "
    "and current_setting('app.heimdal_retention_bypass', true) = 'true' "
    "and exists (select 1 from heimdal_raw_deletion_tombstone where record_id = old.record_id) then "
    "return old; end if; raise exception "
    "'heimdal_raw_consent_association is append-only: % is not permitted', tg_op;"
)

_CLEANUP_QUEUE_HELPER_BODY = (
    "declare old_refs text[] := array( select jsonb_array_elements_text(coalesce(old_payload, '[]'::jsonb)) ); "
    "new_ref text; old_index integer := 1; old_length integer := coalesce(array_length(old_refs, 1), 0); "
    "begin for new_ref in select jsonb_array_elements_text(coalesce(new_payload, '[]'::jsonb)) loop "
    "while old_index <= old_length and old_refs[old_index] <> new_ref loop old_index := old_index + 1; end loop; "
    "if old_index > old_length then return false; end if; old_index := old_index + 1; end loop; "
    "return true; end;"
)


def _normalize_trigger_sql(value: str) -> str:
    """Normalize PostgreSQL's deparsed operator/cast spelling for exact checks."""
    normalized = re.sub(r"\s+", " ", value).lower().strip()
    normalized = re.sub(r"\s*->\s*", "->", normalized)
    normalized = re.sub(r"::text\b", "", normalized)
    normalized = re.sub(r"\(\s*", "(", normalized)
    normalized = re.sub(r"\s*\)", ")", normalized)
    return normalized


def _receipt_trigger_matches(function_def: str, trigger_def: str, expected_body: str) -> bool:
    normalized = _normalize_trigger_sql(function_def)
    normalized_trigger = _normalize_trigger_sql(trigger_def)
    body_match = re.search(r"\bbegin\s+(.*?)\bend\s*;", normalized, re.IGNORECASE)
    body = body_match.group(1).strip() if body_match else ""
    return bool(
        body == _normalize_trigger_sql(expected_body)
        and re.fullmatch(
            r"create trigger heimdal_raw_deletion_receipt_no_update "
            r"before delete or update on (?:[a-z_][a-z0-9_]*\.)?heimdal_raw_deletion_receipt "
            r"for each row execute function "
            r"(?:[a-z_][a-z0-9_]*\.)?heimdal_raw_deletion_receipt_reject_mutation\(\)",
            normalized_trigger,
        )
    )


def _receipt_trigger_is_migration_ready(function_def: str, trigger_def: str) -> bool:
    """Accept the current HAR-04 guarded update trigger shape."""
    return _receipt_trigger_matches(function_def, trigger_def, _RECEIPT_TRIGGER_BODY)


def _receipt_trigger_is_legacy_migration_ready(function_def: str, trigger_def: str) -> bool:
    """Accept the historical pre-HAR-04 trigger shape at its version boundary."""
    return _receipt_trigger_matches(function_def, trigger_def, _PRE_HAR04_RECEIPT_TRIGGER_BODY)


def _consent_association_trigger_is_migration_ready(
    function_def: str, trigger_def: str
) -> bool:
    """Authenticate the exact append-only consent trigger and binding."""

    function = _normalize_trigger_sql(function_def)
    trigger = _normalize_trigger_sql(trigger_def)
    trigger_match = re.fullmatch(
        r"create trigger heimdal_raw_consent_association_no_mutation "
        r"before ((?:insert|update|delete)(?: or (?:insert|update|delete)){2}) on "
        r"(?:[a-z_][a-z0-9_]*\.)?heimdal_raw_consent_association "
        r"for each row execute function "
        r"(?:[a-z_][a-z0-9_]*\.)?heimdal_raw_consent_association_reject_mutation\(\)",
        trigger,
    )
    begin_matches = list(re.finditer(r"\bbegin\b", function, re.IGNORECASE))
    end_matches = list(re.finditer(r"\bend\s*;", function, re.IGNORECASE))
    body = (
        function[begin_matches[0].end() : end_matches[0].start()].strip()
        if len(begin_matches) == 1 and len(end_matches) == 1
        else ""
    )
    trigger_shape = (
        trigger_match is not None
        and set(trigger_match.group(1).split(" or ")) == {"insert", "update", "delete"}
    )
    return bool(
        trigger_shape
        and body == _normalize_trigger_sql(_CONSENT_TRIGGER_BODY)
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


_MUTATION_AUTHORITY_ISSUER = object()
_ACTIVE_MUTATION_AUTHORITIES: Dict[int, "RawMutationAuthority"] = {}
_MUTATION_AUTHORITY_LOCK = threading.Lock()


@dataclass(frozen=True, init=False)
class RawMutationAuthority:
    """Unforgeable, context-bound authority for one active raw generation.

    PostgreSQL authorities carry the cursor whose session owns the advisory
    lock. This keeps registration/activation on one connection, while allowing
    a cold reservation to commit before external bytes are written without
    opening a retirement check/use gap.
    """

    record_id: str
    content_identity: str
    generation: int
    backend: Literal["memory", "pg"]
    owner_thread_id: int
    _issuer: object
    _cursor: Any | None

    def __init__(
        self,
        *,
        _issuer: object,
        record_id: str,
        content_identity: str,
        generation: int,
        backend: Literal["memory", "pg"],
        cursor: Any | None = None,
    ) -> None:
        if _issuer is not _MUTATION_AUTHORITY_ISSUER:
            raise RawLivenessUnavailableError("raw mutation authority cannot be forged")
        object.__setattr__(self, "record_id", record_id)
        object.__setattr__(self, "content_identity", content_identity)
        object.__setattr__(self, "generation", generation)
        object.__setattr__(self, "backend", backend)
        object.__setattr__(self, "owner_thread_id", threading.get_ident())
        object.__setattr__(self, "_issuer", _issuer)
        object.__setattr__(self, "_cursor", cursor)


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
    outcome: Literal["active", "erasure_pending", "erased"]
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


def _assert_new_deletion_payload(payload: Mapping[str, Any]) -> None:
    if (
        _COLD_CLEANUP_PAYLOAD_KEY in payload
        or _COLD_CLEANUP_BINDINGS_PAYLOAD_KEY in payload
    ):
        raise ValueError(
            "cold cleanup authority is reserved for governed retention authority"
        )
    if (
        CONSENT_GRANT_DIGEST_PAYLOAD_KEY in payload
        or CONSENT_GRANT_DIGESTS_PAYLOAD_KEY in payload
    ):
        raise ValueError("consent grant correlation is reserved for governed retention authority")
    if RAW_MODALITY_PAYLOAD_KEY in payload:
        raise ValueError("raw modality is reserved for governed retention authority")


def consent_grant_digest(grant_ref: str) -> str:
    """Return the content-redacted durable correlation for one consent grant."""

    if not isinstance(grant_ref, str) or not grant_ref.strip():
        raise ValueError("grant_ref must be a non-empty string")
    return hashlib.sha256(grant_ref.encode("utf-8")).hexdigest()


def _governed_deletion_payload(
    payload: Mapping[str, Any],
    *,
    grant_refs: Iterable[str],
    correlation_grant_ref: Optional[str],
    raw_modality: str,
    legacy_lineage_ambiguous: bool = False,
) -> Dict[str, Any]:
    governed = dict(payload)
    refs = sorted({ref for ref in grant_refs if isinstance(ref, str) and ref})
    if not refs:
        raise RawLivenessUnavailableError(
            "active raw generation has no durable consent association"
        )
    if (
        correlation_grant_ref is not None
        and correlation_grant_ref not in refs
        and not legacy_lineage_ambiguous
    ):
        raise RawLivenessUnavailableError(
            "deletion correlation grant is not associated with the raw generation"
        )
    digests = sorted(consent_grant_digest(ref) for ref in refs)
    governed[CONSENT_GRANT_DIGESTS_PAYLOAD_KEY] = digests
    selected = correlation_grant_ref or (refs[0] if len(refs) == 1 else None)
    if selected is not None:
        governed[CONSENT_GRANT_DIGEST_PAYLOAD_KEY] = consent_grant_digest(selected)
    governed[RAW_MODALITY_PAYLOAD_KEY] = raw_modality
    if legacy_lineage_ambiguous:
        governed["legacy_lineage_ambiguous"] = True
    return governed


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
        if record_id in _MEMORY.retention_claims_by_record:
            raise RawLivenessUnavailableError(
                "raw generation is retiring and refuses new work"
            )
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
        receipt = next(
            (
                item
                for item in _MEMORY.deletion_receipts
                if item.id == tombstone.deletion_receipt_id
            ),
            None,
        )
        if receipt is None:
            raise RawLivenessUnavailableError(
                "tombstoned raw generation has no matching deletion receipt"
            )
        return RawLivenessProjection(
            outcome=(
                "erasure_pending"
                if receipt.payload.get(_COLD_CLEANUP_PAYLOAD_KEY)
                else "erased"
            ),
            generation=generation,
            tombstone=tombstone,
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
    return RawLivenessProjection(outcome="active", generation=generation, response_lease=lease)


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
        _CONSENT_ASSOCIATION_TABLE,
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
        _CONSENT_ASSOCIATION_TABLE: {
            "record_id",
            "generation",
            "grant_ref",
            "admitted_at",
            "legacy_lineage_ambiguous",
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
              'heimdal_raw_deletion_receipt_no_update',
              'heimdal_raw_consent_association_no_mutation'
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
        "heimdal_raw_consent_association_no_mutation",
    }
    if triggers != expected:
        raise RawLivenessSchemaMissingError(
            "Raw-liveness append-only triggers are incomplete. " + _MIGRATION_HINT
        )
    cur.execute(
        """
        SELECT pg_get_functiondef(t.tgfoid), pg_get_triggerdef(t.oid)
        FROM pg_trigger AS t
        JOIN pg_class AS c ON c.oid = t.tgrelid
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = current_schema()
          AND c.relname = %s
          AND t.tgname = 'heimdal_raw_consent_association_no_mutation'
          AND NOT t.tgisinternal
        """,
        (_CONSENT_ASSOCIATION_TABLE,),
    )
    consent_guard_rows = cur.fetchall()
    if not any(
        _consent_association_trigger_is_migration_ready(str(row[0]), str(row[1]))
        for row in consent_guard_rows
    ):
        raise RawLivenessSchemaMissingError(
            "Consent-association authority trigger is not migration-ready. " + _MIGRATION_HINT
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
    current_trigger = any(
        _receipt_trigger_is_migration_ready(str(row[0]), str(row[1])) for row in trigger_rows
    )
    if not current_trigger:
        raise RawLivenessSchemaMissingError(
            "Deletion-receipt reconciliation trigger is not migration-ready. " + _MIGRATION_HINT
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
            "liveness generation. " + _MIGRATION_HINT
        )
    cur.execute(
        f"""
        SELECT r.id
        FROM heimdal_raw_record AS r
        JOIN {_GENERATION_TABLE} AS g ON g.record_id = r.id
        LEFT JOIN {_TOMBSTONE_TABLE} AS t ON t.record_id = r.id
        LEFT JOIN {_CONSENT_ASSOCIATION_TABLE} AS a
          ON a.record_id = r.id AND a.generation = g.generation
        WHERE t.record_id IS NULL
        GROUP BY r.id
        HAVING count(a.grant_ref) = 0
        LIMIT 1
        """
    )
    if cur.fetchone() is not None:
        raise RawLivenessSchemaMissingError(
            "Active raw generation lacks durable consent association. " + _MIGRATION_HINT
        )


def assert_runtime_schema() -> None:
    """Fail closed unless the complete raw/liveness authority is current.

    Memory-backed test fixtures have no durable schema to check. PostgreSQL
    callers use a fresh read-only connection so startup/status can report an
    incomplete migration before the first media admission. The raw-store
    assertion includes this module's liveness assertion, so calling it here
    validates the complete current contract without recursing through this
    public startup entrypoint.
    """
    if resolve_heimdal_backend() != "pg":
        return
    from app.heimdal import raw_store

    conn = _pg_connect(autocommit=True)
    try:
        try:
            raw_store._assert_pg_schema(conn)  # noqa: SLF001
        except raw_store.RawStoreSchemaMissingError as exc:
            raise RawLivenessSchemaMissingError(
                "Raw identity/representation schema is not migration-ready for liveness. "
                + _MIGRATION_HINT
            ) from exc
    finally:
        conn.close()


def _bootstrap_pg(conn: Any) -> None:
    if not _schema_autocreate_enabled():
        _assert_pg_schema(conn)
        return
    cur = conn.cursor()
    fixture_tables = (
        _GENERATION_TABLE,
        _TOMBSTONE_TABLE,
        _LEASE_TABLE,
        _RETENTION_CLAIM_TABLE,
        _CONSENT_ASSOCIATION_TABLE,
    )
    cur.execute(
        "SELECT " + ", ".join("to_regclass(%s)" for _ in fixture_tables),
        fixture_tables,
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
    generation_table_groups = (
        (
            _GENERATION_TABLE,
            (
                f"""
                CREATE TABLE {_GENERATION_TABLE} (
                    content_identity text NOT NULL,
                    generation integer NOT NULL CHECK (generation > 0),
                    record_id uuid NOT NULL UNIQUE,
                    raw_ref text NOT NULL UNIQUE CHECK (raw_ref LIKE '{_RAW_REF_PREFIX}%'),
                    activated_at timestamptz NOT NULL,
                    sequence bigserial NOT NULL,
                    PRIMARY KEY (content_identity, generation),
                    CONSTRAINT heimdal_raw_liveness_generation_record_generation_uq
                        UNIQUE (record_id, generation)
                )
                """,
                f"""
                ALTER TABLE heimdal_raw_representation
                ADD CONSTRAINT heimdal_raw_representation_generation_fk
                FOREIGN KEY (record_id, raw_generation)
                    REFERENCES {_GENERATION_TABLE}(record_id, generation)
                    ON DELETE RESTRICT
                """,
                f"""
                CREATE OR REPLACE FUNCTION heimdal_raw_representation_reject_mutation()
                RETURNS trigger AS $$
                DECLARE
                    authority_identity text;
                    authority_generation integer;
                BEGIN
                    IF TG_OP IN ('INSERT', 'UPDATE') THEN
                        SELECT content_identity, generation
                        INTO authority_identity, authority_generation
                        FROM {_GENERATION_TABLE}
                        WHERE record_id = NEW.record_id;
                        IF authority_identity IS NULL
                           OR NEW.raw_generation IS DISTINCT FROM authority_generation THEN
                            RAISE EXCEPTION
                                'raw representation has no matching liveness generation';
                        END IF;
                        PERFORM pg_advisory_xact_lock(
                            hashtextextended(authority_identity, 0)
                        );
                        IF EXISTS (
                            SELECT 1 FROM {_RETENTION_CLAIM_TABLE}
                            WHERE record_id = NEW.record_id
                        ) OR EXISTS (
                            SELECT 1 FROM {_TOMBSTONE_TABLE}
                            WHERE record_id = NEW.record_id
                        ) THEN
                            RAISE EXCEPTION
                                'raw representation cannot mutate a retiring generation';
                        END IF;
                        IF NEW.storage_kind = 'encrypted_local_cold'
                           AND EXISTS (
                               SELECT 1 FROM {_DELETION_RECEIPT_TABLE}
                               WHERE COALESCE(
                                   payload->'{_COLD_CLEANUP_PAYLOAD_KEY}', '[]'::jsonb
                               ) ? NEW.location_ref
                           ) THEN
                            RAISE EXCEPTION
                                'cold location remains owned by pending governed cleanup';
                        END IF;
                        IF TG_OP = 'INSERT' THEN
                            RETURN NEW;
                        END IF;
                    END IF;
                    IF TG_OP = 'UPDATE'
                       AND current_setting(
                           'app.heimdal_legacy_archive_reconcile', true
                       ) = 'true'
                       AND NEW.id IS NOT DISTINCT FROM OLD.id
                       AND NEW.record_id IS NOT DISTINCT FROM OLD.record_id
                       AND NEW.storage_kind IS NOT DISTINCT FROM OLD.storage_kind
                       AND NEW.location_ref IS NOT DISTINCT FROM OLD.location_ref
                       AND NEW.ciphertext IS NOT DISTINCT FROM OLD.ciphertext
                       AND NEW.nonce IS NOT DISTINCT FROM OLD.nonce
                       AND NEW.key_ref IS NOT DISTINCT FROM OLD.key_ref
                       AND NEW.raw_generation IS NOT DISTINCT FROM OLD.raw_generation
                       AND NEW.archive_token IS NOT DISTINCT FROM OLD.archive_token
                       AND OLD.archive_generation IS NULL
                       AND NEW.archive_generation ~ '^[0-9a-f]{{64}}$'
                       AND NEW.registered_at IS NOT DISTINCT FROM OLD.registered_at
                       AND NEW.sequence IS NOT DISTINCT FROM OLD.sequence THEN
                        RETURN NEW;
                    END IF;
                    IF TG_OP = 'UPDATE'
                       AND current_setting(
                           'app.heimdal_representation_activation', true
                       ) = 'true'
                       AND NEW.id IS NOT DISTINCT FROM OLD.id
                       AND NEW.record_id IS NOT DISTINCT FROM OLD.record_id
                       AND NEW.storage_kind IS NOT DISTINCT FROM OLD.storage_kind
                       AND NEW.location_ref IS NOT DISTINCT FROM OLD.location_ref
                       AND NEW.ciphertext IS NOT DISTINCT FROM OLD.ciphertext
                       AND NEW.nonce IS NOT DISTINCT FROM OLD.nonce
                       AND NEW.key_ref IS NOT DISTINCT FROM OLD.key_ref
                       AND NEW.raw_generation IS NOT DISTINCT FROM OLD.raw_generation
                       AND NEW.archive_token IS NOT DISTINCT FROM OLD.archive_token
                       AND NEW.archive_generation IS NOT DISTINCT FROM OLD.archive_generation
                       AND NEW.registered_at IS NOT DISTINCT FROM OLD.registered_at
                       AND NEW.sequence IS NOT DISTINCT FROM OLD.sequence THEN
                        RETURN NEW;
                    END IF;
                    IF TG_OP = 'DELETE'
                       AND current_setting('{_RETENTION_GUARD_SETTING}', true) = 'true'
                       AND EXISTS (
                           SELECT 1 FROM {_TOMBSTONE_TABLE}
                           WHERE record_id = OLD.record_id
                       ) THEN
                        RETURN OLD;
                    END IF;
                    RAISE EXCEPTION
                        'heimdal_raw_representation mutation is governed: % is not permitted',
                        TG_OP;
                END;
                $$ LANGUAGE plpgsql
                """,
                "DROP TRIGGER IF EXISTS heimdal_raw_representation_no_mutation "
                "ON heimdal_raw_representation",
                """
                CREATE TRIGGER heimdal_raw_representation_no_mutation
                BEFORE INSERT OR UPDATE OR DELETE ON heimdal_raw_representation
                FOR EACH ROW EXECUTE FUNCTION heimdal_raw_representation_reject_mutation()
                """,
            ),
        ),
    )
    for table_name, statements in generation_table_groups:
        cur.execute("SELECT to_regclass(%s)", (table_name,))
        table_present_row = cur.fetchone()
        table_present = bool(table_present_row and table_present_row[0])
        if table_present:
            continue
        for statement in statements:
            cur.execute(statement)
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
    consent_association_table_groups = (
        (
            _CONSENT_ASSOCIATION_TABLE,
            (
                f"""
                CREATE TABLE {_CONSENT_ASSOCIATION_TABLE} (
                    record_id uuid NOT NULL
                        REFERENCES heimdal_raw_record(id) ON DELETE CASCADE,
                    generation integer NOT NULL,
                    grant_ref text NOT NULL CHECK (btrim(grant_ref) <> ''),
                    admitted_at timestamptz NOT NULL,
                    legacy_lineage_ambiguous boolean NOT NULL DEFAULT false,
                    sequence bigserial NOT NULL,
                    PRIMARY KEY (record_id, generation, grant_ref),
                    FOREIGN KEY (record_id, generation)
                        REFERENCES {_GENERATION_TABLE}(record_id, generation)
                        ON DELETE RESTRICT
                )
                """,
                f"CREATE INDEX heimdal_raw_consent_association_grant_idx "
                f"ON {_CONSENT_ASSOCIATION_TABLE} (grant_ref, sequence)",
                f"""
                CREATE OR REPLACE FUNCTION
                    heimdal_raw_consent_association_reject_mutation()
                RETURNS trigger AS $$
                DECLARE
                    authority_identity text;
                BEGIN
                    IF TG_OP = 'INSERT' THEN
                        IF NEW.legacy_lineage_ambiguous
                           AND current_setting('app.heimdal_legacy_lineage_backfill', true)
                               IS DISTINCT FROM 'true' THEN
                            RAISE EXCEPTION
                                'legacy lineage ambiguity is migration-only authority';
                        END IF;
                        SELECT content_identity INTO authority_identity
                        FROM {_GENERATION_TABLE}
                        WHERE record_id = NEW.record_id
                          AND generation = NEW.generation;
                        IF authority_identity IS NULL THEN
                            RAISE EXCEPTION
                                'consent association has no matching raw generation';
                        END IF;
                        PERFORM pg_advisory_xact_lock(
                            hashtextextended(authority_identity, 0)
                        );
                        IF EXISTS (
                            SELECT 1 FROM {_RETENTION_CLAIM_TABLE}
                            WHERE record_id = NEW.record_id
                        ) OR EXISTS (
                            SELECT 1 FROM {_TOMBSTONE_TABLE}
                            WHERE record_id = NEW.record_id
                        ) THEN
                            RAISE EXCEPTION
                                'consent association cannot admit a retiring raw generation';
                        END IF;
                        RETURN NEW;
                    END IF;
                    IF TG_OP = 'DELETE'
                       AND current_setting('{_RETENTION_GUARD_SETTING}', true) = 'true'
                       AND EXISTS (
                           SELECT 1 FROM {_TOMBSTONE_TABLE}
                           WHERE record_id = OLD.record_id
                       ) THEN
                        RETURN OLD;
                    END IF;
                    RAISE EXCEPTION
                        'heimdal_raw_consent_association is append-only: % is not permitted',
                        TG_OP;
                END;
                $$ LANGUAGE plpgsql
                """,
                f"""
                CREATE TRIGGER heimdal_raw_consent_association_no_mutation
                BEFORE INSERT OR UPDATE OR DELETE ON {_CONSENT_ASSOCIATION_TABLE}
                FOR EACH ROW EXECUTE FUNCTION
                    heimdal_raw_consent_association_reject_mutation()
                """,
            ),
        ),
    )
    for consent_table_name, consent_statements in consent_association_table_groups:
        cur.execute("SELECT to_regclass(%s)", (consent_table_name,))
        table_present_row = cur.fetchone()
        table_present = bool(table_present_row and table_present_row[0])
        if table_present:
            continue
        for statement in consent_statements:
            cur.execute(statement)
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
            cur.execute(f"SELECT 1 FROM {_TOMBSTONE_TABLE} WHERE record_id = %s", (record_id,))
            if cur.fetchone() is not None:
                raise RawEvidenceErasedError(_load_pg_tombstone(cur, record_id=record_id))
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
    cur.execute(f"SELECT 1 FROM {_RETENTION_CLAIM_TABLE} WHERE record_id = %s", (record_id,))
    if cur.fetchone() is not None:
        raise RawLivenessUnavailableError(
            "raw generation is retiring and refuses new work"
        )
    return RawLivenessGeneration(
        content_identity=content_identity,
        generation=int(row[0]),
        record_id=record_id,
        raw_ref=str(row[1]),
        activated_at=row[2],
        sequence=int(row[3]),
    )


def _activate_mutation_authority(authority: RawMutationAuthority) -> None:
    with _MUTATION_AUTHORITY_LOCK:
        _ACTIVE_MUTATION_AUTHORITIES[id(authority)] = authority


def _deactivate_mutation_authority(authority: RawMutationAuthority) -> None:
    with _MUTATION_AUTHORITY_LOCK:
        if _ACTIVE_MUTATION_AUTHORITIES.get(id(authority)) is authority:
            _ACTIVE_MUTATION_AUTHORITIES.pop(id(authority), None)


def require_raw_mutation_authority(
    authority: object,
    *,
    record_id: str,
    content_identity: Optional[str] = None,
) -> RawMutationAuthority:
    """Validate one live, same-thread generation-fence capability."""

    if not isinstance(authority, RawMutationAuthority):
        raise RawLivenessUnavailableError("raw mutation requires generation-fence authority")
    with _MUTATION_AUTHORITY_LOCK:
        active = _ACTIVE_MUTATION_AUTHORITIES.get(id(authority))
    if (
        active is not authority
        or authority._issuer is not _MUTATION_AUTHORITY_ISSUER
        or authority.owner_thread_id != threading.get_ident()
        or authority.record_id != record_id
        or (content_identity is not None and authority.content_identity != content_identity)
        or authority.backend != resolve_heimdal_backend()
    ):
        raise RawLivenessUnavailableError(
            "raw mutation authority is stale or bound to a different generation"
        )
    return authority


def pg_cursor_for_raw_mutation(
    authority: object,
    *,
    record_id: str,
    content_identity: Optional[str] = None,
) -> Any:
    validated = require_raw_mutation_authority(
        authority,
        record_id=record_id,
        content_identity=content_identity,
    )
    if validated.backend != "pg" or validated._cursor is None:
        raise RawLivenessUnavailableError("PostgreSQL mutation authority is unavailable")
    return validated._cursor


def _checkpoint_raw_mutation_authority(authority: object) -> None:
    """Commit a durable PG producer checkpoint without releasing its fence.

    The PG relocation fence is session-scoped, so committing an inactive cold
    reservation leaves retirement blocked on the same identity while making
    the reservation visible as crash/restart cleanup authority. Memory writes
    are already durable for the lifetime of their single process fence.
    """

    validated = require_raw_mutation_authority(
        authority,
        record_id=(authority.record_id if isinstance(authority, RawMutationAuthority) else ""),
    )
    if validated.backend == "memory":
        return
    if validated._cursor is None:
        raise RawLivenessUnavailableError("PostgreSQL mutation authority is unavailable")
    validated._cursor.connection.commit()


def content_identity_for_raw_record(record_id: str) -> str:
    """Resolve only durable identity metadata before acquiring its work fence."""

    if resolve_heimdal_backend() == "memory":
        with _MEMORY_FENCE:
            generation = _MEMORY.generations_by_record.get(record_id)
            if generation is None:
                raise RawLivenessUnavailableError(
                    "raw identity has no durable liveness generation"
                )
            if record_id in _MEMORY.tombstones_by_record:
                raise RawEvidenceErasedError(_MEMORY.tombstones_by_record[record_id])
            return generation.content_identity
    conn = _pg_connect(autocommit=True)
    try:
        _assert_pg_schema(conn)
        cur = conn.cursor()
        cur.execute(
            f"SELECT content_identity FROM {_GENERATION_TABLE} WHERE record_id = %s",
            (record_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise RawLivenessUnavailableError(
                "raw identity has no durable liveness generation"
            )
        cur.execute(f"SELECT 1 FROM {_TOMBSTONE_TABLE} WHERE record_id = %s", (record_id,))
        if cur.fetchone() is not None:
            raise RawEvidenceErasedError(_load_pg_tombstone(cur, record_id=record_id))
        return str(row[0])
    finally:
        conn.close()


@contextmanager
def raw_relocation_fence(
    *, record_id: str, content_identity: str
) -> Iterator[RawMutationAuthority]:
    """Fence one relocation against retention for its exact live generation.

    The fence spans durable cold reservation, external writes, verification,
    and activation.  Retention takes the same authority before it captures
    cold cleanup refs, so it can never commit between an external write and
    the registry state that makes that write discoverable.
    """

    if resolve_heimdal_backend() == "memory":
        with _MEMORY_FENCE:
            generation = assert_memory_generation_active(
                record_id=record_id,
                content_identity=content_identity,
            )
            authority = RawMutationAuthority(
                _issuer=_MUTATION_AUTHORITY_ISSUER,
                record_id=record_id,
                content_identity=content_identity,
                generation=generation.generation,
                backend="memory",
            )
            _activate_mutation_authority(authority)
            try:
                yield authority
            finally:
                _deactivate_mutation_authority(authority)
        return

    conn = _pg_connect(autocommit=False)
    try:
        _assert_pg_schema(conn)
        cur = conn.cursor()
        cur.execute(
            "SELECT pg_advisory_lock(hashtextextended(%s, 0))",
            (content_identity,),
        )
        generation = assert_pg_generation_active(
            cur,
            record_id=record_id,
            content_identity=content_identity,
        )
        authority = RawMutationAuthority(
            _issuer=_MUTATION_AUTHORITY_ISSUER,
            record_id=record_id,
            content_identity=content_identity,
            generation=generation.generation,
            backend="pg",
            cursor=cur,
        )
        _activate_mutation_authority(authority)
        try:
            yield authority
        finally:
            _deactivate_mutation_authority(authority)
        conn.commit()
        cur.execute(
            "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
            (content_identity,),
        )
        cur.fetchone()
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


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


def _load_pg_retention_claim(cur: Any, *, record_id: str) -> Optional[RawRetentionClaim]:
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
                   AND p.raw_generation = %s
                   AND (
                       (p.storage_kind = 'postgres_hot'
                        AND p.archive_token IS NULL
                        AND p.archive_generation IS NULL)
                       OR
                       (p.storage_kind = 'encrypted_local_cold'
                        AND p.archive_token IS NOT NULL
                        AND p.archive_generation IS NOT NULL
                        AND p.location_ref LIKE
                            'heimloc:cold:' || p.archive_token || ':%%')
                   )
               )
        FROM heimdal_raw_record AS r
        LEFT JOIN heimdal_raw_representation AS p ON p.record_id = r.id
        WHERE r.id = %s AND r.content_identity = %s
        GROUP BY r.id
        """,
        (generation.generation, generation.record_id, generation.content_identity),
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
    its exact generation has a governed tombstone and no pending cold cleanup.
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
            cur.execute(f"SELECT 1 FROM {_TOMBSTONE_TABLE} WHERE record_id = %s", (record_id,))
            tombstoned = cur.fetchone() is not None
            raw_active = _pg_exact_active(cur, generation)
            if tombstoned:
                if _pg_raw_exists(cur, record_id):
                    raise RawLivenessUnavailableError(
                        "tombstoned raw generation still has durable raw state"
                    )
                tombstone = _load_pg_tombstone(cur, record_id=record_id)
                cur.execute(
                    f"SELECT payload FROM {_DELETION_RECEIPT_TABLE} WHERE id = %s",
                    (tombstone.deletion_receipt_id,),
                )
                receipt_row = cur.fetchone()
                if receipt_row is None:
                    raise RawLivenessUnavailableError(
                        "tombstoned raw generation has no matching deletion receipt"
                    )
                receipt_payload = (
                    receipt_row[0]
                    if isinstance(receipt_row[0], dict)
                    else json.loads(receipt_row[0] or "{}")
                )
                projections[raw_ref] = RawLivenessProjection(
                    outcome=(
                        "erasure_pending"
                        if receipt_payload.get(_COLD_CLEANUP_PAYLOAD_KEY)
                        else "erased"
                    ),
                    generation=generation,
                    tombstone=tombstone,
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
    if projection.outcome == "erasure_pending":
        raise RawLivenessUnavailableError(
            "raw evidence erasure is pending durable cold cleanup"
        )
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


def _cold_cleanup_binding(
    payload: Mapping[str, Any],
    location_ref: str,
    *,
    expected_raw_generation: int,
) -> tuple[str, str, str]:
    bindings = payload.get(_COLD_CLEANUP_BINDINGS_PAYLOAD_KEY)
    binding = bindings.get(location_ref) if isinstance(bindings, dict) else None
    if not isinstance(binding, dict):
        raise RawLivenessUnavailableError(
            "cold cleanup item lacks durable archive binding"
        )
    archive_token = binding.get("archive_token")
    archive_generation = binding.get("archive_generation")
    raw_generation = binding.get("raw_generation")
    representation_id = binding.get("representation_id")
    try:
        canonical_representation_id = str(UUID(str(representation_id)))
    except (TypeError, ValueError, AttributeError):
        canonical_representation_id = ""
    if (
        not isinstance(archive_token, str)
        or re.fullmatch(r"[0-9a-f]{64}", archive_token) is None
        or not isinstance(archive_generation, str)
        or re.fullmatch(r"[0-9a-f]{64}", archive_generation) is None
        or raw_generation != expected_raw_generation
        or canonical_representation_id != representation_id
        or location_ref
        != f"heimloc:cold:{archive_token}:{canonical_representation_id}"
    ):
        raise RawLivenessUnavailableError(
            "cold cleanup item is stale or bound to a different generation"
        )
    return archive_token, archive_generation, canonical_representation_id


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
        archive_token, archive_generation, representation_id = _cold_cleanup_binding(
            receipt.payload,
            str(location_ref),
            expected_raw_generation=tombstone.generation,
        )
        cleanup_binding = receipt.payload[_COLD_CLEANUP_BINDINGS_PAYLOAD_KEY][str(location_ref)]
        try:
            raw_store._delete_bound_cold_object(  # noqa: SLF001
                str(location_ref),
                expected_archive_token=archive_token,
                expected_archive_generation=archive_generation,
                expected_raw_generation=tombstone.generation,
                expected_representation_id=representation_id,
                expected_record_id=cleanup_binding.get("record_id"),
                expected_content_identity=cleanup_binding.get("content_identity"),
                expected_nonce=(
                    bytes.fromhex(cleanup_binding["nonce_hex"])
                    if cleanup_binding.get("nonce_hex")
                    else None
                ),
            )
        except raw_store.RawRepresentationDeletionError:
            raise
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
    correlation_grant_ref: Optional[str],
) -> GovernedDeletionResult:
    from app.heimdal import raw_store

    _retention_fence_hook(record_id)
    with _MEMORY_FENCE:
        generation = _MEMORY.generations_by_record.get(record_id)
        if generation is None:
            raise RawLivenessUnavailableError("retention target has no durable liveness generation")
        existing_tombstone = _MEMORY.tombstones_by_record.get(record_id)
        raw_active = _memory_raw_is_exact_active(generation)
        if existing_tombstone is not None:
            _reconcile_memory_cold_cleanup(existing_tombstone)
            if raw_active:
                raise RawLivenessUnavailableError(
                    "tombstoned retention target still has active raw state"
                )
            return GovernedDeletionResult(outcome="already_erased", tombstone=existing_tombstone)
        _assert_new_deletion_payload(payload)
        if not raw_active:
            raise RawLivenessUnavailableError(
                "untombstoned retention target is missing its active representation"
            )
        governed_payload = _governed_deletion_payload(
            payload,
            grant_refs=raw_store.raw_record_consent_grant_refs(record_id),
            correlation_grant_ref=correlation_grant_ref,
            raw_modality=raw_store.raw_record_modality(record_id),
        )
        reference_time = _as_utc(deleted_at)
        claim_was_new = record_id not in _MEMORY.retention_claims_by_record
        claim = _memory_claim_retention_locked(
            generation=generation,
            reason=reason,
            retention_window_days=retention_window_days,
            claimed_at=reference_time,
            payload=governed_payload,
        )
        if reference_time < claim.drain_after:
            return GovernedDeletionResult(outcome="lease_valid")

        receipt = _new_receipt(
            record_id=record_id,
            content_identity=generation.content_identity,
            reason=reason,
            retention_window_days=retention_window_days,
            deleted_at=reference_time,
            payload=governed_payload,
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
        cold_bindings: Dict[str, Dict[str, Any]] = {}
        for representation in raw_store.all_raw_representations(record_id):
            if representation.storage_kind == "encrypted_local_cold":
                if (
                    not representation.archive_token
                    or not representation.archive_generation
                    or representation.raw_generation != generation.generation
                ):
                    raise RawLivenessUnavailableError(
                        "cold representation lacks exact archive/generation authority"
                    )
                cold_bindings[representation.location_ref] = {
                    "archive_token": representation.archive_token,
                    "archive_generation": representation.archive_generation,
                    "raw_generation": representation.raw_generation,
                    "representation_id": representation.id,
                    "record_id": record_id,
                    "content_identity": generation.content_identity,
                    "nonce_hex": representation.nonce.hex(),
                }
        # Presence is owner-native evidence: an explicit empty queue means the
        # producer verified that this generation had no cold copies.  Absence
        # remains reserved for legacy/unknown receipts and must fail closed in
        # GAF cleanup projection.
        receipt.payload[_COLD_CLEANUP_PAYLOAD_KEY] = list(cold_bindings)
        if cold_bindings:
            receipt.payload[_COLD_CLEANUP_BINDINGS_PAYLOAD_KEY] = cold_bindings
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
        return GovernedDeletionResult(outcome="deleted", receipt=receipt, tombstone=tombstone)


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
        f"SELECT deletion_receipt_id, generation FROM {_TOMBSTONE_TABLE} WHERE record_id = %s",
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
        archive_token, archive_generation, representation_id = _cold_cleanup_binding(
            payload,
            location_ref,
            expected_raw_generation=int(tombstone_row[1]),
        )
        cleanup_binding = payload[_COLD_CLEANUP_BINDINGS_PAYLOAD_KEY][location_ref]
        try:
            raw_store._delete_bound_cold_object(  # noqa: SLF001
                location_ref,
                expected_archive_token=archive_token,
                expected_archive_generation=archive_generation,
                expected_raw_generation=int(tombstone_row[1]),
                expected_representation_id=representation_id,
                expected_record_id=cleanup_binding.get("record_id"),
                expected_content_identity=cleanup_binding.get("content_identity"),
                expected_nonce=(
                    bytes.fromhex(cleanup_binding["nonce_hex"])
                    if cleanup_binding.get("nonce_hex")
                    else None
                ),
            )
        except raw_store.RawRepresentationDeletionError as exc:
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
            raise exc
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
    correlation_grant_ref: Optional[str],
) -> GovernedDeletionResult:
    from app.heimdal import raw_store

    conn = _pg_connect(autocommit=False)
    try:
        raw_store._assert_pg_schema(conn)  # noqa: SLF001
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT g.content_identity
            FROM {_GENERATION_TABLE} AS g
            WHERE g.record_id = %s
            """,
            (record_id,),
        )
        identity_row = cur.fetchone()
        if identity_row is None:
            raise RawLivenessUnavailableError("retention target has no durable liveness generation")
        content_identity = str(identity_row[0])
        _retention_fence_hook(record_id)
        acquire_pg_fence(cur, content_identity)
        generation = _load_pg_generation(cur, record_id=record_id)
        assert generation is not None
        cur.execute(f"SELECT 1 FROM {_TOMBSTONE_TABLE} WHERE record_id = %s", (record_id,))
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
        _assert_new_deletion_payload(payload)
        if not raw_active:
            raise RawLivenessUnavailableError(
                "untombstoned retention target is missing its active representation"
            )
        cur.execute(
            f"SELECT bool_or(legacy_lineage_ambiguous) "
            f"FROM {_CONSENT_ASSOCIATION_TABLE} WHERE record_id = %s",
            (record_id,),
        )
        lineage_row = cur.fetchone()
        legacy_lineage_ambiguous = bool(lineage_row and lineage_row[0])
        governed_payload = _governed_deletion_payload(
            payload,
            grant_refs=(
                str(row[0])
                for row in cur.execute(
                    f"SELECT grant_ref FROM {_CONSENT_ASSOCIATION_TABLE} "
                    "WHERE record_id = %s ORDER BY sequence",
                    (record_id,),
                ).fetchall()
            ),
            correlation_grant_ref=correlation_grant_ref,
            raw_modality=raw_store.raw_record_modality(record_id),
            legacy_lineage_ambiguous=legacy_lineage_ambiguous,
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
                    json.dumps(governed_payload),
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

        cold_location_refs: list[str] = []
        cold_bindings: Dict[str, Dict[str, Any]] = {}
        try:
            cur.execute(
                "SELECT 1 FROM heimdal_raw_record WHERE id = %s FOR UPDATE",
                (record_id,),
            )
            if cur.fetchone() is None:
                raise RawLivenessUnavailableError(
                    "raw identity disappeared before governed deletion"
                )
            cur.execute(
                """
                SELECT p.id, p.location_ref, p.archive_token, p.archive_generation,
                       p.raw_generation, p.nonce, r.content_identity
                FROM heimdal_raw_representation AS p
                JOIN heimdal_raw_record AS r ON r.id = p.record_id
                WHERE p.record_id = %s AND p.storage_kind = 'encrypted_local_cold'
                ORDER BY p.sequence
                FOR UPDATE
                """,
                (record_id,),
            )
            for (
                representation_id,
                location_ref,
                archive_token,
                archive_generation,
                raw_generation,
                nonce,
                representation_content_identity,
            ) in cur.fetchall():
                if (
                    not archive_token
                    or not archive_generation
                    or int(raw_generation) != generation.generation
                ):
                    raise RawLivenessUnavailableError(
                        "cold representation lacks exact archive/generation authority"
                    )
                ref = str(location_ref)
                cold_location_refs.append(ref)
                cold_bindings[ref] = {
                    "archive_token": str(archive_token),
                    "archive_generation": str(archive_generation),
                    "raw_generation": int(raw_generation),
                    "representation_id": str(representation_id),
                    "record_id": record_id,
                    "content_identity": str(representation_content_identity),
                    "nonce_hex": bytes(nonce).hex(),
                }
        except Exception as exc:
            raise raw_store.RawRepresentationDeletionError(
                "governed all-copy deletion failed; no identity was removed"
            ) from exc

        receipt_payload = dict(governed_payload)
        # Persist explicit verification even for hot-only erasure.  A missing
        # field is legacy/unknown evidence, not an empty cleanup queue.
        receipt_payload[_COLD_CLEANUP_PAYLOAD_KEY] = cold_location_refs
        if cold_location_refs:
            receipt_payload[_COLD_CLEANUP_BINDINGS_PAYLOAD_KEY] = cold_bindings
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
                json.dumps(receipt_payload),
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
        try:
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
        return GovernedDeletionResult(outcome="deleted", receipt=receipt, tombstone=tombstone)
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
    consent_grant_ref: Optional[str] = None,
) -> GovernedDeletionResult:
    """Apply the one fenced, receipted raw-erasure transaction."""

    if resolve_heimdal_backend() == "memory":
        result = _governed_delete_memory(
            record_id=record_id,
            reason=reason,
            retention_window_days=retention_window_days,
            deleted_at=deleted_at,
            payload=dict(payload or {}),
            correlation_grant_ref=consent_grant_ref,
        )
    else:
        result = _governed_delete_pg(
            record_id=record_id,
            reason=reason,
            retention_window_days=retention_window_days,
            deleted_at=deleted_at,
            payload=dict(payload or {}),
            correlation_grant_ref=consent_grant_ref,
        )
    return GovernedDeletionResult(
        outcome=result.outcome,
        receipt=_copy_deletion_receipt(result.receipt) if result.receipt is not None else None,
        tombstone=result.tombstone,
    )


def _copy_deletion_receipt(receipt: DeletionReceipt) -> DeletionReceipt:
    """Return a detached receipt so callers cannot mutate cleanup authority."""

    return DeletionReceipt(
        id=receipt.id,
        record_id=receipt.record_id,
        content_identity=receipt.content_identity,
        reason=receipt.reason,
        retention_window_days=receipt.retention_window_days,
        deleted_at=receipt.deleted_at,
        payload=copy.deepcopy(receipt.payload),
        sequence=receipt.sequence,
        receipted=receipt.receipted,
    )


def cold_cleanup_location_is_pending(location_ref: str) -> bool:
    """Return whether durable cleanup still exclusively owns an opaque ref."""

    if not isinstance(location_ref, str) or not location_ref:
        raise ValueError("location_ref must be non-empty")
    if resolve_heimdal_backend() == "memory":
        with _MEMORY_FENCE:
            return any(
                location_ref
                in receipt.payload.get(_COLD_CLEANUP_PAYLOAD_KEY, [])
                for receipt in _MEMORY.deletion_receipts
            )
    conn = _pg_connect(autocommit=True)
    try:
        _assert_pg_schema(conn)
        cur = conn.cursor()
        cur.execute(
            f"SELECT 1 FROM {_DELETION_RECEIPT_TABLE} "
            f"WHERE COALESCE(payload->'{_COLD_CLEANUP_PAYLOAD_KEY}', '[]'::jsonb) ? %s "
            "LIMIT 1",
            (location_ref,),
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def all_deletion_receipts() -> list[DeletionReceipt]:
    if resolve_heimdal_backend() == "memory":
        with _MEMORY_FENCE:
            return [_copy_deletion_receipt(receipt) for receipt in _MEMORY.deletion_receipts]
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
        cur.execute(f"SELECT record_id FROM {_TOMBSTONE_TABLE} ORDER BY sequence")
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
        cur.execute(f"SELECT record_id FROM {_RETENTION_CLAIM_TABLE} ORDER BY sequence")
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
    "CONSENT_GRANT_DIGEST_PAYLOAD_KEY",
    "CONSENT_GRANT_DIGESTS_PAYLOAD_KEY",
    "DeletionReceipt",
    "GovernedDeletionResult",
    "RAW_MODALITY_PAYLOAD_KEY",
    "cold_cleanup_location_is_pending",
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
    "consent_grant_digest",
    "governed_delete_raw_record",
    "issue_response_lease",
    "project_with_response_leases",
    "raw_relocation_fence",
    "reset_memory_deletion_receipts",
]
