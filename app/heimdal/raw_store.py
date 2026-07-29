"""Heimdal raw-evidence store v0: encrypted-at-rest capture landing table (#3025).

Slice A6 of Epic #3019 (Heimdal v1). Ratified by
`docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md` §1 and
specified by `docs/HEIMDAL/FABLE_COMPANION.md` §11#5/§11#6 (voice-memo
capture adapter writes the raw record; the gated *read* path over this
store is `app/heimdal/raw_read_gate.py`, slice A7, #3027).

Contract:

- **Append-only for every ordinary caller (HEIM-1).** Rows are inserted,
  never updated -- this module exposes no update function, and the Postgres
  backend installs a trigger rejecting UPDATE/DELETE at the database level
  (migration `d5a8e2f1b6c3`), independent of which code path issues the
  statement. **One governed exception exists by design (D-RETENTION,
  Charter FIXED #7):** the raw layer is the one place true erasure exists,
  and its execution must be receipted, never silent or unbounded. That
  exception is `hard_delete_raw_record` below -- the *only* function in this
  module that can remove a row, and the *only* call the trigger admits (it
  checks a session-local guard this function sets immediately before the
  DELETE, in the same transaction, so no other code path -- not even a
  hand-written SQL client -- can hard-delete without going through this
  function). The real caller is `app.heimdal.retention.enforce_hard_retention_bound`
  (Epic #3019 slice A12, #3032), which pairs every deletion with a durable
  deletion receipt in the same call.
- **Encrypted at rest.** Every record is encrypted with AES-256-GCM
  (authenticated encryption) before it is written; the plaintext raw bytes
  never touch the store or its backing table. The store never generates or
  manages key material -- the caller (the capture adapter) supplies the key
  once per process from `HEIMDAL_RAW_STORE_KEY` (see
  :func:`resolve_raw_store_key`), so the store itself has no ambient
  decrypt capability beyond what its caller already holds.
- **Provenance stamped in the SAME durable write (KERNEL-06).** `insert_raw_record`
  writes `content_identity`, `capture_chain`, `sensor`, and `consent` in the
  single INSERT that lands the ciphertext -- there is no "stamp provenance
  later" call. FABLE_COMPANION §1.1 provenance field table:
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
resolvable Postgres DSN uses the real ``heimdal_raw_record`` table.

Out of scope for this slice: key management/rotation (v1 uses one
process-lifetime key from an env var); ASR / transcription. The gated read
path (allowlist + receipt evaluation over this table) is
`app/heimdal/raw_read_gate.py` (A7, #3027).
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.heimdal._backend import resolve_heimdal_backend

_TABLE = "heimdal_raw_record"

_MIGRATION_HINT = (
    "heimdal_raw_record schema is migration-owned: run 'alembic upgrade head' "
    "against this database. See app/alembic/versions/d5a8e2f1b6c3_heim_raw_record_v0.py."
)

_KEY_ENV_VAR = "HEIMDAL_RAW_STORE_KEY"
_AES_KEY_BYTES = 32  # AES-256
_NONCE_BYTES = 12  # standard AES-GCM nonce size

# Session-local Postgres setting the append-only trigger admits a DELETE
# under (D-RETENTION governed exception). Never set by any code path other
# than `hard_delete_raw_record`, and only for the duration of that one
# statement's transaction -- see the trigger body in `_bootstrap_pg`.
_RETENTION_GUARD_SETTING = "app.heimdal_retention_bypass"


class RawStoreSchemaMissingError(RuntimeError):
    """Raised when the Postgres backend is selected but the raw table/columns are absent."""


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


@dataclass(frozen=True)
class RawRecord:
    """One durable, immutable row in the Heimdal raw-evidence store.

    ``ciphertext``/``nonce`` are the AES-256-GCM output of
    :func:`encrypt_raw_bytes`; the plaintext raw bytes are never persisted.
    ``key_ref`` is a caller-supplied opaque label for which key encrypted
    this row (v1: a fixed process-lifetime label -- key rotation/versioning
    is a later concern), not the key material itself.
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
        self._rows: List[RawRecord] = []
        self._by_identity: Dict[str, RawRecord] = {}

    def insert(self, record: RawRecord) -> tuple[RawRecord, bool]:
        """Insert; returns ``(row, created)``. ``created=False`` on a duplicate content_identity."""
        with self._lock:
            existing = self._by_identity.get(record.content_identity)
            if existing is not None:
                return existing, False
            row = RawRecord(
                id=record.id,
                content_identity=record.content_identity,
                capture_chain=list(record.capture_chain),
                sensor=dict(record.sensor),
                consent=dict(record.consent),
                ciphertext=record.ciphertext,
                nonce=record.nonce,
                key_ref=record.key_ref,
                source_path=record.source_path,
                ingested_at=datetime.now(timezone.utc),
                payload=dict(record.payload),
                sequence=len(self._rows),
            )
            self._rows.append(row)
            self._by_identity[record.content_identity] = row
            return row, True

    def all_rows(self) -> List[RawRecord]:
        with self._lock:
            return list(self._rows)

    def capacity_metadata(self) -> List[RawRecordCapacityMetadata]:
        with self._lock:
            return [
                RawRecordCapacityMetadata(
                    ingested_at=row.ingested_at,
                    encrypted_bytes=len(row.ciphertext),
                )
                for row in self._rows
            ]

    def get_by_content_identity(self, content_identity: str) -> Optional[RawRecord]:
        with self._lock:
            return self._by_identity.get(content_identity)

    def hard_delete(self, record_id: str) -> bool:
        """Governed exception to append-only (D-RETENTION): remove one row by id.

        Only `hard_delete_raw_record` calls this. Returns ``True`` if a row
        was actually removed, ``False`` if `record_id` did not resolve to
        any known row (the caller decides whether that is an error).
        """
        with self._lock:
            for idx, row in enumerate(self._rows):
                if row.id == record_id:
                    del self._rows[idx]
                    self._by_identity.pop(row.content_identity, None)
                    return True
            return False

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()
            self._by_identity.clear()


