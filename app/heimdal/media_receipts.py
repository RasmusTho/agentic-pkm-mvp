"""Durable media-admission receipt store (CDLM-01, issue #4384).

The receipt is the *client-visible* definition of durable acceptance
(INV-CDLM-1, `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/README.md`): a row
here exists only after the original is durably in the encrypted raw store
(`app.heimdal.raw_store`) and the admission event is committed to the outbox.
Transport success, folder placement, and iCloud sync are never receipts.

Why this is its own store rather than a field on the raw record:

- **Cardinality.** The raw store holds one object per *content hash*; receipts
  are keyed by the transfer identity `(capture_id, content_sha256)`
  (INV-CDLM-3). Two clients that capture byte-identical content share one raw
  object but each needs its own answer to "was *my* capture accepted?".
- **Lookup direction.** Recovery after a lost response queries by
  `capture_id`; the raw store is only addressable by `content_identity`.
- **Read posture.** Answering a receipt query must never materialize raw
  evidence, so the query never touches the raw table.

Storage discipline follows the Heimdal family verbatim
(`app.heimdal.raw_read_gate`, migration `f1c7e2a9b4d6`): append-only, one row
per identity, memory backend for dev/test and a migration-owned Postgres
table (`heimdal_media_receipt`, migration `e3c1a7f5d2b8`) whose absence fails
loud rather than silently degrading.

Receipt identity is *derived*, not random: ``receipt_id`` is a uuid5 over
`(capture_id, content_sha256)`, so a resend after a lost response returns the
same identity even before the store is read, and the primary key itself makes
a second receipt for the same pair impossible. `append_media_receipt` returns
``(row, created)`` with ``created=False`` for a replay -- the same shape
`app.heimdal.raw_store.insert_raw_record` uses.
"""

from __future__ import annotations

import json
import os
import threading
import uuid as uuid_module
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.heimdal._backend import resolve_heimdal_backend

_TABLE = "heimdal_media_receipt"

_MIGRATION_HINT = (
    "heimdal_media_receipt schema is migration-owned: run 'alembic upgrade head' "
    "against this database. See app/alembic/versions/e3c1a7f5d2b8_heim_media_receipt_v0.py."
)

# Stable namespace for `receipt_id` derivation. Never regenerate it: changing
# it would re-mint every receipt identity and break client-side idempotency.
_RECEIPT_NAMESPACE = uuid_module.UUID("0a3d9f7c-5e21-5b48-9c0e-4f2b6d8a1c37")
_RECEIPT_ID_PREFIX = "rcp_"


class MediaReceiptSchemaMissingError(RuntimeError):
    """Raised when the Postgres backend is selected but the receipt table is absent."""


class MediaReceiptPersistenceError(RuntimeError):
    """Raised when a receipt could not be durably persisted or read back.

    Distinct from a schema problem: this is the durability failure that must
    surface as a named `not_acknowledged` state rather than an unnamed error,
    because the caller was about to acknowledge a capture on the strength of it.
    """


@dataclass(frozen=True)
class MediaReceipt:
    """One durable, immutable record of an accepted media admission.

    ``capture_id`` is the client-minted transfer id for the governed ingress
    lane. For a watched-folder admission with no sidecar `capture_id` it is the
    content hash itself -- "content-hash keyed", per the vertical's
    partial-failure matrix -- so one query parameter serves both lanes.
    """

    receipt_id: str
    capture_id: str
    content_sha256: str
    raw_ref: str
    kind: str
    lane: str
    admitted_at: datetime
    trace_id: str
    payload: Dict[str, Any]
    sequence: int


