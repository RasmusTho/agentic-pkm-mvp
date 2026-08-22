"""Heimdal gated raw-read path: opaque `raw_ref` + allowlist + receipt (#3027).

Slice A7 of Epic #3019 (Heimdal v1). Sits over the raw-evidence store built
by A6 (`app/heimdal/raw_store.py`, migration `d5a8e2f1b6c3`) and enacts
`docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md` §11 /
`docs/HEIMDAL/FABLE_COMPANION.md` §11#6, satisfying HEIM-5
(`heim_policy_gated_raw_access`):

  "Raw-layer reads require a CrossScopeFlow grant and emit a receipt; no
  ungoverned raw read path exists in any surface (API, CLI, worker, agent)."

This module is deliberately narrow. It does not implement full CrossScopeFlow
grant evaluation -- that is a declared contract-stub gap per HEIM-5
(FABLE_COMPANION enforcement-level note: "v1 interim: allowlist + receipts,
honestly weaker -- full CrossScopeFlow runtime is itself xfail-skeleton
today; the invariant is written against the target and the interim is a
declared gap, not a silent one"). What it DOES enforce, for real, today:

- **Opaque `raw_ref` handle (HEIM-4/FABLE_COMPANION §1.1 item 2).** Callers
  outside this module never see or pass a filesystem path, a DB row id
  shape, or the raw table name. `raw_ref_for` mints an opaque
  ``"heimraw:<uuid>"`` token from a durable `RawRecord`; `read_raw_record`
  is the only function that resolves a `raw_ref` back to bytes, and it
  never returns or logs `source_path`.
- **Allowlist gate (interim CrossScopeFlow stand-in).** A read is refused
  -- `RawReadRefusedError`, never a silent None/empty return -- unless the
  caller's declared `reader` identity is on the configured allowlist
  (`HEIMDAL_RAW_READ_ALLOWLIST`, comma-separated reader ids; fail-loud if
  unset, mirroring `resolve_raw_store_key`). Grants do not compose: this
  allowlist governs *read* only -- it says nothing about export, which is
  its own operation with its own gate (T2 mitigation, ADR-0049 §11 SBS
  Impact "Boundary risk").
- **Receipt on every successful read (HEIM-1 append-only truth).** A
  successful read appends one `heimdal_raw_read_receipt` row recording
  who read (`reader`), what (`raw_ref`, `content_identity` -- never
  `source_path`), when (`read_at`), and why (`purpose`) in the SAME call
  that returns the decrypted bytes -- there is no "read now, receipt
  later" step, so a read can never happen without leaving a receipt.
  Refused reads raise before any receipt is written and before any
  decryption is attempted.
- **Append-only receipts.** Same discipline as the raw store itself: this
  module exposes no update/delete function, and the Postgres backend
  installs an identical reject-mutation trigger (migration
  `f1c7e2a9b4d6`).

Backend selection mirrors every other Heimdal store (dual-backend,
fail-loud resolution via `app.heimdal._backend.resolve_heimdal_backend`).

Out of scope for this slice: full CrossScopeFlow grant evaluation (v2);
export (a distinct, ungranted-by-this-module operation); ASR/attribution/
publish stages; cryptographic erasure (v2).
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from app.heimdal import raw_liveness, raw_store
from app.heimdal._backend import resolve_heimdal_backend

_TABLE = "heimdal_raw_read_receipt"

_MIGRATION_HINT = (
    "heimdal_raw_read_receipt schema is migration-owned: run 'alembic upgrade head' "
    "against this database. See app/alembic/versions/f1c7e2a9b4d6_heim_raw_read_receipt_v0.py."
)

_RAW_REF_PREFIX = "heimraw:"
_ALLOWLIST_ENV_VAR = "HEIMDAL_RAW_READ_ALLOWLIST"
_raw_read_stage_hook: Callable[[str], None] = lambda _stage: None


class RawReadReceiptSchemaMissingError(RuntimeError):
    """Raised when the Postgres backend is selected but the receipt table is absent."""


class AppendOnlyViolationError(RuntimeError):
    """Raised when a caller attempts to mutate an existing receipt row.

    Never raised by this module's own code paths (there is no update/delete
    API) -- it is raised when the Postgres backend surfaces the DB trigger's
    rejection of an UPDATE/DELETE statement issued outside this module.
    """


class RawReadRefusedError(RuntimeError):
    """Raised when a raw read is refused: not on the allowlist, or a bad/unknown raw_ref.

    Fail-loud (HEIM-5): never a silent None/empty-bytes return. No receipt
    is written for a refused read -- the receipt records reads that
    actually happened, not attempts.
    """


class RawReadAllowlistMissingError(RuntimeError):
    """Raised when no allowlist is configured -- refuse, never default-allow every reader."""


def resolve_read_allowlist() -> frozenset:
    """Resolve the configured set of reader identities permitted to read raw evidence.

    Fail-loud (HEIM-5 interim gate, mirrors `raw_store.resolve_raw_store_key`):
    an unset allowlist raises rather than silently permitting every caller.
    Comma-separated reader ids in `HEIMDAL_RAW_READ_ALLOWLIST`, e.g.
    ``"asr_stage,capture_adapter_selftest"``.
    """
    raw = os.environ.get(_ALLOWLIST_ENV_VAR)
    if raw is None:
        raise RawReadAllowlistMissingError(
            f"{_ALLOWLIST_ENV_VAR} is not set: raw evidence has no ungoverned read path "
            "(HEIM-5) and this module refuses to default-allow every reader. Set "
            f"{_ALLOWLIST_ENV_VAR} to a comma-separated list of permitted reader ids "
            "(may be empty string to explicitly allow no readers)."
        )
    return frozenset(item.strip() for item in raw.split(",") if item.strip())


def raw_ref_for(record: "raw_store.RawRecord | str") -> str:
    """Mint the opaque `raw_ref` handle for a durable raw record.

    Opaque per FABLE_COMPANION §1.1 item 2: resolvable only through
    :func:`read_raw_record`, never a URL, filesystem path, or raw table key
    a caller could use to bypass the gate.
    """
    record_id = record if isinstance(record, str) else record.id
    return f"{_RAW_REF_PREFIX}{record_id}"


def _record_id_from_raw_ref(raw_ref: str) -> str:
    if not isinstance(raw_ref, str) or not raw_ref.startswith(_RAW_REF_PREFIX):
        raise RawReadRefusedError(
            f"raw_ref {raw_ref!r} is not a recognized opaque handle (must start with "
            f"{_RAW_REF_PREFIX!r})."
        )
    record_id = raw_ref[len(_RAW_REF_PREFIX):]
    if not record_id:
        raise RawReadRefusedError(f"raw_ref {raw_ref!r} carries no record id.")
    return record_id


@dataclass(frozen=True)
class RawReadReceipt:
    """One durable, immutable row recording a successful gated raw read."""

    id: str
    raw_ref: str
    content_identity: str
    reader: str
    purpose: str
    read_at: datetime
    payload: Dict[str, Any]
    sequence: int


@dataclass(frozen=True)
class GatedRawRead:
    """The result of a successful gated read: decrypted bytes plus its receipt.

    ``receipt`` is the durable, append-only record proving this read
    happened -- callers hand this back for audit, never `source_path`.
    """

    plaintext: bytes
    receipt: RawReadReceipt
    representation_id: str
    storage_kind: str


class _MemoryReceiptStore:
    """In-process append-only store. Test/dev backend; volatile by design."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: List[RawReadReceipt] = []

    def append(self, receipt: RawReadReceipt) -> RawReadReceipt:
        with self._lock:
            row = RawReadReceipt(
                id=receipt.id,
                raw_ref=receipt.raw_ref,
                content_identity=receipt.content_identity,
                reader=receipt.reader,
                purpose=receipt.purpose,
                read_at=datetime.now(timezone.utc),
                payload=dict(receipt.payload),
                sequence=len(self._rows),
            )
            self._rows.append(row)
            return row

    def all_rows(self) -> List[RawReadReceipt]:
        with self._lock:
            return list(self._rows)

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()


