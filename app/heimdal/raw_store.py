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
  exception is `hard_delete_raw_record` below -- the *only* function in this
  module that can remove a row, and the *only* call the trigger admits (it
  checks a session-local guard this function sets immediately before the
  DELETEs, in the same transaction, so no other code path -- not even a
  hand-written SQL client -- can hard-delete without going through this
  function). The real caller is `app.heimdal.retention.enforce_hard_retention_bound`
  (Epic #3019 slice A12, #3032), which pairs every deletion with a durable
  deletion receipt in the same call.
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

Out of scope for HAR-02: cold-volume provisioning, a file resolver, and live
relocation. Key management/rotation also remains out of scope. The gated read
path (allowlist + receipt evaluation over the active registry entry) is
`app/heimdal/raw_read_gate.py` (A7, #3027, evolved by #3848).
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.heimdal._backend import resolve_heimdal_backend

_TABLE = "heimdal_raw_record"
_REPRESENTATION_TABLE = "heimdal_raw_representation"

_MIGRATION_HINT = (
    "the location-aware Heimdal raw schema is migration-owned: run "
    "'alembic upgrade head' against this database. See revision e7b4c9d2a6f1."
)

_KEY_ENV_VAR = "HEIMDAL_RAW_STORE_KEY"
_AES_KEY_BYTES = 32  # AES-256
_NONCE_BYTES = 12  # standard AES-GCM nonce size

# Session-local Postgres setting the append-only trigger admits a DELETE
# under (D-RETENTION governed exception). Never set by any code path other
# than `hard_delete_raw_record`, and only for the duration of that one
# statement's transaction -- see the trigger body in `_bootstrap_pg`.
_RETENTION_GUARD_SETTING = "app.heimdal_retention_bypass"
_REPRESENTATION_ACTIVATION_GUARD_SETTING = "app.heimdal_representation_activation"
_HOT_STORAGE_KIND = "postgres_hot"
_LOCATION_REF_PREFIX = "heimloc:"


class RawStoreSchemaMissingError(RuntimeError):
    """Raised when the Postgres backend is selected but the raw table/columns are absent."""


class RawRepresentationUnavailableError(RuntimeError):
    """Raised when an identity has no single readable active representation."""


class RawRepresentationDeletionError(RuntimeError):
    """Raised when governed all-representation erasure cannot complete atomically."""


class RawRepresentationIdentityMismatchError(RuntimeError):
    """Raised when encrypted representation bytes do not match immutable identity."""


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
        raise RawStoreKeyMissingError(
            f"{_KEY_ENV_VAR} is not valid hex: {exc}"
        ) from exc
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


class _MemoryRawStore:
    """In-process append-only store. Test/dev backend; volatile by design."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: List[_RawIdentity] = []
        self._by_identity: Dict[str, _RawIdentity] = {}
        self._representations: Dict[str, RawRepresentation] = {}
        self._representation_ids_by_record: Dict[str, List[str]] = {}

    def _active_representation_locked(self, record_id: str) -> RawRepresentation:
        active = [
            self._representations[representation_id]
            for representation_id in self._representation_ids_by_record.get(record_id, [])
            if self._representations[representation_id].active
        ]
        if len(active) != 1 or active[0].storage_kind != _HOT_STORAGE_KIND:
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
            ciphertext=representation.ciphertext,
            nonce=representation.nonce,
            key_ref=representation.key_ref,
            source_path=identity.source_path,
            ingested_at=identity.ingested_at,
            payload=dict(identity.payload),
            sequence=identity.sequence,
        )

    def insert(self, record: RawRecord) -> tuple[RawRecord, bool]:
        """Atomically insert identity and its initial registered hot representation."""
        with self._lock:
            existing = self._by_identity.get(record.content_identity)
            if existing is not None:
                return self._compose(existing, self._active_representation_locked(existing.id)), False
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
            self._rows.append(identity)
            self._by_identity[record.content_identity] = identity
            self._representations[representation.id] = representation
            self._representation_ids_by_record[record.id] = [representation.id]
            return self._compose(identity, representation), True

    def all_rows(self) -> List[RawRecord]:
        with self._lock:
            return [
                self._compose(row, self._active_representation_locked(row.id))
                for row in self._rows
            ]

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

    def get_by_content_identity(self, content_identity: str) -> Optional[RawRecord]:
        with self._lock:
            identity = self._by_identity.get(content_identity)
            if identity is None:
                return None
            return self._compose(identity, self._active_representation_locked(identity.id))

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
            return self._compose(identity, self._active_representation_locked(record_id))

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
    ) -> tuple[RawRepresentation, bool]:
        with self._lock:
            identity = next((row for row in self._rows if row.id == record_id), None)
            if identity is None:
                raise RawRepresentationUnavailableError("raw identity does not exist")
            decrypt_and_verify_raw_bytes(
                identity.content_identity,
                ciphertext,
                nonce,
                key=key,
            )
            existing = self._representations.get(representation_id)
            if existing is not None:
                expected = (record_id, ciphertext, nonce, key_ref, _HOT_STORAGE_KIND)
                actual = (
                    existing.record_id,
                    existing.ciphertext,
                    existing.nonce,
                    existing.key_ref,
                    existing.storage_kind,
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
            )
            self._representations[representation.id] = representation
            self._representation_ids_by_record.setdefault(record_id, []).append(representation.id)
            if activate:
                representation = self._activate_representation_locked(
                    record_id, representation.id, key=key
                )
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
            target.ciphertext,
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
        self, record_id: str, representation_id: str, *, key: bytes
    ) -> RawRepresentation:
        with self._lock:
            return self._activate_representation_locked(
                record_id, representation_id, key=key
            )

    def all_representations(self, record_id: str) -> List[RawRepresentation]:
        with self._lock:
            return [
                self._representations[representation_id]
                for representation_id in self._representation_ids_by_record.get(record_id, [])
            ]

    def _delete_representation_locked(self, representation_id: str) -> None:
        self._representations.pop(representation_id)

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
            return True

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()
            self._by_identity.clear()
            self._representations.clear()
            self._representation_ids_by_record.clear()


_MEMORY_STORE = _MemoryRawStore()


def reset_memory_raw_store() -> None:
    """Test-only reset hook, mirroring the other memory-backend reset helpers."""
    _MEMORY_STORE.clear()


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


def _assert_pg_schema(conn: Any) -> None:
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
        "id", "content_identity", "capture_chain", "sensor", "consent",
        "source_path", "ingested_at", "payload", "sequence",
    }
    representation_required = {
        "id", "record_id", "storage_kind", "location_ref", "ciphertext",
        "nonce", "key_ref", "active", "registered_at", "sequence",
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
        for event in ("DELETE", "UPDATE")
    }
    if trigger_rows != expected_trigger_rows:
        raise RawStoreSchemaMissingError(
            "Raw identity/representation mutation triggers do not match the "
            "migration-owned schema. "
            + _MIGRATION_HINT
        )

    # Fail loud before serving any production call when backfill or activation
    # is incomplete. The gate must never fall back to legacy inline bytes or an
    # unchecked locator.
    cur.execute(
        f"""
        SELECT r.id
        FROM {_TABLE} AS r
        LEFT JOIN {_REPRESENTATION_TABLE} AS p ON p.record_id = r.id
        GROUP BY r.id
        HAVING count(*) FILTER (WHERE p.active) <> 1
            OR count(*) FILTER (
                WHERE p.active
                  AND (
                    p.storage_kind <> %s
                    OR p.location_ref NOT LIKE %s
                    OR p.ciphertext IS NULL
                    OR p.nonce IS NULL
                    OR p.key_ref IS NULL
                  )
            ) <> 0
        LIMIT 1
        """,
        (_HOT_STORAGE_KIND, f"{_LOCATION_REF_PREFIX}%"),
    )
    if cur.fetchone() is not None:
        raise RawStoreSchemaMissingError(
            "Raw representation backfill/activation is incomplete or unsupported; "
            "refusing to serve raw records. " + _MIGRATION_HINT
        )


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
                    storage_kind text NOT NULL CHECK (storage_kind IN ('{_HOT_STORAGE_KIND}')),
                    location_ref text NOT NULL UNIQUE
                        CHECK (location_ref LIKE '{_LOCATION_REF_PREFIX}%'),
                    ciphertext bytea,
                    nonce bytea,
                    key_ref text,
                    active boolean NOT NULL DEFAULT false,
                    registered_at timestamptz NOT NULL DEFAULT now(),
                    sequence bigserial NOT NULL
                )
                """,
                f"CREATE INDEX heimdal_raw_representation_record_idx "
                f"ON {_REPRESENTATION_TABLE} (record_id, sequence)",
                f"CREATE UNIQUE INDEX heimdal_raw_representation_one_active_uq "
                f"ON {_REPRESENTATION_TABLE} (record_id) WHERE active",
                f"""
                CREATE OR REPLACE FUNCTION heimdal_raw_representation_reject_mutation()
                RETURNS trigger AS $$
                BEGIN
                    IF TG_OP = 'UPDATE'
                       AND current_setting(
                           '{_REPRESENTATION_ACTIVATION_GUARD_SETTING}', true
                       ) = 'true'
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
                BEFORE UPDATE OR DELETE ON {_REPRESENTATION_TABLE}
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
    _assert_pg_schema(conn)


def _row_from_db(row: tuple) -> RawRecord:
    (
        row_id, content_identity, capture_chain, sensor, consent,
        ciphertext, nonce, key_ref, source_path, ingested_at, payload, sequence,
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

    return RawRecord(
        id=str(row_id),
        content_identity=str(content_identity),
        capture_chain=_as_list(capture_chain),
        sensor=_as_dict(sensor),
        consent=_as_dict(consent),
        ciphertext=bytes(ciphertext),
        nonce=bytes(nonce),
        key_ref=str(key_ref),
        source_path=str(source_path),
        ingested_at=ingested_at,
        payload=_as_dict(payload),
        sequence=int(sequence),
    )


_SELECT_COLUMNS = (
    "r.id, r.content_identity, r.capture_chain, r.sensor, r.consent, "
    "p.ciphertext, p.nonce, p.key_ref, r.source_path, r.ingested_at, r.payload, r.sequence"
)

_REPRESENTATION_SELECT_COLUMNS = (
    "id, record_id, storage_kind, location_ref, ciphertext, nonce, key_ref, "
    "active, registered_at, sequence"
)


def _representation_from_db(row: tuple) -> RawRepresentation:
    return RawRepresentation(
        id=str(row[0]),
        record_id=str(row[1]),
        storage_kind=str(row[2]),
        location_ref=str(row[3]),
        ciphertext=bytes(row[4]),
        nonce=bytes(row[5]),
        key_ref=str(row[6]),
        active=bool(row[7]),
        registered_at=row[8],
        sequence=int(row[9]),
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
        conn = _pg_connect(autocommit=False)
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
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
                    f"""
                    INSERT INTO {_REPRESENTATION_TABLE} (
                        id, record_id, storage_kind, location_ref,
                        ciphertext, nonce, key_ref, active
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, true)
                    """,
                    (
                        record.id,
                        record.id,
                        _HOT_STORAGE_KIND,
                        f"{_LOCATION_REF_PREFIX}{record.id}",
                        record.ciphertext,
                        record.nonce,
                        record.key_ref,
                    ),
                )
                created = True
            else:
                created = False
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
            conn.commit()
            return _row_from_db(persisted), created
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
            return {str(content_identity): str(record_id) for content_identity, record_id in cur.fetchall()}
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
    ) -> tuple[RawRepresentation, bool]:
        conn = _pg_connect(autocommit=False)
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"SELECT content_identity FROM {_TABLE} WHERE id = %s FOR UPDATE",
                (record_id,),
            )
            identity_row = cur.fetchone()
            if identity_row is None:
                raise RawRepresentationUnavailableError("raw identity does not exist")
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
                    ciphertext, nonce, key_ref, active
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, false)
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
            result = _representation_from_db(inserted)
            conn.commit()
            return result, created
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

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
            f"SELECT ciphertext, nonce FROM {_REPRESENTATION_TABLE} "
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
            bytes(target_row[0]),
            bytes(target_row[1]),
            key=key,
        )
        cur.execute(
            "SELECT set_config(%s, 'true', true)",
            (_REPRESENTATION_ACTIVATION_GUARD_SETTING,),
        )
        cur.execute(
            f"UPDATE {_REPRESENTATION_TABLE} SET active = false "
            "WHERE record_id = %s AND active",
            (record_id,),
        )
        cur.execute(
            f"UPDATE {_REPRESENTATION_TABLE} SET active = true WHERE id = %s",
            (representation_id,),
        )

    def activate_representation(
        self, record_id: str, representation_id: str, *, key: bytes
    ) -> RawRepresentation:
        conn = _pg_connect(autocommit=False)
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            self._activate_with_cursor(cur, record_id, representation_id, key=key)
            cur.execute(
                f"SELECT {_REPRESENTATION_SELECT_COLUMNS} "
                f"FROM {_REPRESENTATION_TABLE} WHERE id = %s",
                (representation_id,),
            )
            row = cur.fetchone()
            assert row is not None
            result = _representation_from_db(row)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

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
        raise ValueError("sensor identity must be provided (T5 mitigation: no unregistered-source ingestion)")
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


def register_raw_representation(
    *,
    record_id: str,
    ciphertext: bytes,
    nonce: bytes,
    key_ref: str,
    key: Optional[bytes] = None,
    representation_id: Optional[str] = None,
    activate: bool = False,
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
    return _backend().register_representation(
        record_id=record_id,
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref=key_ref,
        key=verification_key,
        representation_id=resolved_id,
        activate=activate,
    )


def activate_raw_representation(
    record_id: str,
    representation_id: str,
    *,
    key: Optional[bytes] = None,
) -> RawRepresentation:
    """Atomically select one already-registered representation for gated reads."""
    verification_key = key if key is not None else resolve_raw_store_key()
    return _backend().activate_representation(
        record_id, representation_id, key=verification_key
    )


def all_raw_representations(record_id: str) -> List[RawRepresentation]:
    """Enumerate every registered copy for retention/revocation traversal."""
    return _backend().all_representations(record_id)


def all_raw_records() -> List[RawRecord]:
    """Return every raw record in insertion order (diagnostic/test helper)."""
    return _backend().all_rows()


def all_raw_record_capacity_metadata() -> List[RawRecordCapacityMetadata]:
    """Return only ingest time and encrypted byte count for HAR-01 reporting."""
    return _backend().capacity_metadata()


def hard_delete_raw_record(record_id: str) -> bool:
    """Governed exception to append-only (D-RETENTION, Charter FIXED #7).

    Atomically enumerates and removes every registered representation before
    removing the durable identity. The identity is never removed while any
    copy remains, and a representation failure rolls the whole attempt back.
    Returns ``True`` if an identity existed and all copies plus identity were
    removed, ``False`` if the identity was already absent.

    This function performs the deletion ONLY -- it does not decide *whether*
    a record is past its retention window, and it does not write a deletion
    receipt or rewrite an admission receipt. The sanctioned caller is
    `app.heimdal.retention.enforce_hard_retention_bound`, which resolves the
    retention window (from `_heimdal/**` settings notes, A14), calls this
    function for each record past the bound, and pairs every call with a
    durable deletion receipt in the same operation -- deletion is never
    silent (Constraints: "no silent hard delete"). Media receipt consumers
    derive post-erasure state from the removed raw identity; they must not
    treat this primitive as permission to mutate append-only receipt history.
    """
    return _backend().hard_delete(record_id)


__all__ = [
    "AppendOnlyViolationError",
    "RawRecord",
    "RawRecordCapacityMetadata",
    "RawRepresentation",
    "RawRepresentationDeletionError",
    "RawRepresentationIdentityMismatchError",
    "RawRepresentationUnavailableError",
    "RawStoreKeyMissingError",
    "RawStoreSchemaMissingError",
    "activate_raw_representation",
    "all_raw_records",
    "all_raw_record_capacity_metadata",
    "all_raw_representations",
    "compute_raw_content_identity",
    "decrypt_and_verify_raw_bytes",
    "decrypt_raw_bytes",
    "encrypt_raw_bytes",
    "get_raw_record_by_content_identity",
    "find_active_raw_record_ids_by_content_identities",
    "hard_delete_raw_record",
    "insert_raw_record",
    "register_raw_representation",
    "reset_memory_raw_store",
    "resolve_active_raw_record",
    "resolve_raw_store_key",
]