_MEMORY_STORE = _MemoryRawStore()


def reset_memory_raw_store() -> None:
    """Test-only reset hook, mirroring the other memory-backend reset helpers."""
    _MEMORY_STORE.clear()


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
    cur = conn.cursor()
    cur.execute("SELECT to_regclass(%s)", (_TABLE,))
    row = cur.fetchone()
    oid = row[0] if row else None
    if not oid:
        raise RawStoreSchemaMissingError(f"Missing table '{_TABLE}'. {_MIGRATION_HINT}")


def _bootstrap_pg(conn: Any) -> None:
    if not _schema_autocreate_enabled():
        _assert_pg_schema(conn)
        return
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            id uuid PRIMARY KEY,
            content_identity text NOT NULL,
            capture_chain jsonb NOT NULL,
            sensor jsonb NOT NULL,
            consent jsonb NOT NULL,
            ciphertext bytea NOT NULL,
            nonce bytea NOT NULL,
            key_ref text NOT NULL,
            source_path text NOT NULL,
            ingested_at timestamptz NOT NULL DEFAULT now(),
            payload jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            sequence bigserial NOT NULL
        )
        """
    )
    cur.execute(f"CREATE INDEX IF NOT EXISTS heimdal_raw_record_seq_idx ON {_TABLE} (sequence)")
    cur.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS heimdal_raw_record_content_identity_uq "
        f"ON {_TABLE} (content_identity)"
    )
    cur.execute(
        f"""
        CREATE OR REPLACE FUNCTION heimdal_raw_record_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            -- D-RETENTION (Charter FIXED #7): the raw layer is the one place
            -- true erasure exists, by design. The ONLY admitted exception is
            -- a governed hard-delete that sets this session-local guard in
            -- the same transaction immediately before issuing the DELETE
            -- (see hard_delete_raw_record below) -- UPDATE is never admitted
            -- under any guard, so no code path can rewrite a raw record,
            -- only remove it wholesale under the governed job.
            IF TG_OP = 'DELETE' AND current_setting('{_RETENTION_GUARD_SETTING}', true) = 'true' THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'heimdal_raw_record is append-only (HEIM-1): % is not permitted '
                'outside the governed hard-retention job (D-RETENTION)', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    cur.execute(f"DROP TRIGGER IF EXISTS heimdal_raw_record_no_update ON {_TABLE}")
    cur.execute(
        f"""
        CREATE TRIGGER heimdal_raw_record_no_update
        BEFORE UPDATE OR DELETE ON {_TABLE}
        FOR EACH ROW EXECUTE FUNCTION heimdal_raw_record_reject_mutation()
        """
    )


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
    "id, content_identity, capture_chain, sensor, consent, "
    "ciphertext, nonce, key_ref, source_path, ingested_at, payload, sequence"
)