_MEMORY_STORE = _MemoryReceiptStore()


def reset_memory_raw_read_receipts() -> None:
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
    """Explicit test-fixture opt-in, mirroring KERNEL-04/KERNEL-05 precedent."""
    return (os.environ.get("STORE_SCHEMA_AUTOCREATE") or "").strip().lower() in {"1", "true", "yes"}


def _assert_pg_schema(conn: Any) -> None:
    cur = conn.cursor()
    cur.execute("SELECT to_regclass(%s)", (_TABLE,))
    row = cur.fetchone()
    oid = row[0] if row else None
    if not oid:
        raise RawReadReceiptSchemaMissingError(f"Missing table '{_TABLE}'. {_MIGRATION_HINT}")


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
            raw_ref text NOT NULL,
            content_identity text NOT NULL,
            reader text NOT NULL,
            purpose text NOT NULL,
            read_at timestamptz NOT NULL DEFAULT now(),
            payload jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            sequence bigserial NOT NULL
        )
        """
    )
    cur.execute(f"CREATE INDEX IF NOT EXISTS heimdal_raw_read_receipt_seq_idx ON {_TABLE} (sequence)")
    cur.execute(
        f"CREATE INDEX IF NOT EXISTS heimdal_raw_read_receipt_raw_ref_idx ON {_TABLE} (raw_ref)"
    )
    cur.execute(
        """
        CREATE OR REPLACE FUNCTION heimdal_raw_read_receipt_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'heimdal_raw_read_receipt is append-only (HEIM-1): % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    cur.execute(f"DROP TRIGGER IF EXISTS heimdal_raw_read_receipt_no_update ON {_TABLE}")
    cur.execute(
        f"""
        CREATE TRIGGER heimdal_raw_read_receipt_no_update
        BEFORE UPDATE OR DELETE ON {_TABLE}
        FOR EACH ROW EXECUTE FUNCTION heimdal_raw_read_receipt_reject_mutation()
        """
    )


