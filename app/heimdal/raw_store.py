"""Heimdal raw-evidence identity + registered representation store (#3025/#3848).

Slice A6 of Epic #3019 (Heimdal v1). Ratified by
`docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md` §1 and
specified by `docs/HEIMDAL/FABLE_COMPANION.md` §11#5/§11#6 (voice-memo
capture adapter writes the raw record; the gated *read* path over this
store is `app/heimdal/raw_read_gate.py`, slice A7, #3027).

Contract:

- **Immutable identity/provenance (HEIM-1).** `heimdal_raw_record` rows are
  inserted and never updated. Encrypted copies live separately in
  `heimdal_raw_representation`; ordinary callers can register a Postgres-hot
  copy and guarded code may switch which registered copy is active without
  rewriting identity or provenance. **One governed exception exists by design (D-RETENTION,
  Charter FIXED #7):** the raw layer is the one place true erasure exists,
  and its execution must be receipted, never silent or unbounded. That
  exception is the fenced transaction in `app.heimdal.raw_liveness`: the only
  path that can append a governed tombstone and deletion receipt while removing
  every registered representation and the identity in one commit. Both
  retention writers use that transaction.
- **Encrypted at rest.** Every representation is encrypted with AES-256-GCM
  (authenticated encryption) before it is written; plaintext raw bytes never
  touch the store or either backing table. The store never generates or
  manages key material -- the caller (the capture adapter) supplies the key
  once per process from `HEIMDAL_RAW_STORE_KEY` (see
  :func:`resolve_raw_store_key`), so the store itself has no ambient
  decrypt capability beyond what its caller already holds.
- **Identity, provenance, and the initial representation land atomically
  (KERNEL-06).** `insert_raw_record` writes `content_identity`,
  `capture_chain`, `sensor`, and `consent` in the same transaction as the
  initial registered Postgres-hot representation -- there is no "stamp
  provenance later" call. FABLE_COMPANION §1.1 provenance field table:
  `content_identity` is the hash of the **raw** evidence (KAP-compatible
  join key); `capture_chain` lists every hop the evidence took before
  Heimdal; `sensor` identifies the capture adapter instance (T5 mitigation,
  a caller-supplied registered identity -- this module does not validate
  registration, that is `app.heimdal.capture_adapter`'s job); `consent`
  carries the resolved `grant_ref` (HEIM-3).
- **Idempotent by `content_identity`.** The same raw evidence (same hash)
  writing twice (e.g. a crash-retry before delete-after-ingest fired) does
  not produce a duplicate row -- the Postgres backend enforces this with a
  unique index, and the memory backend mirrors it in Python, so a caller
  can safely retry `insert_raw_record` after a partial failure without
  double-admitting the same memo.

Backend selection mirrors `app.heimdal.observation_log` /
`app.heimdal.consent_ledger` (dual-backend, fail-loud resolution via
`app.heimdal._backend.resolve_heimdal_backend`): ``STORE_BACKEND=memory``
(or no Postgres DSN configured) uses an in-process append-only list; a
resolvable Postgres DSN uses the migration-owned identity and representation
tables. Runtime preflight refuses an incomplete legacy backfill or unsupported
active representation; it never falls back to inline bytes or a caller path.

HAR-04 adds the mounted-cold file resolver and live relocation. Key
management/rotation remains out of scope. The gated read
path (allowlist + receipt evaluation over the active registry entry) is
`app/heimdal/raw_read_gate.py` (A7, #3027, evolved by #3848).
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterator, List, Optional
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.heimdal._backend import resolve_heimdal_backend

_TABLE = "heimdal_raw_record"
_REPRESENTATION_TABLE = "heimdal_raw_representation"
_CONSENT_ASSOCIATION_TABLE = "heimdal_raw_consent_association"
_GENERATION_TABLE = "heimdal_raw_liveness_generation"
_TOMBSTONE_TABLE = "heimdal_raw_deletion_tombstone"
_RETENTION_CLAIM_TABLE = "heimdal_raw_retention_claim"
_DELETION_RECEIPT_TABLE = "heimdal_raw_deletion_receipt"

_MIGRATION_HINT = (
    "the location-aware Heimdal raw schema is migration-owned: run "
    "'alembic upgrade head' against this database. See revisions "
    "e7b4c9d2a6f1, c5d8a1e4f2b7, e2f3a4b5c6d7, f4b6c8d0e2a1, "
    "and a9d7c5e3b1f0."
)

_KEY_ENV_VAR = "HEIMDAL_RAW_STORE_KEY"
_AES_KEY_BYTES = 32  # AES-256
_NONCE_BYTES = 12  # standard AES-GCM nonce size

# Session-local Postgres setting the append-only trigger admits a DELETE
# under (D-RETENTION governed exception). It is set only by the transaction in
# `raw_liveness.governed_delete_raw_record`, after the tombstone is present.
_RETENTION_GUARD_SETTING = "app.heimdal_retention_bypass"
_REPRESENTATION_ACTIVATION_GUARD_SETTING = "app.heimdal_representation_activation"
_HOT_STORAGE_KIND = "postgres_hot"
_COLD_STORAGE_KIND = "encrypted_local_cold"
_LOCATION_REF_PREFIX = "heimloc:"
_COLD_ARCHIVE_ROOT_ENV = "HEIMDAL_ARCHIVE_ROOT"
_COLD_ARCHIVE_MUTATION_LOCK = ".heimdal-archive-mutation.lock"
_COLD_LOCATION_CONSTRAINT = "heimdal_raw_representation_cold_location_bound_check"
_ARCHIVE_GENERATION_CONSTRAINT = "heimdal_raw_representation_archive_generation_check"
_COLD_OWNER_CONSTRAINT = "heimdal_raw_representation_cold_owner_check"
_GENERATION_FK_CONSTRAINT = "heimdal_raw_representation_generation_fk"
_COLD_LOCATION_REF_PATTERN = (
    r"^heimloc:cold:[0-9a-f]{64}:"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_COLD_LOCATION_REF_RE = re.compile(_COLD_LOCATION_REF_PATTERN)


@dataclass(frozen=True)
class _ColdArchiveBinding:
    archive_root: Path
    archive_token: str
    archive_generation: str


@dataclass(frozen=True)
class _ColdObjectOwnership:
    location_ref: str
    archive_token: str
    archive_generation: str
    raw_generation: int
    representation_id: str
    record_id: str | None = None
    content_identity: str | None = None
    nonce: bytes | None = None


@dataclass(frozen=True)
class _ColdBindingSnapshot:
    """Immutable process authority captured before taking the archive lock."""

    binding: _ColdArchiveBinding
    expected: _ColdObjectOwnership
    object_path: Path
    cached_path: Path | None
    cached_ownership: _ColdObjectOwnership | None


_cold_location_paths: Dict[str, Path] = {}
_cold_location_ownership: Dict[str, _ColdObjectOwnership] = {}
_COLD_BINDING_LOCK = threading.RLock()
_verified_cold_archive_binding: _ColdArchiveBinding | None = None
_expected_cold_delete_ownership: ContextVar[_ColdObjectOwnership | None] = ContextVar(
    "heimdal_expected_cold_delete_ownership",
    default=None,
)
_expected_cold_delete_snapshot: ContextVar[_ColdBindingSnapshot | None] = ContextVar(
    "heimdal_expected_cold_delete_snapshot",
    default=None,
)
_cold_archive_lock_held: ContextVar[bool] = ContextVar(
    "heimdal_cold_archive_lock_held",
    default=False,
)
_cold_read_stage_hook: Callable[[str, str], None] = lambda _stage, _location_ref: None
_cold_delete_stage_hook: Callable[[str, Path], None] = lambda _stage, _path: None
_MEMORY_ARCHIVE_RELOCATION_LEASE = threading.Lock()
_ARCHIVE_RELOCATION_ADVISORY_LOCK = int.from_bytes(
    hashlib.sha256(b"heimdal.har04.archive-relocation").digest()[:8],
    byteorder="big",
    signed=True,
)


class RawStoreSchemaMissingError(RuntimeError):
    """Raised when the Postgres backend is selected but the raw table/columns are absent."""


class RawRepresentationUnavailableError(RuntimeError):
    """Raised when an identity has no single readable active representation."""


class RawRepresentationDeletionError(RuntimeError):
    """Raised when governed all-representation erasure cannot complete atomically."""


class RawRepresentationIdentityMismatchError(RuntimeError):
    """Raised when encrypted representation bytes do not match immutable identity."""


class RawArchiveRelocationLeaseUnavailableError(RuntimeError):
    """Raised when another bounded HAR-04 relocation pass owns the run lease."""


RAW_MODALITY_UNSPECIFIED = "unspecified"
_RAW_MODALITY_RE = re.compile(r"[a-z][a-z0-9_-]{0,63}")


def canonical_raw_modality(value: object) -> str:
    """Return one non-secret canonical modality for retirement receipts."""

    if value is None:
        return RAW_MODALITY_UNSPECIFIED
    if not isinstance(value, str) or _RAW_MODALITY_RE.fullmatch(value) is None:
        raise RawRepresentationUnavailableError(
            "raw record modality metadata is not canonical"
        )
    return value


def _archive_binding_token(archive_ref: str) -> str:
    """Return the opaque stable binding persisted in cold location handles."""

    if not archive_ref:
        raise ValueError("archive_ref must be non-empty")
    return hashlib.sha256(archive_ref.encode("utf-8")).hexdigest()


def _cold_location_ref(archive_ref: str, representation_id: str) -> str:
    """Build one archive-bound opaque location handle."""

    from uuid import UUID

    try:
        canonical_id = str(UUID(representation_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("cold representation id must be a canonical UUID") from exc
    if canonical_id != representation_id:
        raise ValueError("cold representation id must be a canonical UUID")
    return f"{_LOCATION_REF_PREFIX}cold:{_archive_binding_token(archive_ref)}:{canonical_id}"


def _parse_cold_location_ref(location_ref: str) -> tuple[str, str] | None:
    if _COLD_LOCATION_REF_RE.fullmatch(location_ref) is None:
        return None
    _prefix, _kind, archive_token, object_id = location_ref.split(":", 3)
    return archive_token, object_id


def _cold_location_constraint_is_ready(definition: str, validated: bool) -> bool:
    """Require the exact archive-bound cold-location CHECK semantics."""

    def normalize(value: str) -> str:
        return (
            re.sub(r"\s+", "", value.lower())
            .replace("::text", "")
            .replace("(", "")
            .replace(")", "")
        )

    expected = (
        "CHECK (storage_kind <> 'encrypted_local_cold' OR "
        f"location_ref ~ '{_COLD_LOCATION_REF_PATTERN}')"
    )
    return validated and normalize(definition) == normalize(expected)


def _archive_generation_constraint_is_ready(definition: str, validated: bool) -> bool:
    def normalize(value: str) -> str:
        return (
            re.sub(r"\s+", "", value.lower())
            .replace("::text", "")
            .replace("~~", "like")
            .replace("(", "")
            .replace(")", "")
        )

    expected = (
        "CHECK ((storage_kind = 'postgres_hot' "
        "AND archive_token IS NULL AND archive_generation IS NULL) OR "
        "(storage_kind = 'encrypted_local_cold' "
        "AND archive_token ~ '^[0-9a-f]{64}$' "
        "AND (archive_generation ~ '^[0-9a-f]{64}$' OR archive_generation IS NULL) "
        "AND location_ref LIKE 'heimloc:cold:' || archive_token || ':%'))"
    )
    return validated and normalize(definition) == normalize(expected)


_REPRESENTATION_TRIGGER_BODY = (
    "if tg_op in ('insert', 'update') then "
    "select content_identity, generation into authority_identity, authority_generation "
    "from heimdal_raw_liveness_generation where record_id = new.record_id; "
    "if authority_identity is null or new.raw_generation is distinct from authority_generation then "
    "raise exception 'raw representation has no matching liveness generation'; end if; "
    "perform pg_advisory_xact_lock(hashtextextended(authority_identity, 0)); "
    "if exists (select 1 from heimdal_raw_retention_claim where record_id = new.record_id) "
    "or exists (select 1 from heimdal_raw_deletion_tombstone where record_id = new.record_id) then "
    "raise exception 'raw representation cannot mutate a retiring generation'; end if; "
    "if new.storage_kind = 'encrypted_local_cold' and exists (select 1 from heimdal_raw_deletion_receipt "
    "where coalesce(payload->'cold_cleanup_location_refs', '[]'::jsonb) ? new.location_ref) then "
    "raise exception 'cold location remains owned by pending governed cleanup'; end if; "
    "if tg_op = 'insert' then return new; end if; end if; "
    "if tg_op = 'update' and current_setting('app.heimdal_legacy_archive_reconcile', true) = 'true' "
    "and new.id is not distinct from old.id and new.record_id is not distinct from old.record_id "
    "and new.storage_kind is not distinct from old.storage_kind and new.location_ref is not distinct from old.location_ref "
    "and new.ciphertext is not distinct from old.ciphertext and new.nonce is not distinct from old.nonce "
    "and new.key_ref is not distinct from old.key_ref and new.raw_generation is not distinct from old.raw_generation "
    "and new.archive_token is not distinct from old.archive_token and old.archive_generation is null "
    "and new.archive_generation ~ '^[0-9a-f]{64}$' and new.registered_at is not distinct from old.registered_at "
    "and new.sequence is not distinct from old.sequence then return new; end if; "
    "if tg_op = 'update' and current_setting('app.heimdal_representation_activation', true) = 'true' "
    "and new.id is not distinct from old.id and new.record_id is not distinct from old.record_id "
    "and new.storage_kind is not distinct from old.storage_kind and new.location_ref is not distinct from old.location_ref "
    "and new.ciphertext is not distinct from old.ciphertext and new.nonce is not distinct from old.nonce "
    "and new.key_ref is not distinct from old.key_ref and new.raw_generation is not distinct from old.raw_generation "
    "and new.archive_token is not distinct from old.archive_token and new.archive_generation is not distinct from old.archive_generation "
    "and new.registered_at is not distinct from old.registered_at and new.sequence is not distinct from old.sequence then "
    "return new; end if; "
    "if tg_op = 'delete' and current_setting('app.heimdal_retention_bypass', true) = 'true' "
    "and exists (select 1 from heimdal_raw_deletion_tombstone where record_id = old.record_id) then "
    "return old; end if; "
    "raise exception 'heimdal_raw_representation mutation is governed: % is not permitted', tg_op;"
)


def _normalize_trigger_sql(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).lower().strip()
    normalized = re.sub(r"\s*->\s*", "->", normalized)
    normalized = re.sub(r"::text\b", "", normalized)
    normalized = re.sub(r"\(\s*", "(", normalized)
    normalized = re.sub(r"\s*\)", ")", normalized)
    return normalized


def _representation_guard_is_migration_ready(
    definition: str, trigger_definition: str
) -> bool:
    """Authenticate the exact guarded representation trigger and binding."""

    normalized = _normalize_trigger_sql(definition)
    trigger = _normalize_trigger_sql(trigger_definition)
    begin_matches = list(re.finditer(r"\bbegin\b", normalized, re.IGNORECASE))
    end_matches = list(re.finditer(r"\bend\s*;", normalized, re.IGNORECASE))
    body = (
        normalized[begin_matches[0].end() : end_matches[0].start()].strip()
        if len(begin_matches) == 1 and len(end_matches) == 1
        else ""
    )
    trigger_bound = re.fullmatch(
        r"create trigger heimdal_raw_representation_no_mutation "
        r"before ((?:insert|update|delete)(?: or (?:insert|update|delete)){2}) on "
        r"(?:[a-z_][a-z0-9_]*\.)?heimdal_raw_representation "
        r"for each row execute function "
        r"(?:[a-z_][a-z0-9_]*\.)?heimdal_raw_representation_reject_mutation\(\)",
        trigger,
    )
    expected_body = _normalize_trigger_sql(_REPRESENTATION_TRIGGER_BODY)
    return bool(
        body == expected_body
        and trigger_bound is not None
        and set(trigger_bound.group(1).split(" or ")) == {"insert", "update", "delete"}
    )


def _cold_owner_constraint_is_ready(definition: str, validated: bool) -> bool:
    """Require a cold locator's object UUID to equal its representation id."""

    def normalize(value: str) -> str:
        return (
            re.sub(r"\s+", "", value.lower())
            .replace("::text", "")
            .replace("(", "")
            .replace(")", "")
        )

    expected = (
        "CHECK (storage_kind <> 'encrypted_local_cold' OR "
        "location_ref = 'heimloc:cold:' || archive_token || ':' || id::text)"
    )
    return validated and normalize(definition) == normalize(expected)