class _PgRawStore:
    """Postgres-backed append-only raw store; append-only enforced by DB trigger."""

    def __init__(self) -> None:
        conn = _pg_connect()
        try:
            _bootstrap_pg(conn)
        finally:
            conn.close()

    def insert(self, record: RawRecord) -> tuple[RawRecord, bool]:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"""
                INSERT INTO {_TABLE} (
                    id, content_identity, capture_chain, sensor, consent,
                    ciphertext, nonce, key_ref, source_path, payload
                ) VALUES (%s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (content_identity) DO NOTHING
                RETURNING {_SELECT_COLUMNS}
                """,
                (
                    record.id,
                    record.content_identity,
                    json.dumps(record.capture_chain),
                    json.dumps(record.sensor),
                    json.dumps(record.consent),
                    record.ciphertext,
                    record.nonce,
                    record.key_ref,
                    record.source_path,
                    json.dumps(record.payload),
                ),
            )
            row = cur.fetchone()
            if row is not None:
                return _row_from_db(row), True
            # Duplicate content_identity: return the existing row (idempotent insert).
            cur.execute(
                f"SELECT {_SELECT_COLUMNS} FROM {_TABLE} WHERE content_identity = %s",
                (record.content_identity,),
            )
            existing = cur.fetchone()
            assert existing is not None, "ON CONFLICT DO NOTHING but no existing row found"
            return _row_from_db(existing), False
        finally:
            conn.close()

    def all_rows(self) -> List[RawRecord]:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(f"SELECT {_SELECT_COLUMNS} FROM {_TABLE} ORDER BY sequence ASC")
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
                f"SELECT ingested_at, octet_length(ciphertext) FROM {_TABLE} ORDER BY sequence ASC"
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
                f"SELECT {_SELECT_COLUMNS} FROM {_TABLE} WHERE content_identity = %s",
                (content_identity,),
            )
            row = cur.fetchone()
            return _row_from_db(row) if row is not None else None
        finally:
            conn.close()

    def hard_delete(self, record_id: str) -> bool:
        """Governed exception to append-only (D-RETENTION): see module docstring.

        Sets the guard the trigger admits a DELETE under, then issues the
        DELETE, on the same connection -- the guard uses ``is_local=false``
        (session-scoped, not transaction-scoped) because this module's
        connections run with ``autocommit=True`` (mirroring every other
        Heimdal store), where each statement is its own implicit
        transaction and a transaction-local `set_config` would not survive
        to the next statement. The guard is never visible to any OTHER
        connection (a fresh `_pg_connect()` per call), and this connection
        is closed immediately after, so the exception window is exactly one
        DELETE.
        """
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute("SELECT set_config(%s, 'true', false)", (_RETENTION_GUARD_SETTING,))
            cur.execute(f"DELETE FROM {_TABLE} WHERE id = %s", (record_id,))
            return cur.rowcount > 0
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


def all_raw_records() -> List[RawRecord]:
    """Return every raw record in insertion order (diagnostic/test helper)."""
    return _backend().all_rows()


def all_raw_record_capacity_metadata() -> List[RawRecordCapacityMetadata]:
    """Return only ingest time and encrypted byte count for HAR-01 reporting."""
    return _backend().capacity_metadata()


def hard_delete_raw_record(record_id: str) -> bool:
    """Governed exception to append-only (D-RETENTION, Charter FIXED #7).

    Removes exactly one raw record by its durable `id`. This is the ONLY
    function in this module (or anywhere) that can remove a row from
    `heimdal_raw_record` -- the Postgres trigger rejects every DELETE that
    does not come through this call (see the trigger body in
    `_bootstrap_pg`). Returns ``True`` if a row existed and was removed,
    ``False`` if `record_id` did not resolve to any known row.

    This function performs the deletion ONLY -- it does not decide *whether*
    a record is past its retention window, and it does not write a deletion
    receipt. The sanctioned caller is
    `app.heimdal.retention.enforce_hard_retention_bound`, which resolves the
    retention window (from `_heimdal/**` settings notes, A14), calls this
    function for each record past the bound, and pairs every call with a
    durable deletion receipt in the same operation -- deletion is never
    silent (Constraints: "no silent hard delete").
    """
    return _backend().hard_delete(record_id)


__all__ = [
    "AppendOnlyViolationError",
    "RawRecord",
    "RawRecordCapacityMetadata",
    "RawStoreKeyMissingError",
    "RawStoreSchemaMissingError",
    "all_raw_records",
    "all_raw_record_capacity_metadata",
    "decrypt_raw_bytes",
    "encrypt_raw_bytes",
    "get_raw_record_by_content_identity",
    "hard_delete_raw_record",
    "insert_raw_record",
    "reset_memory_raw_store",
    "resolve_raw_store_key",
]