def _row_from_db(row: tuple) -> RawReadReceipt:
    (row_id, raw_ref, content_identity, reader, purpose, read_at, payload, sequence) = row

    def _as_dict(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if value is None:
            return {}
        return json.loads(value)

    return RawReadReceipt(
        id=str(row_id),
        raw_ref=str(raw_ref),
        content_identity=str(content_identity),
        reader=str(reader),
        purpose=str(purpose),
        read_at=read_at,
        payload=_as_dict(payload),
        sequence=int(sequence),
    )


_SELECT_COLUMNS = "id, raw_ref, content_identity, reader, purpose, read_at, payload, sequence"


class _PgReceiptStore:
    """Postgres-backed append-only receipt store; append-only enforced by DB trigger."""

    def __init__(self) -> None:
        conn = _pg_connect()
        try:
            _bootstrap_pg(conn)
        finally:
            conn.close()

    def append(self, receipt: RawReadReceipt) -> RawReadReceipt:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"""
                INSERT INTO {_TABLE} (id, raw_ref, content_identity, reader, purpose, payload)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                RETURNING {_SELECT_COLUMNS}
                """,
                (
                    receipt.id,
                    receipt.raw_ref,
                    receipt.content_identity,
                    receipt.reader,
                    receipt.purpose,
                    json.dumps(receipt.payload),
                ),
            )
            row = cur.fetchone()
            assert row is not None, "INSERT ... RETURNING produced no row"
            return _row_from_db(row)
        finally:
            conn.close()

    def all_rows(self) -> List[RawReadReceipt]:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(f"SELECT {_SELECT_COLUMNS} FROM {_TABLE} ORDER BY sequence ASC")
            return [_row_from_db(row) for row in cur.fetchall()]
        finally:
            conn.close()


def _backend() -> "_MemoryReceiptStore | _PgReceiptStore":
    if resolve_heimdal_backend() == "pg":
        return _PgReceiptStore()
    return _MEMORY_STORE


# ---------------------------------------------------------------------------
# Public gated-read API
# ---------------------------------------------------------------------------