def _require_verified_cold_volume(
    archive_root: Path, verified_volume: object, expected_archive_ref: str | None = None
) -> None:
    from app.ops.heimdal_cold_volume import (
        ArchiveVolumeReady,
        _is_verified_archive_volume_ready,
    )

    if (
        not isinstance(verified_volume, ArchiveVolumeReady)
        or not verified_volume.ready
        or verified_volume.mountpoint != archive_root
        or not _is_verified_archive_volume_ready(
            verified_volume, expected_archive_ref, archive_root
        )
    ):
        raise RawRepresentationDeletionError("verified cold volume proof is required")


def register_cold_location(
    location_ref: str,
    object_path: Path,
    *,
    verified_volume: object,
    raw_generation: int,
    representation_id: str,
) -> None:
    """Bind one exact cold owner under a verified-volume capability."""
    parsed = _parse_cold_location_ref(location_ref)
    if (
        parsed is None
        or not object_path.is_absolute()
        or object_path.name != f"{parsed[1]}.bin"
        or parsed[1] != representation_id
        or type(raw_generation) is not int
        or raw_generation <= 0
    ):
        raise ValueError("cold object path does not match its opaque location handle")
    archive_ref = getattr(verified_volume, "archive_ref", "")
    if parsed[0] != _archive_binding_token(str(archive_ref)):
        raise RawRepresentationDeletionError(
            "cold location is bound to a different archive identity"
        )
    _require_verified_cold_volume(
        object_path.parent.parent,
        verified_volume,
        expected_archive_ref=str(archive_ref),
    )
    archive_generation = str(getattr(verified_volume, "archive_generation", ""))
    ownership = _ColdObjectOwnership(
        location_ref=location_ref,
        archive_token=parsed[0],
        archive_generation=archive_generation,
        raw_generation=raw_generation,
        representation_id=representation_id,
    )
    from app.heimdal import raw_liveness

    if raw_liveness.cold_cleanup_location_is_pending(location_ref):
        raise RawRepresentationDeletionError(
            "cold location remains owned by pending governed cleanup"
        )
    with _COLD_BINDING_LOCK:
        binding = _verified_cold_archive_binding
        if (
            binding is None
            or binding.archive_root != object_path.parent.parent
            or binding.archive_token != parsed[0]
            or binding.archive_generation != archive_generation
        ):
            raise RawRepresentationDeletionError(
                "cold location proof does not match the active archive generation"
            )
        existing_path = _cold_location_paths.get(location_ref)
        existing_ownership = _cold_location_ownership.get(location_ref)
        if (
            existing_path is not None
            and (existing_path != object_path or existing_ownership != ownership)
        ):
            raise RawRepresentationDeletionError(
                "cold location is already bound to a different raw generation"
            )
        _cold_location_paths[location_ref] = object_path
        _cold_location_ownership[location_ref] = ownership


@contextmanager
def _cold_archive_mutation_lock(archive_root: Path, *, blocking: bool) -> Iterator[None]:
    """Serialize external writes and post-authority cleanup on the archive volume."""

    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    locked = False
    try:
        descriptor = os.open(archive_root / _COLD_ARCHIVE_MUTATION_LOCK, flags, 0o600)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("archive mutation lock is not a regular file")
        operation = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        fcntl.flock(descriptor, operation)
        locked = True
        yield
    except (BlockingIOError, OSError) as exc:
        raise RawRepresentationDeletionError("cold archive mutation lock is unavailable") from exc
    finally:
        if descriptor is not None:
            if locked:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                except OSError:
                    pass
            os.close(descriptor)


@contextmanager
def cold_archive_mutation_lock(archive_root: Path, *, verified_volume: object) -> Iterator[None]:
    """Hold the verified volume lock across reservation, copy, and activation."""

    _require_verified_cold_volume(archive_root, verified_volume)
    with _cold_archive_mutation_lock(archive_root, blocking=True):
        token = _cold_archive_lock_held.set(True)
        try:
            yield
        finally:
            _cold_archive_lock_held.reset(token)


def discard_cold_location(location_ref: str) -> None:
    """Forget a location handle when registration never reached raw authority."""
    with _COLD_BINDING_LOCK:
        _cold_location_paths.pop(location_ref, None)
        _cold_location_ownership.pop(location_ref, None)


def revoke_cold_archive_binding() -> None:
    """Revoke process-local cold authority before a failed restart rebind."""
    global _verified_cold_archive_binding
    with _COLD_BINDING_LOCK:
        _verified_cold_archive_binding = None
        _cold_location_paths.clear()
        _cold_location_ownership.clear()
    os.environ.pop(_COLD_ARCHIVE_ROOT_ENV, None)


@contextmanager
def archive_relocation_lease() -> Iterator[None]:
    """Serialize production HAR-04 passes across processes without row locks.

    The memory backend mirrors the contract with a non-blocking process lock.
    PostgreSQL uses one session advisory lock, so independently scheduled CLI
    processes cannot both copy and activate the same hot generation.  Closing
    the connection releases the lease after normal completion or a crash.
    """
    if resolve_heimdal_backend() == "memory":
        if not _MEMORY_ARCHIVE_RELOCATION_LEASE.acquire(blocking=False):
            raise RawArchiveRelocationLeaseUnavailableError(
                "another archive relocation pass is already running"
            )
        try:
            yield
        finally:
            _MEMORY_ARCHIVE_RELOCATION_LEASE.release()
        return

    conn = _pg_connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT pg_try_advisory_lock(%s)",
            (_ARCHIVE_RELOCATION_ADVISORY_LOCK,),
        )
        row = cur.fetchone()
        if row is None or row[0] is not True:
            raise RawArchiveRelocationLeaseUnavailableError(
                "another archive relocation pass is already running"
            )
        yield
    finally:
        # Session-level advisory locks are released even when the body raises
        # or the process loses the connection.  Avoid an unlock round-trip that
        # could mask the original fail-closed relocation error.
        conn.close()


def configure_cold_archive_root(
    archive_root: Path,
    *,
    verified_volume: object,
    expected_archive_ref: str | None = None,
) -> None:
    """Bind the verified archive root for cold reads after process restart."""
    if not archive_root.is_absolute():
        raise ValueError("cold archive root must be absolute")
    _require_verified_cold_volume(archive_root, verified_volume, expected_archive_ref)
    archive_ref = str(getattr(verified_volume, "archive_ref", ""))
    archive_token = _archive_binding_token(archive_ref)
    archive_generation = str(getattr(verified_volume, "archive_generation", ""))
    if re.fullmatch(r"[0-9a-f]{64}", archive_generation) is None:
        raise RawRepresentationDeletionError("verified archive generation is invalid")
    global _verified_cold_archive_binding
    with _COLD_BINDING_LOCK:
        _verified_cold_archive_binding = _ColdArchiveBinding(
            archive_root=archive_root,
            archive_token=archive_token,
            archive_generation=archive_generation,
        )
        # A rebind revokes every cache entry minted under the prior capability.
        _cold_location_paths.clear()
        _cold_location_ownership.clear()
    os.environ[_COLD_ARCHIVE_ROOT_ENV] = str(archive_root)