def canonical_capture_id(value: Any) -> str:
    """Canonical storage/lookup form of a capture id.

    Typed ``Any`` deliberately: one caller is the watched-folder lane, whose id
    comes from an untrusted HCAP-07 sidecar that is not type-validated upstream,
    so this must accept whatever arrived and answer with a string.

    This module owns the rule, so no caller can key a receipt one way and look it
    up another. A UUID collapses to its plain lowercase hyphenated form, because
    `UUID()` accepts uppercase, braced, unhyphenated, and `urn:uuid:` spellings of
    the same id — and clients really do differ here (Swift's
    `UUID().uuidString` is uppercase). Keying on the spelling would mint a
    receipt per spelling and, worse, answer `unknown` on the recovery query for a
    capture that *is* durably admitted.

    A value that is not a UUID is returned stripped and unchanged: the
    watched-folder lane legitimately keys its receipts by content hash.
    """
    if not isinstance(value, str):
        return ""
    text = value.strip()
    try:
        return str(uuid_module.UUID(text))
    except (ValueError, AttributeError, TypeError):
        return text


def derive_receipt_id(capture_id: str, content_sha256: str) -> str:
    """Derive the stable ``receipt_id`` for one transfer identity.

    Deterministic by construction: a resend of the same
    `(capture_id, content_sha256)` pair resolves to the same receipt identity
    without a prior read, which is what makes the idempotent-replay answer
    correct even if a previous attempt crashed mid-flight. The capture id is
    canonicalized first (:func:`canonical_capture_id`), so an equivalent spelling
    is the same identity rather than a new one.
    """
    if not isinstance(capture_id, str) or not capture_id.strip():
        raise ValueError(f"capture_id must be a non-empty string, got {capture_id!r}")
    if not isinstance(content_sha256, str) or not content_sha256.strip():
        raise ValueError(f"content_sha256 must be a non-empty string, got {content_sha256!r}")
    digest = uuid_module.uuid5(
        _RECEIPT_NAMESPACE, f"{canonical_capture_id(capture_id)}\x1f{content_sha256}"
    )
    return f"{_RECEIPT_ID_PREFIX}{digest.hex}"