def read_raw_record(
    raw_ref: str,
    *,
    reader: str,
    purpose: str,
    key: Optional[bytes] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> GatedRawRead:
    """The one sanctioned raw->plaintext read call (HEIM-5).

    Resolves ``raw_ref`` to its underlying `RawRecord` and decrypts it ONLY
    if ``reader`` is on the configured allowlist
    (:func:`resolve_read_allowlist`); otherwise raises
    :class:`RawReadRefusedError` before any decryption is attempted and
    before any receipt is written -- a refused read leaves no receipt
    because it never became a read.

    A successful read appends exactly one :class:`RawReadReceipt` (who:
    ``reader``; what: ``raw_ref`` + `content_identity`, never
    ``source_path``; when: `read_at`; why: ``purpose``) in this same call,
    then returns the decrypted bytes alongside that receipt. There is no
    code path that returns plaintext without also returning a persisted
    receipt.

    This is the interim CrossScopeFlow stand-in (declared HEIM-5 gap): it
    checks a static allowlist, not a full grant evaluation. A future full
    CrossScopeFlow integration replaces the allowlist check inside this
    function without changing the receipt contract other callers rely on.
    """
    if not isinstance(reader, str) or not reader.strip():
        raise ValueError(f"reader must be a non-empty string, got {reader!r}")
    if not isinstance(purpose, str) or not purpose.strip():
        raise ValueError(f"purpose must be a non-empty string, got {purpose!r}")

    record_id = _record_id_from_raw_ref(raw_ref)

    allowlist = resolve_read_allowlist()
    if reader not in allowlist:
        raise RawReadRefusedError(
            f"Raw read refused (HEIM-5): reader {reader!r} is not on the raw-read "
            f"allowlist. No decryption attempted; no receipt written. Set "
            f"{_ALLOWLIST_ENV_VAR} to include this reader id if the read is intended."
        )

    # Resolve receipt-store readiness before touching representation state.
    # A successful call may never decrypt bytes when it cannot durably receipt
    # the read, and unauthorized callers never reach either store.
    receipt_backend = _backend()

    initial = raw_store.resolve_active_raw_record(record_id)
    if initial is None:
        raise RawReadRefusedError(
            f"Raw read refused: raw_ref {raw_ref!r} does not resolve to any known raw "
            "record."
        )

    encryption_key = key if key is not None else raw_store.resolve_raw_store_key()
    with raw_liveness.raw_relocation_fence(
        record_id=record_id,
        content_identity=initial.content_identity,
    ):
        record = raw_store.resolve_active_raw_record(record_id)
        active = [
            representation
            for representation in raw_store.all_raw_representations(record_id)
            if representation.active
        ]
        if record is None or len(active) != 1:
            raise RawReadRefusedError(
                "Raw read refused: the exact active representation is unavailable."
            )
        _raw_read_stage_hook("after_active_representation_resolution")
        try:
            plaintext = raw_store.decrypt_and_verify_raw_bytes(
                record.content_identity,
                record.ciphertext,
                record.nonce,
                key=encryption_key,
            )
        except raw_store.RawRepresentationIdentityMismatchError as exc:
            raise RawReadRefusedError(
                "Raw read refused: active representation does not match immutable content identity. "
                "No receipt written and no plaintext returned."
            ) from exc

        receipt = RawReadReceipt(
            id=str(uuid4()),
            raw_ref=raw_ref,
            content_identity=record.content_identity,
            reader=reader,
            purpose=purpose,
            read_at=datetime.now(timezone.utc),
            payload=dict(payload or {}),
            sequence=-1,
        )
        persisted_receipt = receipt_backend.append(receipt)

        return GatedRawRead(
            plaintext=plaintext,
            receipt=persisted_receipt,
            representation_id=active[0].id,
            storage_kind=active[0].storage_kind,
        )


def all_raw_read_receipts() -> List[RawReadReceipt]:
    """Return every raw-read receipt in insertion order (diagnostic/test/audit helper)."""
    return _backend().all_rows()


__all__ = [
    "AppendOnlyViolationError",
    "GatedRawRead",
    "RawReadAllowlistMissingError",
    "RawReadReceipt",
    "RawReadReceiptSchemaMissingError",
    "RawReadRefusedError",
    "all_raw_read_receipts",
    "raw_ref_for",
    "read_raw_record",
    "reset_memory_raw_read_receipts",
    "resolve_read_allowlist",
]