def reconcile_legacy_cold_representation(
    record_id: str,
    representation_id: str,
    *,
    verified_volume: object,
) -> None:
    """Bind one pre-HAR-05 cold row after proving its existing archive.

    HAR-04 persisted the archive token in the opaque location and in its
    redacted receipt, but HAR-05 adds the independently verified volume
    generation and manifest ownership state.  The migration therefore keeps
    bound legacy rows readable only as metadata; this explicit operator path
    upgrades one row after checking the mounted bytes and receipt.  No
    generation is guessed from the location token.
    """

    if resolve_heimdal_backend() != "pg":
        raise RawRepresentationDeletionError(
            "legacy cold reconciliation requires the PostgreSQL backend"
        )
    try:
        record_uuid = str(UUID(record_id))
        representation_uuid = str(UUID(representation_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("record_id and representation_id must be canonical UUIDs") from exc
    if record_uuid != record_id or representation_uuid != representation_id:
        raise ValueError("record_id and representation_id must be canonical UUIDs")
    _require_verified_cold_volume(
        Path(str(getattr(verified_volume, "mountpoint", ""))),
        verified_volume,
    )
    archive_root = Path(str(getattr(verified_volume, "mountpoint")))
    archive_ref = str(getattr(verified_volume, "archive_ref", ""))
    archive_token = _archive_binding_token(archive_ref)
    archive_generation = str(getattr(verified_volume, "archive_generation", ""))
    if re.fullmatch(r"[0-9a-f]{64}", archive_generation) is None:
        raise RawRepresentationDeletionError("verified archive generation is invalid")

    conn = _pg_connect(autocommit=False)
    try:
        _assert_pg_schema(conn, allow_legacy_reconciliation=True)
        cur = conn.cursor()
        cur.execute(
            f"SELECT p.record_id, r.content_identity, p.storage_kind, p.location_ref, "
            f"p.raw_generation, p.archive_token, p.archive_generation, p.nonce "
            f"FROM {_REPRESENTATION_TABLE} AS p "
            f"JOIN {_TABLE} AS r ON r.id = p.record_id "
            "WHERE p.id = %s",
            (representation_uuid,),
        )
        row = cur.fetchone()
        if row is None or str(row[0]) != record_uuid:
            raise RawRepresentationUnavailableError(
                "legacy cold representation is unavailable"
            )
        content_identity = str(row[1])
        from app.heimdal import raw_liveness

        # Retirement and reconciliation share the same content-identity
        # advisory fence. Acquire it before the representation row lock so a
        # concurrent governed delete cannot invert the lock order.
        raw_liveness.acquire_pg_fence(cur, content_identity)
        cur.execute(
            f"SELECT p.record_id, r.content_identity, p.storage_kind, p.location_ref, "
            f"p.raw_generation, p.archive_token, p.archive_generation, p.nonce "
            f"FROM {_REPRESENTATION_TABLE} AS p "
            f"JOIN {_TABLE} AS r ON r.id = p.record_id "
            "WHERE p.id = %s FOR UPDATE",
            (representation_uuid,),
        )
        row = cur.fetchone()
        if row is None or str(row[0]) != record_uuid:
            raise RawRepresentationUnavailableError(
                "legacy cold representation changed during reconciliation"
            )
        if row[2] != _COLD_STORAGE_KIND:
            raise RawRepresentationUnavailableError(
                "legacy reconciliation requires an encrypted local-cold representation"
            )
        location_ref = str(row[3])
        parsed = _parse_cold_location_ref(location_ref)
        if parsed is None or parsed[0] != archive_token or parsed[1] != representation_uuid:
            raise RawRepresentationUnavailableError(
                "legacy cold representation archive identity does not match the proof"
            )
        if row[6] is not None:
            if str(row[6]) != archive_generation:
                raise RawRepresentationUnavailableError(
                    "cold representation is bound to a different archive generation"
                )
            conn.commit()
            return
        if row[5] != archive_token:
            raise RawRepresentationUnavailableError(
                "legacy cold representation lacks the proven archive token"
            )

        from app.heimdal.local_archive import _durable_write

        manifest_path = archive_root / "manifests" / f"{representation_uuid}.json"
        object_path = archive_root / "representations" / f"{representation_uuid}.bin"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RawRepresentationUnavailableError(
                "legacy cold archive manifest is unavailable"
            ) from exc
        required = {
            "record_id": record_uuid,
            "representation_id": representation_uuid,
            "content_identity": content_identity,
        }
        try:
            receipt_id = str(UUID(str(manifest.get("receipt_id"))))
            verified_at = datetime.fromisoformat(
                str(manifest.get("verified_at", "")).replace("Z", "+00:00")
            )
            receipt_shape_valid = (
                manifest.get("schema") == "heimdal_archive_receipt.v1"
                and receipt_id == manifest.get("receipt_id")
                and verified_at.tzinfo is not None
            )
        except (TypeError, ValueError, AttributeError):
            receipt_shape_valid = False
        if (
            not object_path.is_file()
            or not isinstance(manifest, dict)
            or not receipt_shape_valid
            or any(manifest.get(key) != value for key, value in required.items())
            or manifest.get("encrypted_bytes") != object_path.stat().st_size
            or manifest.get("ciphertext_sha256")
            != hashlib.sha256(object_path.read_bytes()).hexdigest()
        ):
            raise RawRepresentationUnavailableError(
                "legacy cold archive proof does not match the representation"
            )
        ciphertext = object_path.read_bytes()
        decrypt_and_verify_raw_bytes(
            content_identity,
            ciphertext,
            bytes(row[7]),
            key=resolve_raw_store_key(),
        )
        # HAR-04 manifests are receipts, not ownership records: the archive
        # token, volume generation, and raw generation were durable only in
        # the registry/proof. Materialize those trusted values only after the
        # legacy receipt and ciphertext have been independently verified.
        manifest.update(
            {
                "location_ref": location_ref,
                "archive_token": archive_token,
                "archive_generation": archive_generation,
                "raw_generation": int(row[4]),
            }
        )
        manifest["ownership_state"] = "verified"
        _durable_write(
            manifest_path,
            (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        )
        cur.execute(
            "SELECT set_config('app.heimdal_legacy_archive_reconcile', 'true', true)"
        )
        cur.execute(
            f"UPDATE {_REPRESENTATION_TABLE} SET archive_generation = %s "
            "WHERE id = %s AND archive_generation IS NULL",
            (archive_generation, representation_uuid),
        )
        if cur.rowcount != 1:
            raise RawRepresentationUnavailableError(
                "legacy cold representation changed during reconciliation"
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _snapshot_cold_binding(
    location_ref: str,
    *,
    expected_archive_token: str,
    expected_archive_generation: str,
    expected_raw_generation: int,
    expected_representation_id: str,
    expected_record_id: str | None = None,
    expected_content_identity: str | None = None,
    expected_nonce: bytes | None = None,
) -> _ColdBindingSnapshot | None:
    """Capture one exact binding/cache view without performing archive I/O."""

    parsed = _parse_cold_location_ref(location_ref)
    expected = _ColdObjectOwnership(
        location_ref=location_ref,
        archive_token=expected_archive_token,
        archive_generation=expected_archive_generation,
        raw_generation=expected_raw_generation,
        representation_id=expected_representation_id,
        record_id=expected_record_id,
        content_identity=expected_content_identity,
        nonce=expected_nonce,
    )
    with _COLD_BINDING_LOCK:
        binding = _verified_cold_archive_binding
        if (
            parsed is None
            or parsed[0] != expected_archive_token
            or binding is None
            or binding.archive_token != expected_archive_token
            or binding.archive_generation != expected_archive_generation
            or parsed[1] != expected_representation_id
        ):
            return None
        cached_path = _cold_location_paths.get(location_ref)
        cached_ownership = _cold_location_ownership.get(location_ref)
        # The path cache is optional across a restart; the ownership cache may
        # still be present while the path entry is rebuilt from the verified
        # archive binding.  The inverse state (a path without its ownership)
        # is ambiguous and must fail closed.
        if cached_path is not None and cached_ownership is None:
            return None
        if cached_ownership is not None and (
            cached_ownership.location_ref != expected.location_ref
            or cached_ownership.archive_token != expected.archive_token
            or cached_ownership.archive_generation != expected.archive_generation
            or cached_ownership.raw_generation != expected.raw_generation
            or cached_ownership.representation_id != expected.representation_id
        ):
            return None
        object_path = cached_path or (
            binding.archive_root / "representations" / f"{expected_representation_id}.bin"
        )
        return _ColdBindingSnapshot(
            binding=binding,
            expected=expected,
            object_path=object_path,
            cached_path=cached_path,
            cached_ownership=cached_ownership,
        )


def _cold_binding_snapshot_is_current(snapshot: _ColdBindingSnapshot) -> bool:
    """Revalidate one snapshot while the caller holds ``_COLD_BINDING_LOCK``."""

    return (
        _verified_cold_archive_binding == snapshot.binding
        and _cold_location_paths.get(snapshot.expected.location_ref) == snapshot.cached_path
        and _cold_location_ownership.get(snapshot.expected.location_ref)
        == snapshot.cached_ownership
    )


def _resolve_cold_ciphertext(
    location_ref: str,
    *,
    expected_archive_token: str,
    expected_archive_generation: str,
    expected_raw_generation: int,
    expected_representation_id: str,
) -> bytes:
    snapshot = _snapshot_cold_binding(
        location_ref,
        expected_archive_token=expected_archive_token,
        expected_archive_generation=expected_archive_generation,
        expected_raw_generation=expected_raw_generation,
        expected_representation_id=expected_representation_id,
    )
    if snapshot is None:
        raise RawRepresentationUnavailableError(
            "cold representation archive identity/generation is unavailable"
        )
    _cold_read_stage_hook("after_binding_snapshot", location_ref)
    ciphertext: bytes | None = None
    try:

        def read_verified() -> bytes:
            # Canonical lock order is archive mutation lock, then binding lock.
            # Holding the latter through manifest/object I/O prevents a rebind
            # from invalidating the revalidated capability mid-read.
            with _COLD_BINDING_LOCK:
                if not _cold_binding_snapshot_is_current(snapshot):
                    raise RawRepresentationDeletionError(
                        "cold representation binding changed before archive read"
                    )
                _verify_cold_manifest_ownership(
                    snapshot.object_path,
                    snapshot.expected,
                )
                return snapshot.object_path.read_bytes()

        # Revalidate before trying to acquire the archive lock.  Relocation
        # publishes a new binding before taking that lock; returning here on
        # the changed snapshot avoids a binding/archive lock cycle.
        with _COLD_BINDING_LOCK:
            if not _cold_binding_snapshot_is_current(snapshot):
                raise RawRepresentationDeletionError(
                    "cold representation binding changed before archive lock"
                )
        if _cold_archive_lock_held.get():
            ciphertext = read_verified()
        else:
            with _cold_archive_mutation_lock(snapshot.binding.archive_root, blocking=True):
                _cold_read_stage_hook("after_archive_lock", location_ref)
                ciphertext = read_verified()
    except (OSError, RawRepresentationDeletionError):
        pass
    if ciphertext is None:
        raise RawRepresentationUnavailableError("cold representation bytes are unavailable")
    return ciphertext


def _cold_object_path(
    location_ref: str,
    *,
    expected_archive_token: str | None = None,
    expected_archive_generation: str | None = None,
    expected_raw_generation: int | None = None,
    expected_representation_id: str | None = None,
) -> Path | None:
    parsed = _parse_cold_location_ref(location_ref)
    with _COLD_BINDING_LOCK:
        binding = _verified_cold_archive_binding
        if (
            parsed is None
            or binding is None
            or parsed[0] != binding.archive_token
            or (
                expected_archive_token is not None
                and expected_archive_token != binding.archive_token
            )
            or (
                expected_archive_generation is not None
                and expected_archive_generation != binding.archive_generation
            )
            or (
                expected_representation_id is not None
                and parsed[1] != expected_representation_id
            )
        ):
            return None
        object_path = _cold_location_paths.get(location_ref)
        cached_ownership = _cold_location_ownership.get(location_ref)
        if cached_ownership is not None and (
            (
                expected_raw_generation is not None
                and cached_ownership.raw_generation != expected_raw_generation
            )
            or (
                expected_representation_id is not None
                and cached_ownership.representation_id != expected_representation_id
            )
            or cached_ownership.archive_token != binding.archive_token
            or cached_ownership.archive_generation != binding.archive_generation
        ):
            return None
        if object_path is not None:
            return object_path
        return binding.archive_root / "representations" / f"{parsed[1]}.bin"


def _verify_cold_manifest_ownership(
    object_path: Path,
    expected: _ColdObjectOwnership,
    *,
    allow_reserved: bool = False,
    allow_missing_object: bool = False,
) -> None:
    """Fail closed unless the redacted manifest owns this exact object tuple."""

    manifest_path = object_path.parent.parent / "manifests" / f"{object_path.stem}.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RawRepresentationDeletionError(
            "cold representation manifest ownership is unavailable"
        ) from exc
    required = {
        "location_ref": expected.location_ref,
        "archive_token": expected.archive_token,
        "archive_generation": expected.archive_generation,
        "raw_generation": expected.raw_generation,
        "representation_id": expected.representation_id,
    }
    ownership_state = payload.get("ownership_state") if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or ownership_state is None:
        # Explicit HAR-05 boundary: historical manifests without a governed
        # state require reconciliation/re-archive and carry no implicit read,
        # activation, or cleanup authority.
        raise RawRepresentationDeletionError(
            "cold representation manifest ownership state is unavailable"
        )
    accepted_states = {"verified", "reserved"} if allow_reserved else {"verified"}
    if (
        ownership_state not in accepted_states
        or any(payload.get(key) != value for key, value in required.items())
    ):
        raise RawRepresentationDeletionError(
            "cold representation manifest ownership generation mismatch"
        )
    if expected.record_id is not None and payload.get("record_id") != expected.record_id:
        raise RawRepresentationDeletionError("cold representation manifest record mismatch")
    if expected.content_identity is not None:
        if allow_missing_object and not object_path.is_file():
            if payload.get("content_identity") != expected.content_identity:
                raise RawRepresentationDeletionError(
                    "cold representation manifest content identity mismatch"
                )
            return
        ciphertext = object_path.read_bytes()
        if payload.get("content_identity") != expected.content_identity:
            raise RawRepresentationDeletionError(
                "cold representation manifest content identity mismatch"
            )
        if payload.get("encrypted_bytes") != len(ciphertext):
            raise RawRepresentationDeletionError(
                "cold representation manifest byte count mismatch"
            )
        if payload.get("ciphertext_sha256") != hashlib.sha256(ciphertext).hexdigest():
            raise RawRepresentationDeletionError(
                "cold representation manifest ciphertext mismatch"
            )
        if expected.nonce is None:
            raise RawRepresentationDeletionError("cold representation nonce authority unavailable")
        decrypt_and_verify_raw_bytes(
            expected.content_identity,
            ciphertext,
            expected.nonce,
            key=resolve_raw_store_key(),
        )


def _delete_bound_cold_object(
    location_ref: str,
    *,
    expected_archive_token: str,
    expected_archive_generation: str,
    expected_raw_generation: int,
    expected_representation_id: str,
    expected_record_id: str | None = None,
    expected_content_identity: str | None = None,
    expected_nonce: bytes | None = None,
) -> None:
    """Resolve and delete under one indivisible verified binding snapshot."""

    snapshot = _snapshot_cold_binding(
        location_ref,
        expected_archive_token=expected_archive_token,
        expected_archive_generation=expected_archive_generation,
        expected_raw_generation=expected_raw_generation,
        expected_representation_id=expected_representation_id,
        expected_record_id=expected_record_id,
        expected_content_identity=expected_content_identity,
        expected_nonce=expected_nonce,
    )
    if snapshot is None:
        raise RawRepresentationDeletionError(
            "cold representation archive binding is unavailable"
        )
    ownership_token = _expected_cold_delete_ownership.set(snapshot.expected)
    snapshot_token = _expected_cold_delete_snapshot.set(snapshot)
    try:
        _delete_cold_object_path(snapshot.object_path)
    finally:
        _expected_cold_delete_snapshot.reset(snapshot_token)
        _expected_cold_delete_ownership.reset(ownership_token)


def _delete_cold_objects_for_record(record_id: str) -> None:
    """Remove cold bytes and their manifest before a governed raw deletion commits."""
    for representation in all_raw_representations(record_id):
        if representation.storage_kind != _COLD_STORAGE_KIND:
            continue
        if not representation.archive_token or not representation.archive_generation:
            raise RawRepresentationDeletionError(
                "cold representation lacks exact archive ownership"
            )
        _delete_bound_cold_object(
            representation.location_ref,
            expected_archive_token=representation.archive_token,
            expected_archive_generation=representation.archive_generation,
            expected_raw_generation=representation.raw_generation,
            expected_representation_id=representation.id,
            expected_record_id=record_id,
            expected_content_identity=next(
                record.content_identity
                for record in all_raw_records()
                if record.id == record_id
            ),
            expected_nonce=representation.nonce,
        )


def _delete_cold_objects_for_pg_cursor(cur: Any, record_id: str) -> None:
    """Remove cold objects while the deletion transaction owns representation locks."""
    cur.execute(
        f"SELECT p.id, p.location_ref, p.archive_token, p.archive_generation, "
        f"p.raw_generation, p.nonce, r.content_identity "
        f"FROM {_REPRESENTATION_TABLE} AS p JOIN {_TABLE} AS r ON r.id = p.record_id "
        "WHERE p.record_id = %s AND p.storage_kind = %s FOR UPDATE",
        (record_id, _COLD_STORAGE_KIND),
    )
    for row in cur.fetchall():
        if len(row) == 5:
            # Compatibility for narrow in-memory cursor fakes; the real PG
            # query above always returns the cryptographic authority columns.
            representation_id, location_ref, archive_token, archive_generation, raw_generation = row
            nonce = None
            content_identity = None
        else:
            (
                representation_id,
                location_ref,
                archive_token,
                archive_generation,
                raw_generation,
                nonce,
                content_identity,
            ) = row
        if not archive_token or not archive_generation:
            raise RawRepresentationDeletionError(
                "cold representation lacks exact archive ownership"
            )
        _delete_bound_cold_object(
            str(location_ref),
            expected_archive_token=str(archive_token),
            expected_archive_generation=str(archive_generation),
            expected_raw_generation=int(raw_generation),
            expected_representation_id=str(representation_id),
            expected_record_id=record_id if content_identity is not None else None,
            expected_content_identity=(
                str(content_identity) if content_identity is not None else None
            ),
            expected_nonce=bytes(nonce) if nonce is not None else None,
        )


def _delete_cold_object_path(object_path: Path) -> None:
    try:
        with _cold_archive_mutation_lock(object_path.parent.parent, blocking=False):
            manifest_path = object_path.parent.parent.joinpath(
                "manifests", f"{object_path.stem}.json"
            )
            expected = _expected_cold_delete_ownership.get()
            snapshot = _expected_cold_delete_snapshot.get()
            if expected is None or snapshot is None or snapshot.object_path != object_path:
                raise RawRepresentationDeletionError(
                    "cold representation deletion lacks exact binding authority"
                )
            # Canonical order is archive mutation lock, then binding lock.
            # Revalidation plus external I/O stay inside that order so neither
            # rebind nor cache replacement can retarget this cleanup.
            with _COLD_BINDING_LOCK:
                if not _cold_binding_snapshot_is_current(snapshot):
                    raise RawRepresentationDeletionError(
                        "cold representation binding changed before deletion"
                    )
                object_exists = object_path.exists()
                manifest_exists = manifest_path.exists()
                if object_exists or manifest_exists:
                    _verify_cold_manifest_ownership(
                        object_path,
                        expected,
                        allow_reserved=True,
                        allow_missing_object=not object_exists and manifest_exists,
                    )
                if object_exists and not manifest_exists:
                    raise RawRepresentationDeletionError(
                        "cold representation manifest ownership is unavailable"
                    )

                # Receipt/queue authority may advance only after each removal
                # is independently crash durable in this exact sequence.
                _cold_delete_stage_hook("before_unlink", object_path)
                object_path.unlink(missing_ok=True)
                _cold_delete_stage_hook("after_object_unlink", object_path)
                directory_fd = os.open(object_path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
                _cold_delete_stage_hook("after_object_directory_fsync", object_path)

                manifest_path.unlink(missing_ok=True)
                _cold_delete_stage_hook("after_manifest_unlink", manifest_path)
                directory_fd = os.open(manifest_path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
                _cold_delete_stage_hook("after_manifest_directory_fsync", manifest_path)

                _cold_location_paths.pop(expected.location_ref, None)
                _cold_location_ownership.pop(expected.location_ref, None)
    except RawRepresentationDeletionError:
        raise
    except OSError as exc:
        raise RawRepresentationDeletionError(
            "cold representation deletion failed"
        ) from exc


def _representation_ciphertext(representation: "RawRepresentation") -> bytes:
    if representation.storage_kind == _COLD_STORAGE_KIND:
        if not representation.archive_token or not representation.archive_generation:
            raise RawRepresentationUnavailableError(
                "cold representation lacks durable archive binding"
            )
        return _resolve_cold_ciphertext(
            representation.location_ref,
            expected_archive_token=representation.archive_token,
            expected_archive_generation=representation.archive_generation,
            expected_raw_generation=representation.raw_generation,
            expected_representation_id=representation.id,
        )
    return representation.ciphertext


class AppendOnlyViolationError(RuntimeError):
    """Raised when a caller attempts to mutate an existing raw record row.

    Never raised by this module's own code paths (there is no update/delete
    API) -- it is raised when the Postgres backend surfaces the DB trigger's
    rejection of an UPDATE/DELETE statement issued outside this module.
    """


class RawStoreKeyMissingError(RuntimeError):
    """Raised when no encryption key is configured -- refuse, never write plaintext."""


def resolve_raw_store_key() -> bytes:
    """Resolve the AES-256-GCM key material for encryption at rest.

    Fail-loud (KERNEL-03/I-S4 precedent, mirrors
    `app.heimdal._backend.resolve_heimdal_backend`): a missing key raises
    rather than silently falling back to writing plaintext or a fixed
    all-zero key. The key is a 64-char hex string (32 bytes) in
    ``HEIMDAL_RAW_STORE_KEY`` -- generate with ``python -c "import secrets;
    print(secrets.token_hex(32))"``.
    """
    raw = os.environ.get(_KEY_ENV_VAR)
    if not raw:
        raise RawStoreKeyMissingError(
            f"{_KEY_ENV_VAR} is not set: raw evidence is encrypted at rest and this "
            "module refuses to write plaintext or use a fixed default key. Set "
            f"{_KEY_ENV_VAR} to a 64-char hex string (32 bytes)."
        )
    try:
        key = bytes.fromhex(raw.strip())
    except ValueError as exc:
        raise RawStoreKeyMissingError(f"{_KEY_ENV_VAR} is not valid hex: {exc}") from exc
    if len(key) != _AES_KEY_BYTES:
        raise RawStoreKeyMissingError(
            f"{_KEY_ENV_VAR} must decode to {_AES_KEY_BYTES} bytes (AES-256), got {len(key)}"
        )
    return key


def encrypt_raw_bytes(plaintext: bytes, *, key: bytes) -> tuple[bytes, bytes]:
    """Encrypt ``plaintext`` with AES-256-GCM. Returns ``(ciphertext, nonce)``.

    AES-GCM is authenticated encryption: any tampering with the ciphertext
    (or a wrong key) makes decryption raise rather than silently returning
    corrupted plaintext. A fresh random nonce is drawn per call -- callers
    must never reuse a nonce with the same key (AESGCM.generate_key/encrypt
    convention).
    """
    aesgcm = AESGCM(key)
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return ciphertext, nonce


def decrypt_raw_bytes(ciphertext: bytes, nonce: bytes, *, key: bytes) -> bytes:
    """Decrypt ``ciphertext``/``nonce`` with AES-256-GCM. Raises on tamper or wrong key."""
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


def compute_raw_content_identity(plaintext: bytes) -> str:
    """Return the canonical SHA-256 identity for raw evidence bytes."""
    return hashlib.sha256(plaintext).hexdigest()


def decrypt_and_verify_raw_bytes(
    content_identity: str,
    ciphertext: bytes,
    nonce: bytes,
    *,
    key: bytes,
) -> bytes:
    """Decrypt one representation and bind it to immutable content identity.

    Existing authority surfaces use both bare SHA-256 hex and the explicit
    ``sha256:<hex>`` spelling.  Those are the only accepted forms.  A wrong
    key, tampered ciphertext, or different plaintext is the same fail-closed
    outcome to callers: the representation cannot be proven to belong to the
    immutable raw identity.
    """
    try:
        plaintext = decrypt_raw_bytes(ciphertext, nonce, key=key)
    except Exception as exc:
        raise RawRepresentationIdentityMismatchError(
            "raw representation cannot be verified against immutable content identity"
        ) from exc
    digest = compute_raw_content_identity(plaintext)
    if content_identity not in {digest, f"sha256:{digest}"}:
        raise RawRepresentationIdentityMismatchError(
            "raw representation plaintext does not match immutable content identity"
        )
    return plaintext


@dataclass(frozen=True)
class RawRecord:
    """One immutable raw identity resolved with its active representation.

    Identity/provenance fields live in ``heimdal_raw_record``. The encrypted
    fields are composed from the one active, registered representation so
    existing capture/read consumers keep a stable value object while durable
    identity is no longer coupled to one physical copy.
    """

    id: str
    content_identity: str
    capture_chain: List[str]
    sensor: Dict[str, Any]
    consent: Dict[str, Any]
    ciphertext: bytes
    nonce: bytes
    key_ref: str
    source_path: str
    ingested_at: datetime
    payload: Dict[str, Any]
    sequence: int


@dataclass(frozen=True)
class RawRepresentation:
    """One registered encrypted representation of an immutable raw identity.

    ``location_ref`` is an internal opaque handle, never a caller-supplied
    filesystem path. HAR-02 supports only the existing Postgres hot storage;
    later archive slices may add a resolver for another registered kind.
    """

    id: str
    record_id: str
    storage_kind: str
    location_ref: str
    ciphertext: bytes
    nonce: bytes
    key_ref: str
    active: bool
    registered_at: datetime
    sequence: int
    raw_generation: int = 0
    archive_token: Optional[str] = None
    archive_generation: Optional[str] = None


@dataclass(frozen=True)
class _RawIdentity:
    """Durable identity/provenance fields, deliberately excluding raw bytes."""

    id: str
    content_identity: str
    capture_chain: List[str]
    sensor: Dict[str, Any]
    consent: Dict[str, Any]
    source_path: str
    ingested_at: datetime
    payload: Dict[str, Any]
    sequence: int


@dataclass(frozen=True)
class RawRecordCapacityMetadata:
    """The only raw-record fields capacity reporting may read.

    This intentionally excludes identifiers, paths, provenance, payloads, and
    ciphertext.  It keeps the HAR-01 aggregate report from materializing raw
    evidence merely to count encrypted storage bytes.
    """

    ingested_at: datetime
    encrypted_bytes: int


@dataclass(frozen=True)
class RawConsentAssociation:
    """Append-only consent coverage for one exact raw generation."""

    record_id: str
    generation: int
    grant_ref: str
    admitted_at: datetime
    sequence: int


@dataclass(frozen=True)
class RawRetentionMetadata:
    """Ciphertext-free selector row for one active raw generation."""

    record_id: str
    content_identity: str
    generation: int
    ingested_at: datetime


class _MemoryRawStore:
    """In-process append-only store. Test/dev backend; volatile by design."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: List[_RawIdentity] = []
        self._by_identity: Dict[str, _RawIdentity] = {}
        self._representations: Dict[str, RawRepresentation] = {}
        self._representation_ids_by_record: Dict[str, List[str]] = {}
        self._consent_associations: Dict[str, Dict[str, RawConsentAssociation]] = {}

    def _associate_consent_locked(
        self,
        *,
        record_id: str,
        generation: int,
        grant_ref: str,
        admitted_at: datetime,
    ) -> RawConsentAssociation:
        associations = self._consent_associations.setdefault(record_id, {})
        existing = associations.get(grant_ref)
        if existing is not None:
            if existing.generation != generation:
                raise RawRepresentationUnavailableError(
                    "consent association replay targets a different raw generation"
                )
            return existing
        association = RawConsentAssociation(
            record_id=record_id,
            generation=generation,
            grant_ref=grant_ref,
            admitted_at=admitted_at,
            sequence=sum(len(items) for items in self._consent_associations.values()),
        )
        associations[grant_ref] = association
        return association

    def _active_representation_locked(self, record_id: str) -> RawRepresentation:
        active = [
            self._representations[representation_id]
            for representation_id in self._representation_ids_by_record.get(record_id, [])
            if self._representations[representation_id].active
        ]
        if len(active) != 1 or active[0].storage_kind not in {
            _HOT_STORAGE_KIND,
            _COLD_STORAGE_KIND,
        } or active[0].raw_generation <= 0 or (
            active[0].storage_kind == _HOT_STORAGE_KIND
            and (
                active[0].archive_token is not None
                or active[0].archive_generation is not None
            )
        ) or (
            active[0].storage_kind == _COLD_STORAGE_KIND
            and (
                not active[0].archive_token
                or not active[0].archive_generation
                or not active[0].location_ref.startswith(
                    f"{_LOCATION_REF_PREFIX}cold:{active[0].archive_token}:"
                )
            )
        ):
            raise RawRepresentationUnavailableError(
                "raw identity does not have exactly one supported active registered representation"
            )
        return active[0]

    @staticmethod
    def _compose(identity: _RawIdentity, representation: RawRepresentation) -> RawRecord:
        return RawRecord(
            id=identity.id,
            content_identity=identity.content_identity,
            capture_chain=list(identity.capture_chain),
            sensor=dict(identity.sensor),
            consent=dict(identity.consent),
            ciphertext=_representation_ciphertext(representation),
            nonce=representation.nonce,
            key_ref=representation.key_ref,
            source_path=identity.source_path,
            ingested_at=identity.ingested_at,
            payload=dict(identity.payload),
            sequence=identity.sequence,
        )

    def insert(self, record: RawRecord) -> tuple[RawRecord, bool]:
        """Atomically insert identity and its initial registered hot representation."""
        from app.heimdal import raw_liveness

        with raw_liveness.memory_fence(), self._lock:
            existing = self._by_identity.get(record.content_identity)
            if existing is not None:
                generation = raw_liveness.assert_memory_generation_active(
                    record_id=existing.id,
                    content_identity=record.content_identity,
                )
                self._associate_consent_locked(
                    record_id=existing.id,
                    generation=generation.generation,
                    grant_ref=str(record.consent["grant_ref"]),
                    admitted_at=datetime.now(timezone.utc),
                )
                return (
                    self._compose(existing, self._active_representation_locked(existing.id)),
                    False,
                )
            identity = _RawIdentity(
                id=record.id,
                content_identity=record.content_identity,
                capture_chain=list(record.capture_chain),
                sensor=dict(record.sensor),
                consent=dict(record.consent),
                source_path=record.source_path,
                ingested_at=datetime.now(timezone.utc),
                payload=dict(record.payload),
                sequence=len(self._rows),
            )
            representation = RawRepresentation(
                id=record.id,
                record_id=record.id,
                storage_kind=_HOT_STORAGE_KIND,
                location_ref=f"{_LOCATION_REF_PREFIX}{record.id}",
                ciphertext=record.ciphertext,
                nonce=record.nonce,
                key_ref=record.key_ref,
                active=True,
                registered_at=identity.ingested_at,
                sequence=0,
            )
            try:
                self._rows.append(identity)
                self._by_identity[record.content_identity] = identity
                self._representations[representation.id] = representation
                self._representation_ids_by_record[record.id] = [representation.id]
                generation = raw_liveness.register_memory_generation(
                    record_id=record.id,
                    content_identity=record.content_identity,
                    activated_at=identity.ingested_at,
                )
                representation = replace(
                    representation,
                    raw_generation=generation.generation,
                )
                self._representations[representation.id] = representation
                self._associate_consent_locked(
                    record_id=record.id,
                    generation=generation.generation,
                    grant_ref=str(record.consent["grant_ref"]),
                    admitted_at=identity.ingested_at,
                )
            except Exception:
                self._rows = [row for row in self._rows if row.id != record.id]
                self._by_identity.pop(record.content_identity, None)
                self._representations.pop(representation.id, None)
                self._representation_ids_by_record.pop(record.id, None)
                self._consent_associations.pop(record.id, None)
                raise
            return self._compose(identity, representation), True

    def validate_exact_active(self, record_id: str, content_identity: str) -> bool:
        """Validate exact identity + one supported active representation."""

        with self._lock:
            identity = next((row for row in self._rows if row.id == record_id), None)
            if identity is None or identity.content_identity != content_identity:
                return False
            try:
                self._active_representation_locked(record_id)
            except RawRepresentationUnavailableError:
                return False
            return True

    def all_rows(self) -> List[RawRecord]:
        with self._lock:
            snapshots = [
                (row, self._active_representation_locked(row.id)) for row in self._rows
            ]
        return [self._compose(row, representation) for row, representation in snapshots]

    def record_ids_by_consent_grant(self, grant_ref: str) -> List[str]:
        """Select raw identities by consent metadata without reading representations."""

        with self._lock:
            return [
                row.id
                for row in self._rows
                if grant_ref in self._consent_associations.get(row.id, {})
            ]

    def consent_grant_refs(self, record_id: str) -> List[str]:
        """Resolve every consent grant associated with one raw generation."""

        with self._lock:
            return list(self._consent_associations.get(record_id, {}))

    def archive_eligible_hot_rows(
        self,
        *,
        ingested_before: datetime,
        ingested_at_or_after: datetime,
        limit: int,
    ) -> tuple[List[RawRecord], int]:
        with self._lock:
            selected: List[RawRecord] = []
            eligible_count = 0
            for row in self._rows:
                active = self._active_representation_locked(row.id)
                if (
                    active.storage_kind != _HOT_STORAGE_KIND
                    or row.ingested_at >= ingested_before
                    or row.ingested_at < ingested_at_or_after
                ):
                    continue
                eligible_count += 1
                if len(selected) < limit:
                    selected.append(self._compose(row, active))
            return selected, eligible_count

    def capacity_metadata(self) -> List[RawRecordCapacityMetadata]:
        with self._lock:
            return [
                RawRecordCapacityMetadata(
                    row.ingested_at,
                    sum(
                        len(self._representations[representation_id].ciphertext)
                        for representation_id in self._representation_ids_by_record.get(row.id, [])
                    ),
                )
                for row in self._rows
            ]

    def retention_metadata_before(
        self,
        cutoff: datetime,
        *,
        modality: str | None = None,
    ) -> List[RawRetentionMetadata]:
        """Select expired identities without resolving any representation bytes."""

        with self._lock:
            selected: List[RawRetentionMetadata] = []
            for row in self._rows:
                if row.ingested_at >= cutoff or (
                    modality is not None and row.payload.get("modality") != modality
                ):
                    continue
                generations = {
                    association.generation
                    for association in self._consent_associations.get(row.id, {}).values()
                }
                if len(generations) != 1:
                    raise RawRepresentationUnavailableError(
                        "active raw identity lacks one correlated consent generation"
                    )
                selected.append(
                    RawRetentionMetadata(
                        record_id=row.id,
                        content_identity=row.content_identity,
                        generation=next(iter(generations)),
                        ingested_at=row.ingested_at,
                    )
                )
            return selected

    def raw_modality(self, record_id: str) -> str:
        """Read only non-secret modality metadata for governed deletion."""

        with self._lock:
            row = next((item for item in self._rows if item.id == record_id), None)
            if row is None:
                raise RawRepresentationUnavailableError(
                    "raw record modality metadata is unavailable"
                )
            return canonical_raw_modality(row.payload.get("modality"))

    def get_by_content_identity(self, content_identity: str) -> Optional[RawRecord]:
        with self._lock:
            identity = self._by_identity.get(content_identity)
            if identity is None:
                return None
            representation = self._active_representation_locked(identity.id)
        return self._compose(identity, representation)

    def active_record_ids_by_content_identities(
        self, content_identities: List[str]
    ) -> Dict[str, str]:
        """Return active raw IDs only, without composing encrypted record payloads."""
        with self._lock:
            return {
                identity: record.id
                for identity in set(content_identities)
                if (record := self._by_identity.get(identity)) is not None
                and self._active_representation_locked(record.id) is not None
            }

    def resolve_active(self, record_id: str) -> Optional[RawRecord]:
        with self._lock:
            identity = next((row for row in self._rows if row.id == record_id), None)
            if identity is None:
                return None
            representation = self._active_representation_locked(record_id)
        # Compose outside the store mutex: cold reads may perform verified
        # archive I/O and must not prevent relocation from advancing the raw
        # authority while a read snapshot is being revalidated.
        return self._compose(identity, representation)

    def register_representation(
        self,
        *,
        record_id: str,
        ciphertext: bytes,
        nonce: bytes,
        key_ref: str,
        key: bytes,
        representation_id: str,
        activate: bool,
        authority: object,
    ) -> tuple[RawRepresentation, bool]:
        with self._lock:
            identity = next((row for row in self._rows if row.id == record_id), None)
            if identity is None:
                raise RawRepresentationUnavailableError("raw identity does not exist")
            from app.heimdal import raw_liveness

            mutation_authority = raw_liveness.require_raw_mutation_authority(
                authority,
                record_id=record_id,
                content_identity=identity.content_identity,
            )
            decrypt_and_verify_raw_bytes(
                identity.content_identity,
                ciphertext,
                nonce,
                key=key,
            )
            existing = self._representations.get(representation_id)
            if existing is not None:
                expected = (
                    record_id,
                    ciphertext,
                    nonce,
                    key_ref,
                    _HOT_STORAGE_KIND,
                    mutation_authority.generation,
                    None,
                    None,
                )
                actual = (
                    existing.record_id,
                    existing.ciphertext,
                    existing.nonce,
                    existing.key_ref,
                    existing.storage_kind,
                    existing.raw_generation,
                    existing.archive_token,
                    existing.archive_generation,
                )
                if actual != expected:
                    raise ValueError("representation id replay does not match registered bytes")
                if activate:
                    existing = self._activate_representation_locked(
                        record_id, representation_id, key=key
                    )
                return existing, False
            representation = RawRepresentation(
                id=representation_id,
                record_id=record_id,
                storage_kind=_HOT_STORAGE_KIND,
                location_ref=f"{_LOCATION_REF_PREFIX}{representation_id}",
                ciphertext=ciphertext,
                nonce=nonce,
                key_ref=key_ref,
                active=False,
                registered_at=datetime.now(timezone.utc),
                sequence=len(self._representation_ids_by_record.get(record_id, [])),
                raw_generation=mutation_authority.generation,
            )
            self._representations[representation.id] = representation
            self._representation_ids_by_record.setdefault(record_id, []).append(representation.id)
            if activate:
                representation = self._activate_representation_locked(
                    record_id, representation.id, key=key
                )
            return representation, True

    def register_cold_representation(
        self,
        *,
        record_id: str,
        ciphertext: bytes,
        nonce: bytes,
        key_ref: str,
        key: bytes,
        representation_id: str,
        location_ref: str,
        archive_token: str,
        archive_generation: str,
        authority: object,
    ) -> tuple[RawRepresentation, bool]:
        with self._lock:
            identity = next((row for row in self._rows if row.id == record_id), None)
            if identity is None:
                raise RawRepresentationUnavailableError("raw identity does not exist")
            from app.heimdal import raw_liveness

            mutation_authority = raw_liveness.require_raw_mutation_authority(
                authority,
                record_id=record_id,
                content_identity=identity.content_identity,
            )
            decrypt_and_verify_raw_bytes(identity.content_identity, ciphertext, nonce, key=key)
            existing = self._representations.get(representation_id)
            if existing is not None:
                expected = (
                    record_id,
                    nonce,
                    key_ref,
                    _COLD_STORAGE_KIND,
                    location_ref,
                    mutation_authority.generation,
                    archive_token,
                    archive_generation,
                )
                actual = (
                    existing.record_id,
                    existing.nonce,
                    existing.key_ref,
                    existing.storage_kind,
                    existing.location_ref,
                    existing.raw_generation,
                    existing.archive_token,
                    existing.archive_generation,
                )
                if actual != expected:
                    raise ValueError(
                        "cold representation id replay does not match registered state"
                    )
                return existing, False
            representation = RawRepresentation(
                id=representation_id,
                record_id=record_id,
                storage_kind=_COLD_STORAGE_KIND,
                location_ref=location_ref,
                ciphertext=b"",
                nonce=nonce,
                key_ref=key_ref,
                active=False,
                registered_at=datetime.now(timezone.utc),
                sequence=len(self._representation_ids_by_record.get(record_id, [])),
                raw_generation=mutation_authority.generation,
                archive_token=archive_token,
                archive_generation=archive_generation,
            )
            self._representations[representation.id] = representation
            self._representation_ids_by_record.setdefault(record_id, []).append(representation.id)
            return representation, True

    def _activate_representation_locked(
        self, record_id: str, representation_id: str, *, key: bytes
    ) -> RawRepresentation:
        target = self._representations.get(representation_id)
        if target is None or target.record_id != record_id:
            raise RawRepresentationUnavailableError(
                "cannot activate an unregistered representation for this raw identity"
            )
        identity = next((row for row in self._rows if row.id == record_id), None)
        if identity is None:
            raise RawRepresentationUnavailableError("raw identity does not exist")
        decrypt_and_verify_raw_bytes(
            identity.content_identity,
            _representation_ciphertext(target),
            target.nonce,
            key=key,
        )
        for current_id in self._representation_ids_by_record.get(record_id, []):
            current = self._representations[current_id]
            self._representations[current_id] = replace(
                current, active=current_id == representation_id
            )
        return self._representations[representation_id]

    def activate_representation(
        self,
        record_id: str,
        representation_id: str,
        *,
        key: bytes,
        authority: object,
    ) -> RawRepresentation:
        with self._lock:
            identity = next((row for row in self._rows if row.id == record_id), None)
            if identity is None:
                raise RawRepresentationUnavailableError("raw identity does not exist")
            from app.heimdal import raw_liveness

            raw_liveness.require_raw_mutation_authority(
                authority,
                record_id=record_id,
                content_identity=identity.content_identity,
            )
            return self._activate_representation_locked(record_id, representation_id, key=key)

    def all_representations(self, record_id: str) -> List[RawRepresentation]:
        with self._lock:
            return [
                self._representations[representation_id]
                for representation_id in self._representation_ids_by_record.get(record_id, [])
            ]

    def _delete_representation_locked(self, representation_id: str) -> None:
        self._representations.pop(representation_id)

    def snapshot_state(
        self,
    ) -> tuple[
        List[_RawIdentity],
        Dict[str, _RawIdentity],
        Dict[str, RawRepresentation],
        Dict[str, List[str]],
        Dict[str, Dict[str, RawConsentAssociation]],
    ]:
        """Snapshot memory raw state while the liveness fence is held.

        The governed deletion coordinator uses this to give the volatile
        backend the same all-or-nothing crash semantics as PostgreSQL.  The
        stored records are immutable values, so container copies are enough.
        """

        with self._lock:
            return (
                list(self._rows),
                dict(self._by_identity),
                dict(self._representations),
                {key: list(value) for key, value in self._representation_ids_by_record.items()},
                {key: dict(value) for key, value in self._consent_associations.items()},
            )

    def restore_state(
        self,
        snapshot: tuple[
            List[_RawIdentity],
            Dict[str, _RawIdentity],
            Dict[str, RawRepresentation],
            Dict[str, List[str]],
            Dict[str, Dict[str, RawConsentAssociation]],
        ],
    ) -> None:
        """Restore a deletion snapshot while the liveness fence is held."""

        with self._lock:
            rows, by_identity, representations, representation_ids, associations = snapshot
            self._rows = list(rows)
            self._by_identity = dict(by_identity)
            self._representations = dict(representations)
            self._representation_ids_by_record = {
                key: list(value) for key, value in representation_ids.items()
            }
            self._consent_associations = {
                key: dict(value) for key, value in associations.items()
            }

    def hard_delete(self, record_id: str) -> bool:
        """Atomically erase every representation, then its immutable identity."""
        with self._lock:
            row_index = next((i for i, row in enumerate(self._rows) if row.id == record_id), None)
            if row_index is None:
                return False
            representations_before = dict(self._representations)
            representation_ids_before = {
                key: list(value) for key, value in self._representation_ids_by_record.items()
            }
            try:
                for representation_id in list(
                    self._representation_ids_by_record.get(record_id, [])
                ):
                    self._delete_representation_locked(representation_id)
                if any(
                    representation.record_id == record_id
                    for representation in self._representations.values()
                ):
                    raise RawRepresentationDeletionError(
                        "raw representation remains after governed all-copy deletion"
                    )
            except Exception as exc:
                self._representations = representations_before
                self._representation_ids_by_record = representation_ids_before
                if isinstance(exc, RawRepresentationDeletionError):
                    raise
                raise RawRepresentationDeletionError(
                    "governed all-copy deletion failed; no identity was removed"
                ) from exc

            row = self._rows.pop(row_index)
            self._by_identity.pop(row.content_identity, None)
            self._representation_ids_by_record.pop(record_id, None)
            self._consent_associations.pop(record_id, None)
            return True

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()
            self._by_identity.clear()
            self._representations.clear()
            self._representation_ids_by_record.clear()
            self._consent_associations.clear()
            self._by_identity.clear()
            self._representations.clear()
            self._representation_ids_by_record.clear()


_MEMORY_STORE = _MemoryRawStore()


def reset_memory_raw_store() -> None:
    """Test-only reset hook, mirroring the other memory-backend reset helpers."""
    _MEMORY_STORE.clear()
    revoke_cold_archive_binding()
    from app.heimdal.raw_liveness import reset_memory_raw_liveness

    reset_memory_raw_liveness()


def _pg_connect(*, autocommit: bool = True) -> Any:
    import psycopg

    from app.db.dsn import resolve_dsn

    url = os.environ.get("DATABASE_URL") or os.environ.get("DB_DSN")
    if not url:
        raise RuntimeError("DATABASE_URL or DB_DSN not set")
    return psycopg.connect(resolve_dsn(url), autocommit=autocommit)


def _schema_autocreate_enabled() -> bool:
    """Explicit test-fixture opt-in, mirroring KERNEL-04/KERNEL-05 precedent.

    Production/runtime Postgres never auto-creates this table; only test
    environments set STORE_SCHEMA_AUTOCREATE=1 (tests/conftest.py).
    """
    return (os.environ.get("STORE_SCHEMA_AUTOCREATE") or "").strip().lower() in {"1", "true", "yes"}


def _assert_pg_schema(conn: Any, *, allow_legacy_reconciliation: bool = False) -> None:
    cur = conn.cursor()
    cur.execute(
        "SELECT to_regclass(%s), to_regclass(%s)",
        (_TABLE, _REPRESENTATION_TABLE),
    )
    row = cur.fetchone()
    if not row or not row[0] or not row[1]:
        raise RawStoreSchemaMissingError(
            "Missing raw identity or representation table. " + _MIGRATION_HINT
        )

    cur.execute(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name IN (%s, %s)
        """,
        (_TABLE, _REPRESENTATION_TABLE),
    )
    columns: Dict[str, set[str]] = {_TABLE: set(), _REPRESENTATION_TABLE: set()}
    for table_name, column_name in cur.fetchall():
        columns[str(table_name)].add(str(column_name))
    identity_required = {
        "id",
        "content_identity",
        "capture_chain",
        "sensor",
        "consent",
        "source_path",
        "ingested_at",
        "payload",
        "sequence",
    }
    representation_required = {
        "id",
        "record_id",
        "storage_kind",
        "location_ref",
        "ciphertext",
        "nonce",
        "key_ref",
        "raw_generation",
        "archive_token",
        "archive_generation",
        "active",
        "registered_at",
        "sequence",
    }
    legacy_blob_columns = {"ciphertext", "nonce", "key_ref"}
    if (
        not identity_required.issubset(columns[_TABLE])
        or not representation_required.issubset(columns[_REPRESENTATION_TABLE])
        or legacy_blob_columns.intersection(columns[_TABLE])
    ):
        raise RawStoreSchemaMissingError(
            "Raw identity/representation columns do not match the location-aware schema. "
            + _MIGRATION_HINT
        )

    cur.execute(
        """
        SELECT pg_get_constraintdef(c.oid), c.convalidated
        FROM pg_constraint AS c
        WHERE c.conrelid = %s::regclass
          AND c.conname = %s
          AND c.contype = 'c'
        """,
        (_REPRESENTATION_TABLE, _COLD_LOCATION_CONSTRAINT),
    )
    cold_location_constraints = cur.fetchall()
    if len(cold_location_constraints) != 1 or not _cold_location_constraint_is_ready(
        str(cold_location_constraints[0][0]),
        bool(cold_location_constraints[0][1]),
    ):
        raise RawStoreSchemaMissingError(
            "Cold representation archive binding constraint is not migration-ready. "
            + _MIGRATION_HINT
        )
    cur.execute(
        """
        SELECT pg_get_constraintdef(c.oid), c.convalidated
        FROM pg_constraint AS c
        WHERE c.conrelid = %s::regclass
          AND c.conname = %s
          AND c.contype = 'c'
        """,
        (_REPRESENTATION_TABLE, _ARCHIVE_GENERATION_CONSTRAINT),
    )
    archive_generation_constraints = cur.fetchall()
    if len(archive_generation_constraints) != 1 or not _archive_generation_constraint_is_ready(
        str(archive_generation_constraints[0][0]),
        bool(archive_generation_constraints[0][1]),
    ):
        raise RawStoreSchemaMissingError(
            "Cold representation archive generation constraint is not migration-ready. "
            + _MIGRATION_HINT
        )
    cur.execute(
        """
        SELECT pg_get_constraintdef(c.oid), c.convalidated
        FROM pg_constraint AS c
        WHERE c.conrelid = %s::regclass
          AND c.conname = %s
          AND c.contype = 'c'
        """,
        (_REPRESENTATION_TABLE, _COLD_OWNER_CONSTRAINT),
    )
    cold_owner_constraints = cur.fetchall()
    if len(cold_owner_constraints) != 1 or not _cold_owner_constraint_is_ready(
        str(cold_owner_constraints[0][0]),
        bool(cold_owner_constraints[0][1]),
    ):
        raise RawStoreSchemaMissingError(
            "Cold representation object ownership constraint is not migration-ready. "
            + _MIGRATION_HINT
        )
    cur.execute(
        """
        SELECT c.convalidated,
               ARRAY(
                   SELECT a.attname
                   FROM unnest(c.conkey) WITH ORDINALITY AS key(attnum, ord)
                   JOIN pg_attribute AS a
                     ON a.attrelid = c.conrelid AND a.attnum = key.attnum
                   ORDER BY key.ord
               ),
               referenced.relname,
               ARRAY(
                   SELECT a.attname
                   FROM unnest(c.confkey) WITH ORDINALITY AS key(attnum, ord)
                   JOIN pg_attribute AS a
                     ON a.attrelid = c.confrelid AND a.attnum = key.attnum
                   ORDER BY key.ord
               ),
               c.confdeltype
        FROM pg_constraint AS c
        JOIN pg_class AS referenced ON referenced.oid = c.confrelid
        JOIN pg_namespace AS referenced_namespace
          ON referenced_namespace.oid = referenced.relnamespace
        WHERE c.conrelid = %s::regclass
          AND c.conname = %s
          AND c.contype = 'f'
          AND referenced_namespace.nspname = current_schema()
        """,
        (_REPRESENTATION_TABLE, _GENERATION_FK_CONSTRAINT),
    )
    generation_fk_rows = cur.fetchall()
    generation_fk_ready = len(generation_fk_rows) == 1 and (
        bool(generation_fk_rows[0][0])
        and tuple(str(column) for column in generation_fk_rows[0][1])
        == ("record_id", "raw_generation")
        and str(generation_fk_rows[0][2]) == _GENERATION_TABLE
        and tuple(str(column) for column in generation_fk_rows[0][3])
        == ("record_id", "generation")
        and str(generation_fk_rows[0][4]) == "r"
    )
    if not generation_fk_ready:
        raise RawStoreSchemaMissingError(
            "Raw representation generation binding is not migration-ready. "
            + _MIGRATION_HINT
        )

    cur.execute(
        """
        SELECT c.relname, i.indisunique, i.indpred IS NOT NULL,
               ARRAY(
                   SELECT a.attname
                   FROM unnest(i.indkey) WITH ORDINALITY AS key(attnum, ord)
                   JOIN pg_attribute AS a
                     ON a.attrelid = i.indrelid AND a.attnum = key.attnum
                   ORDER BY key.ord
               )
        FROM pg_index AS i
        JOIN pg_class AS c ON c.oid = i.indexrelid
        WHERE i.indrelid IN (%s::regclass, %s::regclass)
          AND c.relname IN (
              'heimdal_raw_record_seq_idx',
              'heimdal_raw_record_content_identity_idx',
              'heimdal_raw_record_content_identity_uq',
              'heimdal_raw_representation_record_idx',
              'heimdal_raw_representation_one_active_uq'
          )
        """,
        (_TABLE, _REPRESENTATION_TABLE),
    )
    indexes = {
        str(name): (bool(unique), bool(partial), tuple(str(column) for column in key_columns))
        for name, unique, partial, key_columns in cur.fetchall()
    }
    expected_indexes = {
        "heimdal_raw_record_seq_idx": (False, False, ("sequence",)),
        "heimdal_raw_record_content_identity_idx": (
            False,
            False,
            ("content_identity",),
        ),
        "heimdal_raw_record_content_identity_uq": (
            True,
            False,
            ("content_identity",),
        ),
        "heimdal_raw_representation_record_idx": (
            False,
            False,
            ("record_id", "sequence"),
        ),
        "heimdal_raw_representation_one_active_uq": (
            True,
            True,
            ("record_id",),
        ),
    }
    if indexes != expected_indexes:
        raise RawStoreSchemaMissingError(
            "Raw identity/representation indexes do not match the migration-owned schema. "
            + _MIGRATION_HINT
        )

    cur.execute(
        """
        SELECT event_object_table, trigger_name, event_manipulation,
               action_timing, action_orientation, action_statement
        FROM information_schema.triggers
        WHERE trigger_schema = current_schema()
          AND event_object_table IN (%s, %s)
          AND trigger_name IN (
              'heimdal_raw_record_no_update',
              'heimdal_raw_representation_no_mutation'
          )
        """,
        (_TABLE, _REPRESENTATION_TABLE),
    )
    trigger_rows = {
        (
            str(table_name),
            str(trigger_name),
            str(event),
            str(timing),
            str(orientation),
            str(statement),
        )
        for table_name, trigger_name, event, timing, orientation, statement in cur.fetchall()
    }
    expected_trigger_rows = {
        (
            _TABLE,
            "heimdal_raw_record_no_update",
            event,
            "BEFORE",
            "ROW",
            "EXECUTE FUNCTION heimdal_raw_record_reject_mutation()",
        )
        for event in ("DELETE", "UPDATE")
    } | {
        (
            _REPRESENTATION_TABLE,
            "heimdal_raw_representation_no_mutation",
            event,
            "BEFORE",
            "ROW",
            "EXECUTE FUNCTION heimdal_raw_representation_reject_mutation()",
        )
        for event in ("DELETE", "INSERT", "UPDATE")
    }
    if trigger_rows != expected_trigger_rows:
        raise RawStoreSchemaMissingError(
            "Raw identity/representation mutation triggers do not match the "
            "migration-owned schema. " + _MIGRATION_HINT
        )
    cur.execute(
        """
        SELECT pg_get_functiondef(t.tgfoid), pg_get_triggerdef(t.oid)
        FROM pg_trigger AS t
        JOIN pg_class AS c ON c.oid = t.tgrelid
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = current_schema()
          AND c.relname = %s
          AND t.tgname = 'heimdal_raw_representation_no_mutation'
          AND NOT t.tgisinternal
        """,
        (_REPRESENTATION_TABLE,),
    )
    representation_guard_rows = cur.fetchall()
    guard_definition = (
        (str(representation_guard_rows[0][0]), str(representation_guard_rows[0][1]))
        if len(representation_guard_rows) == 1
        else ("", "")
    )
    if not _representation_guard_is_migration_ready(*guard_definition):
        raise RawStoreSchemaMissingError(
            "Raw representation pending-cleanup reuse guard is not migration-ready. "
            + _MIGRATION_HINT
        )

    # Fail loud before serving any production call when backfill or activation
    # is incomplete. The gate must never fall back to legacy inline bytes or an
    # unchecked locator.
    cold_generation_clause = (
        "TRUE" if allow_legacy_reconciliation else "p.archive_generation IS NOT NULL"
    )
    invalid_cold_generation_clause = (
        "p.archive_generation IS NULL AND p.active IS NOT TRUE"
        if allow_legacy_reconciliation
        else "p.archive_generation IS NULL"
    )
    cur.execute(
        f"""
        SELECT r.id
        FROM {_TABLE} AS r
        LEFT JOIN {_REPRESENTATION_TABLE} AS p ON p.record_id = r.id
        GROUP BY r.id
        HAVING count(*) FILTER (WHERE p.active) <> 1
            OR count(*) FILTER (
                WHERE p.storage_kind = 'encrypted_local_cold'
                  AND {invalid_cold_generation_clause}
            ) <> 0
            OR count(*) FILTER (
                WHERE p.active
                  AND (
                    NOT (
                        (
                            p.storage_kind = 'postgres_hot'
                            AND p.location_ref LIKE %s
                            AND p.ciphertext IS NOT NULL
                            AND p.nonce IS NOT NULL
                            AND p.key_ref IS NOT NULL
                            AND p.archive_token IS NULL
                            AND p.archive_generation IS NULL
                        )
                        OR (
                            p.storage_kind = 'encrypted_local_cold'
                            AND p.location_ref LIKE %s
                                AND p.nonce IS NOT NULL
                                AND p.key_ref IS NOT NULL
                            AND p.archive_token IS NOT NULL
                            AND {cold_generation_clause}
                            AND p.location_ref LIKE
                                'heimloc:cold:' || p.archive_token || %s
                            AND p.location_ref =
                                'heimloc:cold:' || p.archive_token || ':' || p.id::text
                        )
                    )
                  )
            ) <> 0
        LIMIT 1
        """,
        (f"{_LOCATION_REF_PREFIX}%", f"{_LOCATION_REF_PREFIX}cold:%", ":%"),
    )
    if cur.fetchone() is not None:
        raise RawStoreSchemaMissingError(
            "Raw representation backfill/activation is incomplete or unsupported; "
            "refusing to serve raw records. " + _MIGRATION_HINT
        )

    from app.heimdal import raw_liveness

    raw_liveness._assert_pg_schema(conn)  # noqa: SLF001


def _bootstrap_pg(conn: Any) -> None:
    if not _schema_autocreate_enabled():
        _assert_pg_schema(conn)
        return
    cur = conn.cursor()
    # Autocreate is a fresh-fixture producer, never a second migration engine.
    # Any existing/partial/legacy shape is asserted exactly and must be repaired
    # by Alembic; runtime bootstrap never backfills or reshapes durable tables.
    cur.execute(
        "SELECT to_regclass(%s), to_regclass(%s)",
        (_TABLE, _REPRESENTATION_TABLE),
    )
    existing = cur.fetchone()
    if existing and (existing[0] or existing[1]):
        _assert_pg_schema(conn)
        return

    cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    table_groups = (
        (
            _TABLE,
            (
                f"""
                CREATE TABLE {_TABLE} (
                    id uuid PRIMARY KEY,
                    content_identity text NOT NULL,
                    capture_chain jsonb NOT NULL,
                    sensor jsonb NOT NULL,
                    consent jsonb NOT NULL,
                    source_path text NOT NULL,
                    ingested_at timestamptz NOT NULL DEFAULT now(),
                    payload jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                    sequence bigserial NOT NULL
                )
                """,
                f"CREATE INDEX heimdal_raw_record_seq_idx ON {_TABLE} (sequence)",
                f"CREATE INDEX heimdal_raw_record_content_identity_idx "
                f"ON {_TABLE} (content_identity)",
                f"CREATE UNIQUE INDEX heimdal_raw_record_content_identity_uq "
                f"ON {_TABLE} (content_identity)",
                f"""
                CREATE OR REPLACE FUNCTION heimdal_raw_record_reject_mutation()
                RETURNS trigger AS $$
                BEGIN
                    IF TG_OP = 'DELETE'
                       AND current_setting('{_RETENTION_GUARD_SETTING}', true) = 'true' THEN
                        RETURN OLD;
                    END IF;
                    RAISE EXCEPTION 'heimdal_raw_record is append-only (HEIM-1): % is not permitted '
                        'outside the governed hard-retention job (D-RETENTION)', TG_OP;
                END;
                $$ LANGUAGE plpgsql
                """,
                f"""
                CREATE TRIGGER heimdal_raw_record_no_update
                BEFORE UPDATE OR DELETE ON {_TABLE}
                FOR EACH ROW EXECUTE FUNCTION heimdal_raw_record_reject_mutation()
                """,
            ),
        ),
        (
            _REPRESENTATION_TABLE,
            (
                f"""
                CREATE TABLE {_REPRESENTATION_TABLE} (
                    id uuid PRIMARY KEY,
                    record_id uuid NOT NULL REFERENCES {_TABLE}(id) ON DELETE RESTRICT,
                    storage_kind text NOT NULL CHECK (
                        storage_kind IN ('{_HOT_STORAGE_KIND}', '{_COLD_STORAGE_KIND}')
                    ),
                    location_ref text NOT NULL UNIQUE
                        CHECK (location_ref LIKE '{_LOCATION_REF_PREFIX}%'),
                    ciphertext bytea,
                    nonce bytea,
                    key_ref text,
                    active boolean NOT NULL DEFAULT false,
                    registered_at timestamptz NOT NULL DEFAULT now(),
                    sequence bigserial NOT NULL,
                    raw_generation integer NOT NULL,
                    archive_token text,
                    archive_generation text,
                    CONSTRAINT {_COLD_LOCATION_CONSTRAINT} CHECK (
                        storage_kind <> '{_COLD_STORAGE_KIND}'
                        OR location_ref ~ '{_COLD_LOCATION_REF_PATTERN}'
                    ),
                    CONSTRAINT {_COLD_OWNER_CONSTRAINT} CHECK (
                        storage_kind <> '{_COLD_STORAGE_KIND}'
                        OR location_ref = '{_LOCATION_REF_PREFIX}cold:'
                            || archive_token || ':' || id::text
                    ),
                    CONSTRAINT heimdal_raw_representation_archive_generation_check CHECK (
                        (
                            storage_kind = '{_HOT_STORAGE_KIND}'
                            AND archive_token IS NULL
                            AND archive_generation IS NULL
                        )
                        OR (
                            storage_kind = '{_COLD_STORAGE_KIND}'
                            AND archive_token ~ '^[0-9a-f]{{64}}$'
                            AND (
                                archive_generation ~ '^[0-9a-f]{{64}}$'
                                OR archive_generation IS NULL
                            )
                            AND location_ref LIKE
                                '{_LOCATION_REF_PREFIX}cold:' || archive_token || ':%'
                        )
                    )
                )
                """,
                f"CREATE INDEX heimdal_raw_representation_record_idx "
                f"ON {_REPRESENTATION_TABLE} (record_id, sequence)",
                f"CREATE UNIQUE INDEX heimdal_raw_representation_one_active_uq "
                f"ON {_REPRESENTATION_TABLE} (record_id) WHERE active",
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
                        IF NEW.storage_kind = '{_COLD_STORAGE_KIND}'
                           AND EXISTS (
                               SELECT 1 FROM {_DELETION_RECEIPT_TABLE}
                               WHERE COALESCE(
                                   payload->'cold_cleanup_location_refs', '[]'::jsonb
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
                       AND current_setting('app.heimdal_legacy_archive_reconcile', true) = 'true'
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
                       AND current_setting('{_REPRESENTATION_ACTIVATION_GUARD_SETTING}', true) = 'true'
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
                       AND current_setting('{_RETENTION_GUARD_SETTING}', true) = 'true' THEN
                        RETURN OLD;
                    END IF;
                    RAISE EXCEPTION
                        'heimdal_raw_representation mutation is governed: % is not permitted',
                        TG_OP;
                END;
                $$ LANGUAGE plpgsql
                """,
                f"""
                CREATE TRIGGER heimdal_raw_representation_no_mutation
                BEFORE INSERT OR UPDATE OR DELETE ON {_REPRESENTATION_TABLE}
                FOR EACH ROW EXECUTE FUNCTION heimdal_raw_representation_reject_mutation()
                """,
            ),
        ),
    )
    for table_name, statements in table_groups:
        cur.execute("SELECT to_regclass(%s)", (table_name,))
        table_present_row = cur.fetchone()
        table_present = bool(table_present_row and table_present_row[0])
        if table_present:
            continue
        for statement in statements:
            cur.execute(statement)
    from app.heimdal import raw_liveness

    raw_liveness._bootstrap_pg(conn)  # noqa: SLF001
    _assert_pg_schema(conn)


def _row_from_db(row: tuple) -> RawRecord:
    (
        row_id,
        content_identity,
        capture_chain,
        sensor,
        consent,
        representation_id,
        storage_kind,
        location_ref,
        ciphertext,
        nonce,
        key_ref,
        raw_generation,
        archive_token,
        archive_generation,
        source_path,
        ingested_at,
        payload,
        sequence,
    ) = row

    def _as_dict(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if value is None:
            return {}
        return json.loads(value)

    def _as_list(value: Any) -> List[Any]:
        if isinstance(value, list):
            return value
        if value is None:
            return []
        return json.loads(value)

    resolved_representation_id = str(representation_id)
    if str(storage_kind) == _COLD_STORAGE_KIND:
        parsed_location = _parse_cold_location_ref(str(location_ref))
        if (
            parsed_location is None
            or parsed_location[1] != resolved_representation_id
            or int(raw_generation) <= 0
        ):
            raise RawRepresentationUnavailableError(
                "active cold representation lacks exact durable ownership identity"
            )
    representation = RawRepresentation(
        id=resolved_representation_id,
        record_id=str(row_id),
        storage_kind=str(storage_kind),
        location_ref=str(location_ref),
        ciphertext=bytes(ciphertext or b""),
        nonce=bytes(nonce),
        key_ref=str(key_ref),
        active=True,
        registered_at=ingested_at,
        sequence=int(sequence),
        raw_generation=int(raw_generation),
        archive_token=str(archive_token) if archive_token is not None else None,
        archive_generation=(
            str(archive_generation) if archive_generation is not None else None
        ),
    )
    return RawRecord(
        id=str(row_id),
        content_identity=str(content_identity),
        capture_chain=_as_list(capture_chain),
        sensor=_as_dict(sensor),
        consent=_as_dict(consent),
        ciphertext=_representation_ciphertext(representation),
        nonce=bytes(nonce),
        key_ref=str(key_ref),
        source_path=str(source_path),
        ingested_at=ingested_at,
        payload=_as_dict(payload),
        sequence=int(sequence),
    )


_SELECT_COLUMNS = (
    "r.id, r.content_identity, r.capture_chain, r.sensor, r.consent, "
    "p.id, p.storage_kind, p.location_ref, p.ciphertext, p.nonce, p.key_ref, "
    "p.raw_generation, p.archive_token, p.archive_generation, "
    "r.source_path, r.ingested_at, r.payload, r.sequence"
)

_REPRESENTATION_SELECT_COLUMNS = (
    "id, record_id, storage_kind, location_ref, ciphertext, nonce, key_ref, "
    "raw_generation, archive_token, archive_generation, active, registered_at, sequence"
)


def _representation_from_db(row: tuple) -> RawRepresentation:
    return RawRepresentation(
        id=str(row[0]),
        record_id=str(row[1]),
        storage_kind=str(row[2]),
        location_ref=str(row[3]),
        ciphertext=bytes(row[4] or b""),
        nonce=bytes(row[5]),
        key_ref=str(row[6]),
        raw_generation=int(row[7]),
        archive_token=str(row[8]) if row[8] is not None else None,
        archive_generation=str(row[9]) if row[9] is not None else None,
        active=bool(row[10]),
        registered_at=row[11],
        sequence=int(row[12]),
    )


class _PgRawStore:
    """Postgres-backed append-only raw store; append-only enforced by DB trigger."""

    def __init__(self) -> None:
        conn = _pg_connect(autocommit=False)
        try:
            _bootstrap_pg(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def insert(self, record: RawRecord) -> tuple[RawRecord, bool]:
        from app.heimdal import raw_liveness

        conn = _pg_connect(autocommit=False)
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            raw_liveness.acquire_pg_fence(cur, record.content_identity)
            cur.execute(
                f"""
                INSERT INTO {_TABLE} (
                    id, content_identity, capture_chain, sensor, consent, source_path, payload
                ) VALUES (%s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s::jsonb)
                ON CONFLICT (content_identity) DO NOTHING
                RETURNING id
                """,
                (
                    record.id,
                    record.content_identity,
                    json.dumps(record.capture_chain),
                    json.dumps(record.sensor),
                    json.dumps(record.consent),
                    record.source_path,
                    json.dumps(record.payload),
                ),
            )
            row = cur.fetchone()
            if row is not None:
                cur.execute(
                    f"SELECT id, content_identity, ingested_at FROM {_TABLE} WHERE id = %s",
                    (record.id,),
                )
                identity_row = cur.fetchone()
                assert identity_row is not None
                generation = raw_liveness.register_pg_generation(
                    cur,
                    record_id=str(identity_row[0]),
                    content_identity=str(identity_row[1]),
                    activated_at=identity_row[2],
                )
                cur.execute(
                    f"""
                    INSERT INTO {_REPRESENTATION_TABLE} (
                        id, record_id, storage_kind, location_ref,
                        ciphertext, nonce, key_ref, raw_generation,
                        archive_token, archive_generation, active
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL, true)
                    """,
                    (
                        record.id,
                        record.id,
                        _HOT_STORAGE_KIND,
                        f"{_LOCATION_REF_PREFIX}{record.id}",
                        record.ciphertext,
                        record.nonce,
                        record.key_ref,
                        generation.generation,
                    ),
                )
                created = True
            else:
                created = False
                cur.execute(
                    f"SELECT id, content_identity, ingested_at FROM {_TABLE} "
                    "WHERE content_identity = %s",
                    (record.content_identity,),
                )
                identity_row = cur.fetchone()
                if identity_row is None:
                    raise RawRepresentationUnavailableError(
                        "raw identity replay could not resolve durable identity"
                    )
                generation = raw_liveness.assert_pg_generation_active(
                    cur,
                    record_id=str(identity_row[0]),
                    content_identity=str(identity_row[1]),
                )
            cur.execute(
                f"""
                INSERT INTO {_CONSENT_ASSOCIATION_TABLE} (
                    record_id, generation, grant_ref, admitted_at
                ) VALUES (%s, %s, %s, %s)
                ON CONFLICT (record_id, generation, grant_ref) DO NOTHING
                """,
                (
                    str(identity_row[0]),
                    generation.generation,
                    str(record.consent["grant_ref"]),
                    datetime.now(timezone.utc),
                ),
            )
            cur.execute(
                f"""
                SELECT {_SELECT_COLUMNS}
                FROM {_TABLE} AS r
                JOIN {_REPRESENTATION_TABLE} AS p ON p.record_id = r.id AND p.active
                WHERE r.content_identity = %s
                """,
                (record.content_identity,),
            )
            persisted = cur.fetchone()
            if persisted is None:
                raise RawRepresentationUnavailableError(
                    "raw identity insert/replay has no active registered representation"
                )
            persisted_record = _row_from_db(persisted)
            conn.commit()
            return persisted_record, created
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def all_rows(self) -> List[RawRecord]:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT {_SELECT_COLUMNS}
                FROM {_TABLE} AS r
                JOIN {_REPRESENTATION_TABLE} AS p ON p.record_id = r.id AND p.active
                ORDER BY r.sequence ASC
                """
            )
            return [_row_from_db(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def record_ids_by_consent_grant(self, grant_ref: str) -> List[str]:
        """Select raw identities by consent metadata without materializing ciphertext."""

        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT r.id
                FROM {_CONSENT_ASSOCIATION_TABLE} AS a
                JOIN {_TABLE} AS r ON r.id = a.record_id
                WHERE a.grant_ref = %s OR a.legacy_lineage_ambiguous
                ORDER BY r.sequence ASC
                """,
                (grant_ref,),
            )
            return [str(row[0]) for row in cur.fetchall()]
        finally:
            conn.close()

    def consent_grant_refs(self, record_id: str) -> List[str]:
        """Resolve every consent grant associated with one raw generation."""

        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"SELECT grant_ref FROM {_CONSENT_ASSOCIATION_TABLE} "
                "WHERE record_id = %s ORDER BY sequence",
                (record_id,),
            )
            return [str(row[0]) for row in cur.fetchall()]
        finally:
            conn.close()

    def archive_eligible_hot_rows(
        self,
        *,
        ingested_before: datetime,
        ingested_at_or_after: datetime,
        limit: int,
    ) -> tuple[List[RawRecord], int]:
        """Select a bounded hot batch while counting the full eligible window."""
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT {_SELECT_COLUMNS}, count(*) OVER ()
                FROM {_TABLE} AS r
                JOIN {_REPRESENTATION_TABLE} AS p
                  ON p.record_id = r.id
                 AND p.active
                 AND p.storage_kind = %s
                WHERE r.ingested_at < %s
                  AND r.ingested_at >= %s
                ORDER BY r.sequence ASC
                LIMIT %s
                """,
                (
                    _HOT_STORAGE_KIND,
                    ingested_before,
                    ingested_at_or_after,
                    limit,
                ),
            )
            rows = cur.fetchall()
            if not rows:
                return [], 0
            return (
                [_row_from_db(tuple(row[:-1])) for row in rows],
                int(rows[0][-1]),
            )
        finally:
            conn.close()

    def capacity_metadata(self) -> List[RawRecordCapacityMetadata]:
        """Query aggregate-report metadata without selecting sensitive row fields."""
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT r.ingested_at, sum(octet_length(p.ciphertext))
                FROM {_TABLE} AS r
                JOIN {_REPRESENTATION_TABLE} AS p ON p.record_id = r.id
                GROUP BY r.id, r.ingested_at, r.sequence
                ORDER BY r.sequence ASC
                """
            )
            return [
                RawRecordCapacityMetadata(ingested_at=row[0], encrypted_bytes=int(row[1]))
                for row in cur.fetchall()
            ]
        finally:
            conn.close()

    def retention_metadata_before(
        self,
        cutoff: datetime,
        *,
        modality: str | None = None,
    ) -> List[RawRetentionMetadata]:
        """Select expired identities without selecting a representation or locator."""

        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT r.id, r.content_identity, g.generation, r.ingested_at
                FROM heimdal_raw_record AS r
                JOIN heimdal_raw_liveness_generation AS g ON g.record_id = r.id
                LEFT JOIN heimdal_raw_deletion_tombstone AS t ON t.record_id = r.id
                WHERE r.ingested_at < %s
                  AND (%s::text IS NULL OR r.payload->>'modality' = %s)
                  AND t.record_id IS NULL
                ORDER BY r.sequence
                """,
                (cutoff, modality, modality),
            )
            return [
                RawRetentionMetadata(
                    record_id=str(row[0]),
                    content_identity=str(row[1]),
                    generation=int(row[2]),
                    ingested_at=row[3],
                )
                for row in cur.fetchall()
            ]
        finally:
            conn.close()

    def raw_modality(self, record_id: str) -> str:
        """Read only non-secret modality metadata for governed deletion."""

        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"SELECT payload->>'modality' FROM {_TABLE} WHERE id = %s",
                (record_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise RawRepresentationUnavailableError(
                    "raw record modality metadata is unavailable"
                )
            return canonical_raw_modality(row[0])
        finally:
            conn.close()

    def get_by_content_identity(self, content_identity: str) -> Optional[RawRecord]:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT {_SELECT_COLUMNS}
                FROM {_TABLE} AS r
                JOIN {_REPRESENTATION_TABLE} AS p ON p.record_id = r.id AND p.active
                WHERE r.content_identity = %s
                """,
                (content_identity,),
            )
            row = cur.fetchone()
            return _row_from_db(row) if row is not None else None
        finally:
            conn.close()

    def active_record_ids_by_content_identities(
        self, content_identities: List[str]
    ) -> Dict[str, str]:
        """Resolve active raw IDs in one metadata-only query.

        Receipt recovery needs only identity existence and the opaque raw-record
        ID; selecting ciphertext, nonces, or JSON payloads here would materialize
        media bytes on a read-only recovery path.
        """
        identities = sorted(set(content_identities))
        if not identities:
            return {}
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT r.content_identity, r.id
                FROM {_TABLE} AS r
                JOIN {_REPRESENTATION_TABLE} AS p ON p.record_id = r.id AND p.active
                WHERE r.content_identity = ANY(%s)
                """,
                (identities,),
            )
            return {
                str(content_identity): str(record_id)
                for content_identity, record_id in cur.fetchall()
            }
        finally:
            conn.close()

    def resolve_active(self, record_id: str) -> Optional[RawRecord]:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT {_SELECT_COLUMNS}
                FROM {_TABLE} AS r
                JOIN {_REPRESENTATION_TABLE} AS p ON p.record_id = r.id AND p.active
                WHERE r.id = %s
                """,
                (record_id,),
            )
            row = cur.fetchone()
            return _row_from_db(row) if row is not None else None
        finally:
            conn.close()

    def register_representation(
        self,
        *,
        record_id: str,
        ciphertext: bytes,
        nonce: bytes,
        key_ref: str,
        key: bytes,
        representation_id: str,
        activate: bool,
        authority: object,
    ) -> tuple[RawRepresentation, bool]:
        from app.heimdal import raw_liveness

        cur = raw_liveness.pg_cursor_for_raw_mutation(authority, record_id=record_id)
        cur.execute(
            f"SELECT content_identity FROM {_TABLE} WHERE id = %s FOR UPDATE",
            (record_id,),
        )
        identity_row = cur.fetchone()
        if identity_row is None:
            raise RawRepresentationUnavailableError("raw identity does not exist")
        mutation_authority = raw_liveness.require_raw_mutation_authority(
            authority,
            record_id=record_id,
            content_identity=str(identity_row[0]),
        )
        decrypt_and_verify_raw_bytes(
            str(identity_row[0]),
            ciphertext,
            nonce,
            key=key,
        )
        cur.execute(
            f"""
            INSERT INTO {_REPRESENTATION_TABLE} (
                id, record_id, storage_kind, location_ref,
                ciphertext, nonce, key_ref, raw_generation,
                archive_token, archive_generation, active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL, false)
            ON CONFLICT (id) DO NOTHING
            RETURNING {_REPRESENTATION_SELECT_COLUMNS}
            """,
            (
                representation_id,
                record_id,
                _HOT_STORAGE_KIND,
                f"{_LOCATION_REF_PREFIX}{representation_id}",
                ciphertext,
                nonce,
                key_ref,
                mutation_authority.generation,
            ),
        )
        inserted = cur.fetchone()
        created = inserted is not None
        if inserted is None:
            cur.execute(
                f"SELECT {_REPRESENTATION_SELECT_COLUMNS} "
                f"FROM {_REPRESENTATION_TABLE} WHERE id = %s",
                (representation_id,),
            )
            inserted = cur.fetchone()
            if inserted is None:
                raise RawRepresentationUnavailableError(
                    "representation replay could not resolve registered state"
                )
            existing = _representation_from_db(inserted)
            if (
                existing.record_id != record_id
                or existing.storage_kind != _HOT_STORAGE_KIND
                or existing.ciphertext != ciphertext
                or existing.nonce != nonce
                or existing.key_ref != key_ref
                or existing.raw_generation != mutation_authority.generation
                or existing.archive_token is not None
                or existing.archive_generation is not None
            ):
                raise ValueError("representation id replay does not match registered bytes")
        if activate:
            self._activate_with_cursor(cur, record_id, representation_id, key=key)
            cur.execute(
                f"SELECT {_REPRESENTATION_SELECT_COLUMNS} "
                f"FROM {_REPRESENTATION_TABLE} WHERE id = %s",
                (representation_id,),
            )
            inserted = cur.fetchone()
        assert inserted is not None
        return _representation_from_db(inserted), created

    def register_cold_representation(
        self,
        *,
        record_id: str,
        ciphertext: bytes,
        nonce: bytes,
        key_ref: str,
        key: bytes,
        representation_id: str,
        location_ref: str,
        archive_token: str,
        archive_generation: str,
        authority: object,
    ) -> tuple[RawRepresentation, bool]:
        from app.heimdal import raw_liveness

        cur = raw_liveness.pg_cursor_for_raw_mutation(authority, record_id=record_id)
        cur.execute(
            f"SELECT content_identity FROM {_TABLE} WHERE id = %s FOR UPDATE", (record_id,)
        )
        identity_row = cur.fetchone()
        if identity_row is None:
            raise RawRepresentationUnavailableError("raw identity does not exist")
        mutation_authority = raw_liveness.require_raw_mutation_authority(
            authority,
            record_id=record_id,
            content_identity=str(identity_row[0]),
        )
        decrypt_and_verify_raw_bytes(str(identity_row[0]), ciphertext, nonce, key=key)
        cur.execute(
            f"""
            INSERT INTO {_REPRESENTATION_TABLE} (
                id, record_id, storage_kind, location_ref,
                ciphertext, nonce, key_ref, raw_generation,
                archive_token, archive_generation, active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, false)
            ON CONFLICT (id) DO NOTHING
            RETURNING {_REPRESENTATION_SELECT_COLUMNS}
            """,
            (
                representation_id,
                record_id,
                _COLD_STORAGE_KIND,
                location_ref,
                None,
                nonce,
                key_ref,
                mutation_authority.generation,
                archive_token,
                archive_generation,
            ),
        )
        inserted = cur.fetchone()
        created = inserted is not None
        if inserted is None:
            cur.execute(
                f"SELECT {_REPRESENTATION_SELECT_COLUMNS} FROM {_REPRESENTATION_TABLE} WHERE id = %s",
                (representation_id,),
            )
            inserted = cur.fetchone()
            if inserted is None:
                raise RawRepresentationUnavailableError(
                    "cold representation replay could not resolve"
                )
            existing = _representation_from_db(inserted)
            if (
                existing.record_id != record_id
                or existing.storage_kind != _COLD_STORAGE_KIND
                or existing.location_ref != location_ref
                or existing.nonce != nonce
                or existing.key_ref != key_ref
                or existing.raw_generation != mutation_authority.generation
                or existing.archive_token != archive_token
                or existing.archive_generation != archive_generation
            ):
                raise ValueError(
                    "cold representation id replay does not match registered state"
                )
        assert inserted is not None
        return _representation_from_db(inserted), created

    @staticmethod
    def _activate_with_cursor(
        cur: Any,
        record_id: str,
        representation_id: str,
        *,
        key: bytes,
    ) -> None:
        cur.execute(
            f"SELECT content_identity FROM {_TABLE} WHERE id = %s FOR UPDATE",
            (record_id,),
        )
        identity_row = cur.fetchone()
        if identity_row is None:
            raise RawRepresentationUnavailableError("raw identity does not exist")
        cur.execute(
            f"SELECT storage_kind, location_ref, ciphertext, nonce, raw_generation, "
            f"archive_token, archive_generation FROM {_REPRESENTATION_TABLE} "
            "WHERE id = %s AND record_id = %s FOR UPDATE",
            (representation_id, record_id),
        )
        target_row = cur.fetchone()
        if target_row is None:
            raise RawRepresentationUnavailableError(
                "cannot activate an unregistered representation for this raw identity"
            )
        decrypt_and_verify_raw_bytes(
            str(identity_row[0]),
            _representation_ciphertext(
                RawRepresentation(
                    id=representation_id,
                    record_id=record_id,
                    storage_kind=str(target_row[0]),
                    location_ref=str(target_row[1]),
                    ciphertext=bytes(target_row[2] or b""),
                    nonce=bytes(target_row[3]),
                    key_ref="activation",
                    active=False,
                    registered_at=datetime.now(timezone.utc),
                    sequence=0,
                    raw_generation=int(target_row[4]),
                    archive_token=(str(target_row[5]) if target_row[5] is not None else None),
                    archive_generation=(
                        str(target_row[6]) if target_row[6] is not None else None
                    ),
                )
            ),
            bytes(target_row[3]),
            key=key,
        )
        cur.execute(
            "SELECT set_config(%s, 'true', true)",
            (_REPRESENTATION_ACTIVATION_GUARD_SETTING,),
        )
        cur.execute(
            f"UPDATE {_REPRESENTATION_TABLE} SET active = false " "WHERE record_id = %s AND active",
            (record_id,),
        )
        cur.execute(
            f"UPDATE {_REPRESENTATION_TABLE} SET active = true WHERE id = %s",
            (representation_id,),
        )

    def activate_representation(
        self,
        record_id: str,
        representation_id: str,
        *,
        key: bytes,
        authority: object,
    ) -> RawRepresentation:
        from app.heimdal import raw_liveness

        cur = raw_liveness.pg_cursor_for_raw_mutation(authority, record_id=record_id)
        self._activate_with_cursor(cur, record_id, representation_id, key=key)
        cur.execute(
            f"SELECT {_REPRESENTATION_SELECT_COLUMNS} "
            f"FROM {_REPRESENTATION_TABLE} WHERE id = %s",
            (representation_id,),
        )
        row = cur.fetchone()
        assert row is not None
        return _representation_from_db(row)

    def all_representations(self, record_id: str) -> List[RawRepresentation]:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"SELECT {_REPRESENTATION_SELECT_COLUMNS} "
                f"FROM {_REPRESENTATION_TABLE} WHERE record_id = %s ORDER BY sequence",
                (record_id,),
            )
            return [_representation_from_db(row) for row in cur.fetchall()]
        finally:
            conn.close()

    def hard_delete(self, record_id: str) -> bool:
        """Atomically erase every registered copy before deleting identity."""
        conn = _pg_connect(autocommit=False)
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(f"SELECT 1 FROM {_TABLE} WHERE id = %s FOR UPDATE", (record_id,))
            if cur.fetchone() is None:
                conn.rollback()
                return False
            cur.execute("SELECT set_config(%s, 'true', true)", (_RETENTION_GUARD_SETTING,))
            cur.execute(f"DELETE FROM {_REPRESENTATION_TABLE} WHERE record_id = %s", (record_id,))
            cur.execute(
                f"SELECT 1 FROM {_REPRESENTATION_TABLE} WHERE record_id = %s LIMIT 1",
                (record_id,),
            )
            if cur.fetchone() is not None:
                raise RawRepresentationDeletionError(
                    "raw representation remains after governed all-copy deletion"
                )
            cur.execute(f"DELETE FROM {_TABLE} WHERE id = %s", (record_id,))
            deleted = cur.rowcount > 0
            conn.commit()
            return deleted
        except Exception as exc:
            conn.rollback()
            if isinstance(exc, RawRepresentationDeletionError):
                raise
            raise RawRepresentationDeletionError(
                "governed all-copy deletion failed; no identity was removed"
            ) from exc
        finally:
            conn.close()


def _backend() -> "_MemoryRawStore | _PgRawStore":
    if resolve_heimdal_backend() == "pg":
        return _PgRawStore()
    return _MEMORY_STORE


# ---------------------------------------------------------------------------
# Public store API
# ---------------------------------------------------------------------------


def insert_raw_record(
    *,
    content_identity: str,
    capture_chain: List[str],
    sensor: Dict[str, Any],
    consent: Dict[str, Any],
    ciphertext: bytes,
    nonce: bytes,
    key_ref: str,
    key: bytes,
    source_path: str,
    payload: Optional[Dict[str, Any]] = None,
) -> tuple[RawRecord, bool]:
    """Durably insert one encrypted raw record. Returns ``(row, created)``.

    ``created=False`` means ``content_identity`` already existed and the
    pre-existing row was returned unchanged (idempotent insert -- a
    crash-retry of the same admitted evidence, e.g. before
    delete-after-confirmed-ingest fired, does not double-write).

    Provenance (``content_identity``, ``capture_chain``, ``sensor``,
    ``consent``) is stamped in this SAME call/statement as the ciphertext
    (KERNEL-06) -- there is no separate "stamp provenance" step.
    """
    if not isinstance(content_identity, str) or not content_identity.strip():
        raise ValueError(f"content_identity must be a non-empty string, got {content_identity!r}")
    if not capture_chain:
        raise ValueError("capture_chain must be a non-empty list (FABLE_COMPANION §1.1)")
    if not sensor:
        raise ValueError(
            "sensor identity must be provided (T5 mitigation: no unregistered-source ingestion)"
        )
    if not consent or not consent.get("grant_ref"):
        raise ValueError("consent block with a resolvable grant_ref must be provided (HEIM-3)")
    decrypt_and_verify_raw_bytes(
        content_identity,
        ciphertext,
        nonce,
        key=key,
    )

    record = RawRecord(
        id=str(uuid4()),
        content_identity=content_identity,
        capture_chain=list(capture_chain),
        sensor=dict(sensor),
        consent=dict(consent),
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref=key_ref,
        source_path=source_path,
        ingested_at=datetime.now(timezone.utc),
        payload=dict(payload or {}),
        sequence=-1,
    )
    return _backend().insert(record)


def get_raw_record_by_content_identity(content_identity: str) -> Optional[RawRecord]:
    """Look up a previously-admitted raw record by its content_identity (idempotency check)."""
    return _backend().get_by_content_identity(content_identity)


def find_active_raw_record_ids_by_content_identities(
    content_identities: List[str],
) -> Dict[str, str]:
    """Resolve bounded active raw identities without materializing encrypted media.

    The return mapping is ``content_identity -> record_id`` for identities with
    one active representation. It is the receipt-state recovery seam; absence
    is distinct from a backend failure, which callers must surface rather than
    treating as an erased or unknown receipt.
    """
    return _backend().active_record_ids_by_content_identities(content_identities)


def resolve_active_raw_record(record_id: str) -> Optional[RawRecord]:
    """Resolve identity through its one active registered representation.

    This is the only storage-resolution seam used by the production raw-read
    gate. Callers cannot supply a location or path.
    """
    return _backend().resolve_active(record_id)


def raw_record_ids_by_consent_grant(grant_ref: str) -> List[str]:
    """Return matching raw ids from metadata only, never cold bytes or paths."""

    if not isinstance(grant_ref, str) or not grant_ref.strip():
        raise ValueError("grant_ref must be a non-empty string")
    return _backend().record_ids_by_consent_grant(grant_ref)


def raw_record_consent_grant_refs(record_id: str) -> List[str]:
    """Return all grants for one raw generation without reading representations."""

    if not isinstance(record_id, str) or not record_id.strip():
        raise ValueError("record_id must be a non-empty string")
    return _backend().consent_grant_refs(record_id)


def raw_record_consent_grant_ref(record_id: str) -> Optional[str]:
    """Compatibility projection for callers that can handle only one grant."""

    refs = raw_record_consent_grant_refs(record_id)
    return refs[0] if refs else None


def register_raw_representation(
    *,
    record_id: str,
    ciphertext: bytes,
    nonce: bytes,
    key_ref: str,
    key: Optional[bytes] = None,
    representation_id: Optional[str] = None,
    activate: bool = False,
    _authority: object | None = None,
) -> tuple[RawRepresentation, bool]:
    """Register an encrypted Postgres-hot copy, idempotently by representation id.

    HAR-02 deliberately accepts no storage path and no caller-selected storage
    kind. Cold-volume resolution and live relocation remain later slices.
    """
    if not record_id:
        raise ValueError("record_id must be non-empty")
    if not ciphertext or not nonce or not key_ref:
        raise ValueError("ciphertext, nonce, and key_ref are required")
    verification_key = key if key is not None else resolve_raw_store_key()
    resolved_id = representation_id or str(uuid4())
    from app.heimdal import raw_liveness

    backend = _backend()

    def register(authority: object) -> tuple[RawRepresentation, bool]:
        return backend.register_representation(
            record_id=record_id,
            ciphertext=ciphertext,
            nonce=nonce,
            key_ref=key_ref,
            key=verification_key,
            representation_id=resolved_id,
            activate=activate,
            authority=authority,
        )

    if _authority is not None:
        return register(_authority)
    content_identity = raw_liveness.content_identity_for_raw_record(record_id)
    with raw_liveness.raw_relocation_fence(
        record_id=record_id,
        content_identity=content_identity,
    ) as authority:
        return register(authority)


def register_cold_raw_representation(
    *,
    record_id: str,
    ciphertext: bytes,
    nonce: bytes,
    key_ref: str,
    location_ref: str,
    key: Optional[bytes] = None,
    representation_id: Optional[str] = None,
    verified_volume: object,
    _authority: object | None = None,
) -> tuple[RawRepresentation, bool]:
    """Register one verified encrypted local-cold representation, inactive."""
    if not record_id or not ciphertext or not nonce or not key_ref:
        raise ValueError("record_id, ciphertext, nonce, and key_ref are required")
    resolved_id = representation_id or str(uuid4())
    parsed = _parse_cold_location_ref(location_ref)
    if parsed is None or parsed[1] != resolved_id:
        raise ValueError("cold location_ref must be an opaque heimloc:cold: handle")
    object_path = _cold_object_path(location_ref)
    if object_path is None:
        raise RawRepresentationDeletionError("cold location is not bound to a verified volume")
    archive_ref = str(getattr(verified_volume, "archive_ref", ""))
    if parsed[0] != _archive_binding_token(archive_ref):
        raise RawRepresentationDeletionError(
            "cold location is bound to a different archive identity"
        )
    _require_verified_cold_volume(
        object_path.parent.parent,
        verified_volume,
        expected_archive_ref=archive_ref,
    )
    verification_key = key if key is not None else resolve_raw_store_key()
    from app.heimdal import raw_liveness

    backend = _backend()
    if raw_liveness.cold_cleanup_location_is_pending(location_ref):
        raise RawRepresentationDeletionError(
            "cold location remains owned by pending governed cleanup"
        )

    def register(authority: object) -> tuple[RawRepresentation, bool]:
        return backend.register_cold_representation(
            record_id=record_id,
            ciphertext=ciphertext,
            nonce=nonce,
            key_ref=key_ref,
            key=verification_key,
            representation_id=resolved_id,
            location_ref=location_ref,
            archive_token=parsed[0],
            archive_generation=str(getattr(verified_volume, "archive_generation", "")),
            authority=authority,
        )

    if _authority is not None:
        return register(_authority)
    content_identity = raw_liveness.content_identity_for_raw_record(record_id)
    with raw_liveness.raw_relocation_fence(
        record_id=record_id,
        content_identity=content_identity,
    ) as authority:
        return register(authority)


def activate_raw_representation(
    record_id: str,
    representation_id: str,
    *,
    key: Optional[bytes] = None,
    _authority: object | None = None,
) -> RawRepresentation:
    """Atomically select one already-registered representation for gated reads."""
    verification_key = key if key is not None else resolve_raw_store_key()
    from app.heimdal import raw_liveness

    backend = _backend()

    def activate(authority: object) -> RawRepresentation:
        return backend.activate_representation(
            record_id,
            representation_id,
            key=verification_key,
            authority=authority,
        )

    if _authority is not None:
        return activate(_authority)
    content_identity = raw_liveness.content_identity_for_raw_record(record_id)
    with raw_liveness.raw_relocation_fence(
        record_id=record_id,
        content_identity=content_identity,
    ) as authority:
        return activate(authority)


def all_raw_representations(record_id: str) -> List[RawRepresentation]:
    """Enumerate every registered copy for retention/revocation traversal."""
    return _backend().all_representations(record_id)


def all_raw_records() -> List[RawRecord]:
    """Return every raw record in insertion order (diagnostic/test helper)."""
    return _backend().all_rows()


def raw_record_modality(record_id: str) -> str:
    """Return canonical non-secret modality without materializing raw bytes."""

    if not isinstance(record_id, str) or not record_id.strip():
        raise ValueError("record_id must be a non-empty string")
    return _backend().raw_modality(record_id)


def expired_raw_record_metadata(
    *,
    ingested_before: datetime,
    modality: str | None = None,
) -> List[RawRetentionMetadata]:
    """Return ciphertext-free expiry candidates for the retention state machine."""

    if ingested_before.tzinfo is None:
        raise ValueError("ingested_before must be timezone-aware")
    return _backend().retention_metadata_before(
        ingested_before.astimezone(timezone.utc),
        modality=modality,
    )


def archive_eligible_hot_raw_records(
    *,
    ingested_before: datetime,
    ingested_at_or_after: datetime,
    limit: int,
) -> tuple[List[RawRecord], int]:
    """Return a bounded active-hot batch and the exact eligible count.

    HAR-04's production producer uses this metadata-bounded query instead of
    materializing every raw row and issuing one representation query per item.
    """
    if (
        type(limit) is not int
        or limit <= 0
        or ingested_before.tzinfo is None
        or ingested_at_or_after.tzinfo is None
        or ingested_at_or_after >= ingested_before
    ):
        raise ValueError("archive eligibility bounds and limit are invalid")
    return _backend().archive_eligible_hot_rows(
        ingested_before=ingested_before.astimezone(timezone.utc),
        ingested_at_or_after=ingested_at_or_after.astimezone(timezone.utc),
        limit=limit,
    )


def all_raw_record_capacity_metadata() -> List[RawRecordCapacityMetadata]:
    """Return only ingest time and encrypted byte count for HAR-01 reporting."""
    return _backend().capacity_metadata()


__all__ = [
    "AppendOnlyViolationError",
    "RawRecord",
    "RawRecordCapacityMetadata",
    "RawRetentionMetadata",
    "RawRepresentation",
    "RawArchiveRelocationLeaseUnavailableError",
    "RawRepresentationDeletionError",
    "RawRepresentationIdentityMismatchError",
    "RawRepresentationUnavailableError",
    "RAW_MODALITY_UNSPECIFIED",
    "RawStoreKeyMissingError",
    "RawStoreSchemaMissingError",
    "activate_raw_representation",
    "archive_eligible_hot_raw_records",
    "archive_relocation_lease",
    "all_raw_records",
    "all_raw_record_capacity_metadata",
    "all_raw_representations",
    "compute_raw_content_identity",
    "canonical_raw_modality",
    "cold_archive_mutation_lock",
    "decrypt_and_verify_raw_bytes",
    "decrypt_raw_bytes",
    "encrypt_raw_bytes",
    "get_raw_record_by_content_identity",
    "find_active_raw_record_ids_by_content_identities",
    "expired_raw_record_metadata",
    "insert_raw_record",
    "register_raw_representation",
    "register_cold_raw_representation",
    "reconcile_legacy_cold_representation",
    "reset_memory_raw_store",
    "resolve_active_raw_record",
    "raw_record_ids_by_consent_grant",
    "raw_record_modality",
    "raw_record_consent_grant_ref",
    "raw_record_consent_grant_refs",
    "resolve_raw_store_key",
]