class _MemoryReceiptStore:
    """In-process append-only store. Test/dev backend; volatile by design."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: List[MediaReceipt] = []
        self._by_receipt_id: Dict[str, MediaReceipt] = {}

    def append(self, receipt: MediaReceipt) -> tuple[MediaReceipt, bool]:
        """Insert; returns ``(row, created)``. ``created=False`` on a replay."""
        with self._lock:
            existing = self._by_receipt_id.get(receipt.receipt_id)
            if existing is not None:
                return existing, False
            row = MediaReceipt(
                receipt_id=receipt.receipt_id,
                capture_id=receipt.capture_id,
                content_sha256=receipt.content_sha256,
                raw_ref=receipt.raw_ref,
                kind=receipt.kind,
                lane=receipt.lane,
                admitted_at=receipt.admitted_at,
                trace_id=receipt.trace_id,
                payload=dict(receipt.payload),
                sequence=len(self._rows),
            )
            self._rows.append(row)
            self._by_receipt_id[row.receipt_id] = row
            return row, True

    def get_by_receipt_id(self, receipt_id: str) -> Optional[MediaReceipt]:
        with self._lock:
            return self._by_receipt_id.get(receipt_id)

    def first_by_capture_ids(self, capture_ids: List[str]) -> Dict[str, MediaReceipt]:
        wanted = set(capture_ids)
        found: Dict[str, MediaReceipt] = {}
        with self._lock:
            for row in self._rows:
                if row.capture_id in wanted and row.capture_id not in found:
                    found[row.capture_id] = row
            return found

    def all_rows(self) -> List[MediaReceipt]:
        with self._lock:
            return list(self._rows)

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()
            self._by_receipt_id.clear()


_MEMORY_STORE = _MemoryReceiptStore()


def reset_memory_media_receipts() -> None:
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
        raise MediaReceiptSchemaMissingError(f"Missing table '{_TABLE}'. {_MIGRATION_HINT}")


def _bootstrap_pg(conn: Any) -> None:
    if not _schema_autocreate_enabled():
        _assert_pg_schema(conn)
        return
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            receipt_id text PRIMARY KEY,
            capture_id text NOT NULL,
            content_sha256 text NOT NULL,
            raw_ref text NOT NULL,
            kind text NOT NULL,
            lane text NOT NULL,
            admitted_at timestamptz NOT NULL DEFAULT now(),
            trace_id text NOT NULL DEFAULT '',
            payload jsonb NOT NULL DEFAULT '{{}}'::jsonb,
            sequence bigserial NOT NULL
        )
        """
    )
    cur.execute(f"CREATE INDEX IF NOT EXISTS heimdal_media_receipt_seq_idx ON {_TABLE} (sequence)")
    cur.execute(
        f"CREATE INDEX IF NOT EXISTS heimdal_media_receipt_capture_id_idx ON {_TABLE} (capture_id)"
    )
    cur.execute(
        """
        CREATE OR REPLACE FUNCTION heimdal_media_receipt_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'heimdal_media_receipt is append-only (HEIM-1): % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    cur.execute(f"DROP TRIGGER IF EXISTS heimdal_media_receipt_no_update ON {_TABLE}")
    cur.execute(
        f"""
        CREATE TRIGGER heimdal_media_receipt_no_update
        BEFORE UPDATE OR DELETE ON {_TABLE}
        FOR EACH ROW EXECUTE FUNCTION heimdal_media_receipt_reject_mutation()
        """
    )


_SELECT_COLUMNS = (
    "receipt_id, capture_id, content_sha256, raw_ref, kind, lane, admitted_at, "
    "trace_id, payload, sequence"
)


def _row_from_db(row: tuple) -> MediaReceipt:
    (
        receipt_id,
        capture_id,
        content_sha256,
        raw_ref,
        kind,
        lane,
        admitted_at,
        trace_id,
        payload,
        sequence,
    ) = row

    def _as_dict(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if value is None:
            return {}
        return json.loads(value)

    return MediaReceipt(
        receipt_id=str(receipt_id),
        capture_id=str(capture_id),
        content_sha256=str(content_sha256),
        raw_ref=str(raw_ref),
        kind=str(kind),
        lane=str(lane),
        admitted_at=admitted_at,
        trace_id=str(trace_id or ""),
        payload=_as_dict(payload),
        sequence=int(sequence),
    )


class _PgReceiptStore:
    """Postgres-backed append-only receipt store; append-only enforced by DB trigger."""

    def __init__(self) -> None:
        conn = _pg_connect()
        try:
            _bootstrap_pg(conn)
        finally:
            conn.close()

    def append(self, receipt: MediaReceipt) -> tuple[MediaReceipt, bool]:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            # `ON CONFLICT DO NOTHING` (never DO UPDATE): the append-only
            # trigger rejects UPDATE, and a replay must return the receipt
            # that was already durably acknowledged, unchanged.
            cur.execute(
                f"""
                INSERT INTO {_TABLE}
                    (receipt_id, capture_id, content_sha256, raw_ref, kind, lane, admitted_at, trace_id, payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (receipt_id) DO NOTHING
                RETURNING {_SELECT_COLUMNS}
                """,
                (
                    receipt.receipt_id,
                    receipt.capture_id,
                    receipt.content_sha256,
                    receipt.raw_ref,
                    receipt.kind,
                    receipt.lane,
                    receipt.admitted_at,
                    receipt.trace_id,
                    json.dumps(receipt.payload),
                ),
            )
            row = cur.fetchone()
            if row is not None:
                return _row_from_db(row), True
            existing = self.get_by_receipt_id(receipt.receipt_id)
            if existing is None:
                raise MediaReceiptPersistenceError(
                    f"receipt {receipt.receipt_id!r} was neither inserted nor readable in "
                    f"'{_TABLE}'; refusing to report an acknowledgement that is not durable."
                )
            return existing, False
        finally:
            conn.close()

    def get_by_receipt_id(self, receipt_id: str) -> Optional[MediaReceipt]:
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"SELECT {_SELECT_COLUMNS} FROM {_TABLE} WHERE receipt_id = %s", (receipt_id,)
            )
            row = cur.fetchone()
            return _row_from_db(row) if row else None
        finally:
            conn.close()

    def first_by_capture_ids(self, capture_ids: List[str]) -> Dict[str, MediaReceipt]:
        """Resolve a whole bounded batch in one statement on one connection.

        The recovery query is a bounded batch, so a per-id round trip would open
        two connections per requested id; this keeps a 100-id reconnect query at
        one connection and one scan of the `capture_id` index.
        """
        conn = _pg_connect()
        try:
            _assert_pg_schema(conn)
            cur = conn.cursor()
            cur.execute(
                f"SELECT {_SELECT_COLUMNS} FROM {_TABLE} WHERE capture_id = ANY(%s) "
                "ORDER BY sequence ASC",
                (list(capture_ids),),
            )
            found: Dict[str, MediaReceipt] = {}
            for row in cur.fetchall():
                receipt = _row_from_db(row)
                found.setdefault(receipt.capture_id, receipt)
            return found
        finally:
            conn.close()

    def all_rows(self) -> List[MediaReceipt]:
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
# Public receipt API
# ---------------------------------------------------------------------------


def append_media_receipt(
    *,
    capture_id: str,
    content_sha256: str,
    raw_ref: str,
    kind: str,
    lane: str,
    trace_id: str = "",
    payload: Optional[Dict[str, Any]] = None,
    admitted_at: Optional[datetime] = None,
) -> tuple[MediaReceipt, bool]:
    """Persist one admission receipt. Returns ``(row, created)``.

    ``created=False`` means this transfer identity was already acknowledged and
    the pre-existing receipt is returned unchanged -- the idempotent-replay
    answer clients rely on after a lost response (INV-CDLM-3).

    Callers must not invoke this before the raw write is durable and the
    admission event is committed: this row *is* the acknowledgement, so writing
    it early would manufacture the false receipt INV-CDLM-1 forbids.
    """
    for name, value in (("raw_ref", raw_ref), ("kind", kind), ("lane", lane)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string, got {value!r}")

    receipt = MediaReceipt(
        receipt_id=derive_receipt_id(capture_id, content_sha256),
        capture_id=canonical_capture_id(capture_id),
        content_sha256=content_sha256,
        raw_ref=raw_ref,
        kind=kind,
        lane=lane,
        admitted_at=admitted_at or datetime.now(timezone.utc),
        trace_id=trace_id or "",
        payload=dict(payload or {}),
        sequence=-1,
    )
    return _backend().append(receipt)


def get_media_receipt(capture_id: str, content_sha256: str) -> Optional[MediaReceipt]:
    """Look up the receipt for one transfer identity (idempotency check).

    Keyed by the derived receipt id, which canonicalizes the capture id, so an
    equivalent spelling resolves to the same receipt.
    """
    return _backend().get_by_receipt_id(derive_receipt_id(capture_id, content_sha256))


def find_media_receipts_by_capture_ids(capture_ids: List[str]) -> Dict[str, MediaReceipt]:
    """Resolve the earliest receipt per requested ``capture_id``, in one backend pass.

    The recovery query carries `capture_id`s and not content hashes, so this is
    the lookup that answers `admitted` vs `unknown`. Ids with no receipt are
    simply absent from the result — that absence is the `unknown` answer, and it
    must mean "never arrived", never "you spelled your own id differently": each
    id is canonicalized for the lookup and the result is keyed back by the
    **requested** spelling so a caller can align answers with its own request.

    A client that reused one `capture_id` for different bytes gets the first
    admission; the returned ``content_sha256`` is what lets it detect that reuse.
    """
    wanted = {canonical_capture_id(value) for value in capture_ids}
    wanted.discard("")
    if not wanted:
        return {}
    found = _backend().first_by_capture_ids(sorted(wanted))
    resolved: Dict[str, MediaReceipt] = {}
    for value in capture_ids:
        receipt = found.get(canonical_capture_id(value))
        if receipt is not None:
            resolved[value] = receipt
    return resolved


def all_media_receipts() -> List[MediaReceipt]:
    """Return every media receipt in insertion order (diagnostic/test/audit helper)."""
    return _backend().all_rows()


__all__ = [
    "MediaReceipt",
    "MediaReceiptPersistenceError",
    "MediaReceiptSchemaMissingError",
    "all_media_receipts",
    "append_media_receipt",
    "canonical_capture_id",
    "derive_receipt_id",
    "find_media_receipts_by_capture_ids",
    "get_media_receipt",
    "reset_memory_media_receipts",
]
