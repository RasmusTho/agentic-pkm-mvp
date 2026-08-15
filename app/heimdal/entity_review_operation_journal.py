"""Entity-review operation journal — EROJ-01 (#4350, parent #4349).

Specified by `docs/ENTITY_REVIEW_OPERATION_JOURNAL/COMMIT_OPERATION_AND_OUTBOX_VISIBILITY.md`
and bound by INV-EROJ-1..9 in `docs/ENTITY_REVIEW_OPERATION_JOURNAL/README.md`.
This module owns the narrow durable record that makes a human-confirmed
entity-review merge restart-safe at the transaction boundary:

- **One deterministic operation identity** (INV-EROJ-2): the active vault
  identity, queue entry id, decision-list position, SHA-256 digest of the
  exact human-authored decision mapping, and the original
  ``{from_id, into_id}`` determine one ``operation_id``. An identical retry
  selects the same row; a changed decision mapping for the same still-active
  queue entry **fails closed** (`EntityReviewOperationConflictError`) instead
  of minting a colliding second operation.
- **Claim before effect**: the initial operation row is committed by
  :meth:`EntityReviewOperationJournal.claim_operation` in a journal-owned
  transaction *before* the first entity-register note write, so a crash
  mid-effect resumes the same operation rather than starting a new one.
- **Atomic terminal evidence**:
  :meth:`EntityReviewOperationJournal.commit_merge_event` advances the
  operation to ``event_committed`` and inserts exactly one
  ``heimdal.register.entity.merged`` outbox row (deterministically keyed by
  the operation) in **one** Postgres transaction — both commit or neither
  does.
- **Committed visibility as a fence** (INV-EROJ-3, the #4253 failure):
  :meth:`EntityReviewOperationJournal.verify_committed_visibility` opens a
  **fresh connection** and requires it to observe both the terminal journal
  state and the matching committed outbox row. Visibility on the writer's or
  a caller's own uncommitted transaction is never sufficient — Postgres lets
  a transaction read its own uncommitted insert, and treating that read as
  durability once cleared the only retry anchor from ``pending`` before a
  rollback removed the event.

Authority boundary (INV-EROJ-1): the journal records that the Hub executed a
merge and whether its event is committed. It never decides that two entities
are the same, never amends the human decision history, and never becomes
identity truth — `entities/review.md` stays the decision history and
`_heimdal/register/*.md` stays canonical identity. Postgres state here is
operational coordination evidence only.

States are **monotonic**: ``claimed`` -> ``event_committed`` -> ``cleared``.
``cleared`` is recorded when the fence has passed and the pending clear is
being applied; it is what allows a later re-queue of the same queue entry id
to claim a fresh operation (the active-entry uniqueness below only covers
non-cleared rows). Completion is never inferred from the absence of a
``pending`` entry.

Schema ownership (INV-EROJ-8): the ``entity_review_operations`` table is
Alembic-owned (revision ``e7a2b9c4d1f8``) and **assert-only outside tests**
— a Postgres runtime with the table missing raises
:class:`EntityReviewOperationSchemaMissingError` with migration guidance.
Test environments opt in to create-on-demand via ``STORE_SCHEMA_AUTOCREATE=1``
(the KERNEL-04/#2766 fixture-flag precedent). Parity between the migration
and this module's audited shape is asserted by
``tests/migrations/test_entity_review_operation_journal_schema_parity.py``.

Deliberately out of scope here (INV-EROJ-7, INV-EROJ-9): target-evolution
lineage recovery (EROJ-02), globally unique split complements (EROJ-03), and
any generic saga API, worker, event bus, graph, second outbox, or UI.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid as uuid_module
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping, Protocol

from app.events.models import new_event
from app.events.types import HEIMDAL_REGISTER_ENTITY_MERGED
from app.instance.binding_ids import COMPATIBILITY_BINDING_ID
from app.services.outbox import write_outbox_event

# ---------------------------------------------------------------------------
# Identity derivation (INV-EROJ-2)
# ---------------------------------------------------------------------------

#: Fixed UUIDv5 namespace for deterministic entity-review operation ids.
#: Changing this value changes every derived operation id and outbox event key
#: and breaks resume/replay dedup — never rotate it.
ENTITY_REVIEW_OPERATION_NAMESPACE = uuid_module.UUID("8c1f4b9e-5a37-4d2e-9f60-3b7a2c8d514e")

#: Content-fingerprint label for the operation's deterministically keyed
#: ``heimdal.register.entity.merged`` outbox event (KERNEL-02 derivation via
#: ``app.services.outbox.derive_idempotency_key``): the source id is the
#: operation id, so a retried emission of the same operation maps to the same
#: outbox row while distinct operations never collide.
OPERATION_EVENT_FINGERPRINT = "entity-review-operation"

#: Envelope source for journal-committed merge events.
OPERATION_EVENT_SOURCE = "heimdal.entity_review"

STATE_CLAIMED = "claimed"
STATE_EVENT_COMMITTED = "event_committed"
STATE_CLEARED = "cleared"

_STATES = (STATE_CLAIMED, STATE_EVENT_COMMITTED, STATE_CLEARED)

JOURNAL_TABLE = "entity_review_operations"

_MIGRATION_HINT = (
    "entity_review_operations schema is migration-owned (EROJ-01, #4350): run "
    "'alembic upgrade head' against this database. See "
    "app/alembic/versions/e7a2b9c4d1f8_eroj01_entity_review_operations.py and "
    "docs/DB_SCHEMA.md :: Source Of Truth."
)

# The exact table shape (kept byte-identical with the Alembic revision
# e7a2b9c4d1f8; parity is asserted by
# tests/migrations/test_entity_review_operation_journal_schema_parity.py).
_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS entity_review_operations (
    operation_id UUID PRIMARY KEY,
    vault_identity TEXT NOT NULL,
    queue_entry_id TEXT NOT NULL,
    decision_position INTEGER NOT NULL,
    decision_digest TEXT NOT NULL,
    from_id TEXT NOT NULL,
    into_id TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'claimed'
        CONSTRAINT entity_review_operations_state_chk
        CHECK (state IN ('claimed', 'event_committed', 'cleared')),
    outbox_event_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

# One *active* (non-cleared) operation per (vault, queue entry): a changed
# decision digest for a still-active queue entry derives a different
# operation_id and this partial unique index makes the competing INSERT fail
# closed at the database even under concurrent applicators (INV-EROJ-2/6).
_ACTIVE_ENTRY_INDEX_DDL = """
CREATE UNIQUE INDEX IF NOT EXISTS entity_review_operations_active_entry_idx
    ON entity_review_operations (vault_identity, queue_entry_id)
    WHERE state <> 'cleared'
"""

_COLUMNS = (
    "operation_id",
    "vault_identity",
    "queue_entry_id",
    "decision_position",
    "decision_digest",
    "from_id",
    "into_id",
    "state",
    "outbox_event_id",
    "created_at",
    "updated_at",
)

_SELECT_COLUMNS = (
    "operation_id, vault_identity, queue_entry_id, decision_position, "
    "decision_digest, from_id, into_id, state, outbox_event_id"
)


class EntityReviewOperationJournalError(RuntimeError):
    """Raised for entity-review operation journal contract violations."""


class EntityReviewOperationConflictError(EntityReviewOperationJournalError):
    """A different decision mapping is already bound to this active queue entry.

    Fails closed (INV-EROJ-2 / INV-EROJ-6): the decision history and the
    pending queue entry are left unchanged; no second operation is minted.
    """


class EntityReviewOperationSchemaMissingError(EntityReviewOperationJournalError):
    """Migration-owned journal schema is absent in a Postgres-backed runtime."""


def decision_mapping_digest(raw_mapping: Mapping[str, Any]) -> str:
    """SHA-256 digest of the exact human-authored decision mapping.

    Canonical JSON (sorted keys) over the raw mapping exactly as persisted in
    `entities/review.md`'s append-only ``decisions`` history — including any
    forward-compatible fields this code does not interpret — so *any* change
    to the mapping changes the operation identity.
    """
    canonical = json.dumps(dict(raw_mapping), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def derive_operation_id(
    *,
    vault_identity: str,
    queue_entry_id: str,
    decision_position: int,
    decision_digest: str,
    from_id: str,
    into_id: str,
) -> str:
    """Derive the deterministic operation id from the INV-EROJ-2 tuple.

    ``uuid5(namespace, sha256(vault \\x1f queue_entry \\x1f position \\x1f
    digest \\x1f from \\x1f into))`` — an identical retry derives the same id;
    a different decision mapping, position, pair, or vault cannot collide.
    """
    parts = {
        "vault_identity": vault_identity,
        "queue_entry_id": queue_entry_id,
        "decision_digest": decision_digest,
        "from_id": from_id,
        "into_id": into_id,
    }
    for name, value in parts.items():
        if not isinstance(value, str) or not value.strip():
            raise EntityReviewOperationJournalError(
                f"derive_operation_id requires a non-empty string {name!r}, got {value!r}"
            )
    if not isinstance(decision_position, int) or decision_position < 0:
        raise EntityReviewOperationJournalError(
            f"derive_operation_id requires a non-negative decision_position, got {decision_position!r}"
        )
    digest = hashlib.sha256(
        "\x1f".join(
            (
                vault_identity,
                queue_entry_id,
                str(decision_position),
                decision_digest,
                from_id,
                into_id,
            )
        ).encode("utf-8")
    ).hexdigest()
    return str(uuid_module.uuid5(ENTITY_REVIEW_OPERATION_NAMESPACE, digest))


def derive_operation_event_id(operation_id: str) -> str:
    """Deterministic outbox idempotency key for the operation's merged event."""
    from app.services.outbox import derive_idempotency_key

    return derive_idempotency_key(
        HEIMDAL_REGISTER_ENTITY_MERGED, operation_id, OPERATION_EVENT_FINGERPRINT
    )


@dataclass(frozen=True)
class OperationRecord:
    """One committed row of the entity-review operation journal."""

    operation_id: str
    vault_identity: str
    queue_entry_id: str
    decision_position: int
    decision_digest: str
    from_id: str
    into_id: str
    state: str
    outbox_event_id: str


class EntityReviewOperationJournalPort(Protocol):
    """The narrow journal surface `apply_human_review_decisions` depends on.

    Production is :class:`EntityReviewOperationJournal` (Postgres). Tests may
    substitute an in-process double for applicator-routing coverage, but the
    committed-visibility fence itself is only proven against real Postgres
    (`tests/heimdal/test_entity_review_operation_journal.py`, pg-marked).
    """

    def claim_operation(
        self,
        *,
        vault_identity: str,
        queue_entry_id: str,
        decision_position: int,
        decision_digest: str,
        from_id: str,
        into_id: str,
    ) -> OperationRecord: ...

    def find_active_operation(
        self, *, vault_identity: str, queue_entry_id: str
    ) -> OperationRecord | None: ...

    def find_cleared_operation(
        self,
        *,
        vault_identity: str,
        queue_entry_id: str,
        from_id: str | None = None,
        into_id: str | None = None,
    ) -> OperationRecord | None: ...

    def commit_merge_event(self, operation: OperationRecord) -> OperationRecord: ...

    def verify_committed_visibility(self, operation: OperationRecord) -> bool: ...

    def mark_cleared(self, operation: OperationRecord) -> OperationRecord: ...


# ---------------------------------------------------------------------------
# Connection handling
# ---------------------------------------------------------------------------


def _schema_autocreate_enabled() -> bool:
    return (os.environ.get("STORE_SCHEMA_AUTOCREATE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _default_connection_factory() -> Any:
    """Open one manual-commit psycopg connection from the canonical env DSN.

    Manual commit is the whole point: every journal write is an explicit
    journal-owned transaction, and :meth:`verify_committed_visibility` opens a
    *separate* connection from the same factory so its reads can only see
    committed state.
    """
    import psycopg

    from app.db.dsn import resolve_dsn

    url = os.environ.get("DATABASE_URL") or os.environ.get("DB_DSN")
    if not url:
        raise EntityReviewOperationJournalError(
            "entity-review operation journal requires DATABASE_URL or DB_DSN"
        )
    return psycopg.connect(resolve_dsn(url))


def _col(row: Any, index: int, key: str) -> Any:
    if isinstance(row, dict):
        return row[key]
    return row[index]


def _exec(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> Any:
    if hasattr(conn, "cursor"):
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur
    return conn.execute(sql, params)


def _is_unique_violation(exc: Exception) -> bool:
    sqlstate = getattr(exc, "sqlstate", None)
    if sqlstate is None:
        diag = getattr(exc, "diag", None)
        sqlstate = getattr(diag, "sqlstate", None)
    return sqlstate == "23505"


def ensure_journal_schema(conn: Any) -> None:
    """Assert (or, under the test flag, create) the journal schema.

    Assert-only outside tests: raises
    :class:`EntityReviewOperationSchemaMissingError` with ``alembic upgrade
    head`` guidance when the migration-owned table or a required column is
    absent. With ``STORE_SCHEMA_AUTOCREATE=1`` (test fixtures only) the
    audited shape is created on demand; the DDL here is what
    ``tests/migrations/test_entity_review_operation_journal_schema_parity.py``
    holds byte-parity with the Alembic revision.
    """
    if _schema_autocreate_enabled():
        _exec(conn, _TABLE_DDL)
        _exec(conn, _ACTIVE_ENTRY_INDEX_DDL)
        conn.commit()
        return
    cur = _exec(conn, "SELECT to_regclass(%s) AS oid", (JOURNAL_TABLE,))
    row = cur.fetchone() if hasattr(cur, "fetchone") else None
    oid = _col(row, 0, "oid") if row is not None else None
    if not oid:
        raise EntityReviewOperationSchemaMissingError(
            f"Missing table '{JOURNAL_TABLE}' in the configured Postgres. {_MIGRATION_HINT}"
        )
    cur = _exec(
        conn,
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s",
        (JOURNAL_TABLE,),
    )
    rows = cur.fetchall() if hasattr(cur, "fetchall") else []
    present = {_col(r, 0, "column_name") for r in rows}
    missing = [column for column in _COLUMNS if column not in present]
    if missing:
        raise EntityReviewOperationSchemaMissingError(
            f"{JOURNAL_TABLE} table is missing column(s) {missing}. {_MIGRATION_HINT}"
        )


def bootstrap(conn: Any = None, *, connection_factory: Callable[[], Any] | None = None) -> None:
    """Schema preflight entrypoint (assert-only outside tests).

    Mirrors ``app.services.outbox.bootstrap``'s KERNEL-05 posture for this
    table so fixtures and the schema-parity test share one producer.
    """
    close = False
    if conn is None:
        factory = connection_factory or _default_connection_factory
        conn = factory()
        close = True
    try:
        ensure_journal_schema(conn)
    finally:
        if close:
            conn.close()


class EntityReviewOperationJournal:
    """Postgres-backed entity-review operation journal (EROJ-01).

    Every method opens its own connection from ``connection_factory`` and
    owns its transaction. No method ever accepts or reuses a caller's
    connection: caller-transaction visibility is exactly the #4253 defect
    this journal exists to fence out.
    """

    def __init__(self, *, connection_factory: Callable[[], Any] | None = None) -> None:
        self._connection_factory = connection_factory or _default_connection_factory

    # -- internal ------------------------------------------------------------

    def _open(self) -> Any:
        conn = self._connection_factory()
        autocommit = getattr(conn, "autocommit", False)
        if autocommit:
            try:
                conn.close()
            finally:
                raise EntityReviewOperationJournalError(
                    "journal connections must be manual-commit; an autocommit "
                    "connection cannot express the atomic journal-owned transaction"
                )
        return conn

    def _load_row(self, conn: Any, operation_id: str) -> OperationRecord | None:
        cur = _exec(
            conn,
            f"SELECT {_SELECT_COLUMNS} FROM {JOURNAL_TABLE} WHERE operation_id = %s",
            (operation_id,),
        )
        row = cur.fetchone() if hasattr(cur, "fetchone") else None
        if row is None:
            return None
        record = OperationRecord(
            operation_id=str(_col(row, 0, "operation_id")),
            vault_identity=str(_col(row, 1, "vault_identity")),
            queue_entry_id=str(_col(row, 2, "queue_entry_id")),
            decision_position=int(_col(row, 3, "decision_position")),
            decision_digest=str(_col(row, 4, "decision_digest")),
            from_id=str(_col(row, 5, "from_id")),
            into_id=str(_col(row, 6, "into_id")),
            state=str(_col(row, 7, "state")),
            outbox_event_id=str(_col(row, 8, "outbox_event_id")),
        )
        if record.state not in _STATES:
            raise EntityReviewOperationJournalError(
                f"operation {record.operation_id} has unknown state {record.state!r}; "
                "refusing to proceed (INV-EROJ-6)"
            )
        return record

    @staticmethod
    def _validate_loaded(record: OperationRecord, expected: OperationRecord) -> OperationRecord:
        immutable = (
            "vault_identity",
            "queue_entry_id",
            "decision_position",
            "decision_digest",
            "from_id",
            "into_id",
            "outbox_event_id",
        )
        for field_name in immutable:
            if getattr(record, field_name) != getattr(expected, field_name):
                raise EntityReviewOperationJournalError(
                    f"operation {record.operation_id} column {field_name!r} does not match "
                    "its derivation inputs; journal row is malformed and the queue entry "
                    "stays pending (INV-EROJ-6)"
                )
        return record

    # -- API -----------------------------------------------------------------

    def load_operation(self, operation_id: str) -> OperationRecord | None:
        """Read one committed operation row on a fresh connection."""
        conn = self._open()
        try:
            ensure_journal_schema(conn)
            return self._load_row(conn, operation_id)
        finally:
            conn.close()

    def find_active_operation(
        self, *, vault_identity: str, queue_entry_id: str
    ) -> OperationRecord | None:
        """The active (non-cleared) operation bound to this queue entry, if any.

        Resume is keyed on the ENTRY, not on re-deriving an id from the current
        decision content: after the decision history is edited mid-operation,
        the current mapping derives a different id, and only this entry-keyed
        read can still reach the in-flight row (review F1 on #4350). At most
        one active row can exist (the partial unique index); more than one is
        malformed and fails closed (INV-EROJ-6).
        """
        conn = self._open()
        try:
            ensure_journal_schema(conn)
            cur = _exec(
                conn,
                f"SELECT operation_id FROM {JOURNAL_TABLE} "
                "WHERE vault_identity = %s AND queue_entry_id = %s AND state <> %s",
                (vault_identity, queue_entry_id, STATE_CLEARED),
            )
            rows = cur.fetchall() if hasattr(cur, "fetchall") else []
            if not rows:
                return None
            if len(rows) > 1:
                raise EntityReviewOperationJournalError(
                    f"queue entry {queue_entry_id!r} has {len(rows)} active operations; "
                    "the journal is malformed and the entry stays pending (INV-EROJ-6)"
                )
            return self._load_row(conn, str(_col(rows[0], 0, "operation_id")))
        finally:
            conn.close()

    def find_cleared_operation(
        self,
        *,
        vault_identity: str,
        queue_entry_id: str,
        from_id: str | None = None,
        into_id: str | None = None,
    ) -> OperationRecord | None:
        """The most recent CLEARED operation for this entry (optionally by pair).

        Guards matrix row 4's forbidden outcome (review F4 on #4350): a stop
        between `mark_cleared` and the pending-note write leaves the entry
        visible while its operation already released the active slot. A later
        identical re-approval must finish the interrupted clear instead of
        claiming a fresh operation and emitting a second event for the same
        merge. With the exact original pair supplied, a genuinely new merge of
        a split-reverted pair (effects no longer present) never matches. The
        pair-less form supports the round-2 divergence diagnostic: a non-merge
        ruling that clears an entry must be able to name a previously
        completed merge that remains materialised for it.
        """
        if (from_id is None) != (into_id is None):
            raise EntityReviewOperationJournalError(
                "find_cleared_operation requires both from_id and into_id, or neither"
            )
        conn = self._open()
        try:
            ensure_journal_schema(conn)
            sql = (
                f"SELECT operation_id FROM {JOURNAL_TABLE} "
                "WHERE vault_identity = %s AND queue_entry_id = %s AND state = %s "
            )
            params: tuple[Any, ...] = (vault_identity, queue_entry_id, STATE_CLEARED)
            if from_id is not None and into_id is not None:
                sql += "AND from_id = %s AND into_id = %s "
                params = (*params, from_id, into_id)
            sql += "ORDER BY updated_at DESC, operation_id LIMIT 1"
            cur = _exec(conn, sql, params)
            row = cur.fetchone() if hasattr(cur, "fetchone") else None
            if row is None:
                return None
            return self._load_row(conn, str(_col(row, 0, "operation_id")))
        finally:
            conn.close()

    def claim_operation(
        self,
        *,
        vault_identity: str,
        queue_entry_id: str,
        decision_position: int,
        decision_digest: str,
        from_id: str,
        into_id: str,
    ) -> OperationRecord:
        """Commit the initial operation row before the first register effect.

        Idempotent for an identical retry (same derived id selects the same
        row). A different decision mapping while another operation for this
        ``(vault_identity, queue_entry_id)`` is still active fails closed
        with :class:`EntityReviewOperationConflictError` — enforced both by
        an explicit probe and by the partial unique index.
        """
        operation_id = derive_operation_id(
            vault_identity=vault_identity,
            queue_entry_id=queue_entry_id,
            decision_position=decision_position,
            decision_digest=decision_digest,
            from_id=from_id,
            into_id=into_id,
        )
        expected = OperationRecord(
            operation_id=operation_id,
            vault_identity=vault_identity,
            queue_entry_id=queue_entry_id,
            decision_position=decision_position,
            decision_digest=decision_digest,
            from_id=from_id,
            into_id=into_id,
            state=STATE_CLAIMED,
            outbox_event_id=derive_operation_event_id(operation_id),
        )
        conn = self._open()
        try:
            ensure_journal_schema(conn)
            existing = self._load_row(conn, operation_id)
            if existing is not None:
                conn.rollback()
                return self._validate_loaded(existing, expected)
            cur = _exec(
                conn,
                f"SELECT operation_id FROM {JOURNAL_TABLE} "
                "WHERE vault_identity = %s AND queue_entry_id = %s AND state <> %s",
                (vault_identity, queue_entry_id, STATE_CLEARED),
            )
            active = cur.fetchall() if hasattr(cur, "fetchall") else []
            conflicting = [
                str(_col(r, 0, "operation_id"))
                for r in active
                if str(_col(r, 0, "operation_id")) != operation_id
            ]
            if conflicting:
                conn.rollback()
                raise EntityReviewOperationConflictError(
                    f"queue entry {queue_entry_id!r} already has active operation "
                    f"{conflicting[0]} bound to a different decision mapping; the changed "
                    "decision fails closed and the entry stays pending (INV-EROJ-2/6). "
                    "To recover, restore this entry's original decision in "
                    "entities/review.md (the active operation then resumes cleanly), "
                    "or wait for EROJ-02."
                )
            try:
                _exec(
                    conn,
                    f"INSERT INTO {JOURNAL_TABLE} "
                    "(operation_id, vault_identity, queue_entry_id, decision_position, "
                    "decision_digest, from_id, into_id, state, outbox_event_id) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (operation_id) DO NOTHING",
                    (
                        operation_id,
                        vault_identity,
                        queue_entry_id,
                        decision_position,
                        decision_digest,
                        from_id,
                        into_id,
                        STATE_CLAIMED,
                        expected.outbox_event_id,
                    ),
                )
            except Exception as exc:
                conn.rollback()
                if _is_unique_violation(exc):
                    raise EntityReviewOperationConflictError(
                        f"queue entry {queue_entry_id!r} gained a concurrent active operation "
                        "bound to a different decision mapping; failing closed (INV-EROJ-2/6). "
                        "To recover, restore this entry's original decision in "
                        "entities/review.md, or wait for EROJ-02."
                    ) from exc
                raise
            conn.commit()
            committed = self._load_row(conn, operation_id)
            if committed is None:
                raise EntityReviewOperationJournalError(
                    f"operation {operation_id} was not durable after claim commit"
                )
            return self._validate_loaded(committed, expected)
        finally:
            conn.close()

    def commit_merge_event(self, operation: OperationRecord) -> OperationRecord:
        """Atomically commit terminal journal state plus exactly one event.

        One journal-owned Postgres transaction advances
        ``claimed -> event_committed`` and inserts the operation's
        deterministically keyed ``heimdal.register.entity.merged`` outbox row
        carrying the original ``from_id``, original ``into_id``, and
        ``operation_id`` (INV-EROJ-4). Both commit or neither does. Retrying
        an already event-committed operation is a no-op: the atomic
        transaction guarantees its event row is already durable.
        """
        conn = self._open()
        try:
            ensure_journal_schema(conn)
            cur = _exec(
                conn,
                f"UPDATE {JOURNAL_TABLE} SET state = %s, updated_at = now() "
                "WHERE operation_id = %s AND state = %s",
                (STATE_EVENT_COMMITTED, operation.operation_id, STATE_CLAIMED),
            )
            advanced = getattr(cur, "rowcount", 0) == 1
            if not advanced:
                conn.rollback()
                current = self._load_row(conn, operation.operation_id)
                if current is not None and current.state in (
                    STATE_EVENT_COMMITTED,
                    STATE_CLEARED,
                ):
                    return self._validate_loaded(current, operation)
                raise EntityReviewOperationJournalError(
                    f"operation {operation.operation_id} cannot commit its merge event from "
                    f"state {current.state if current is not None else 'absent'!r}; "
                    "failing closed (INV-EROJ-6)"
                )
            event = new_event(
                event_type=HEIMDAL_REGISTER_ENTITY_MERGED,
                payload={
                    "from_id": operation.from_id,
                    "into_id": operation.into_id,
                    "operation_id": operation.operation_id,
                },
                source=OPERATION_EVENT_SOURCE,
            )
            write_outbox_event(event, conn=conn, idempotency_key=operation.outbox_event_id)
            conn.commit()
            return replace(operation, state=STATE_EVENT_COMMITTED)
        except Exception:
            try:
                conn.rollback()
            except Exception:  # pragma: no cover - close still runs
                pass
            raise
        finally:
            conn.close()

    def verify_committed_visibility(self, operation: OperationRecord) -> bool:
        """The fence (INV-EROJ-3): fresh-transaction proof of the commit.

        Opens a **new** connection from the factory and returns True only when
        that transaction observes (a) the journal row in a terminal
        (``event_committed``/``cleared``) state with its immutable binding
        intact and (b) the matching committed outbox row whose payload carries
        the original ``from_id``, original ``into_id``, and ``operation_id``.
        A row visible only to the writer's or a caller's uncommitted
        transaction can never satisfy this read.
        """
        conn = self._open()
        try:
            ensure_journal_schema(conn)
            record = self._load_row(conn, operation.operation_id)
            if record is None or record.state not in (STATE_EVENT_COMMITTED, STATE_CLEARED):
                return False
            self._validate_loaded(record, operation)
            cur = _exec(
                conn,
                "SELECT topic, payload FROM outbox "
                "WHERE id = %s OR (legacy_key = %s AND vault_binding_id = %s) "
                "ORDER BY (id = %s) DESC LIMIT 1",
                (
                    record.outbox_event_id,
                    record.outbox_event_id,
                    COMPATIBILITY_BINDING_ID,
                    record.outbox_event_id,
                ),
            )
            row = cur.fetchone() if hasattr(cur, "fetchone") else None
            if row is None:
                return False
            topic = str(_col(row, 0, "topic"))
            raw_payload = _col(row, 1, "payload")
            if topic != HEIMDAL_REGISTER_ENTITY_MERGED:
                return False
            envelope = raw_payload if isinstance(raw_payload, dict) else json.loads(raw_payload)
            payload = envelope.get("payload") if isinstance(envelope, dict) else None
            if not isinstance(payload, dict):
                return False
            return (
                payload.get("from_id") == record.from_id
                and payload.get("into_id") == record.into_id
                and payload.get("operation_id") == record.operation_id
            )
        finally:
            conn.close()

    def mark_cleared(self, operation: OperationRecord) -> OperationRecord:
        """Record that the fence passed and the pending clear is being applied.

        Monotonic ``event_committed -> cleared``; idempotent when already
        cleared. Any other state fails closed — clearing is only ever
        authorized downstream of :meth:`verify_committed_visibility`.
        """
        conn = self._open()
        try:
            ensure_journal_schema(conn)
            cur = _exec(
                conn,
                f"UPDATE {JOURNAL_TABLE} SET state = %s, updated_at = now() "
                "WHERE operation_id = %s AND state = %s",
                (STATE_CLEARED, operation.operation_id, STATE_EVENT_COMMITTED),
            )
            if getattr(cur, "rowcount", 0) == 1:
                conn.commit()
                return replace(operation, state=STATE_CLEARED)
            conn.rollback()
            current = self._load_row(conn, operation.operation_id)
            if current is not None and current.state == STATE_CLEARED:
                return self._validate_loaded(current, operation)
            raise EntityReviewOperationJournalError(
                f"operation {operation.operation_id} cannot be marked cleared from state "
                f"{current.state if current is not None else 'absent'!r}; "
                "failing closed (INV-EROJ-6)"
            )
        except Exception:
            try:
                conn.rollback()
            except Exception:  # pragma: no cover - close still runs
                pass
            raise
        finally:
            conn.close()


__all__ = [
    "ENTITY_REVIEW_OPERATION_NAMESPACE",
    "JOURNAL_TABLE",
    "OPERATION_EVENT_FINGERPRINT",
    "OPERATION_EVENT_SOURCE",
    "STATE_CLAIMED",
    "STATE_CLEARED",
    "STATE_EVENT_COMMITTED",
    "EntityReviewOperationConflictError",
    "EntityReviewOperationJournal",
    "EntityReviewOperationJournalError",
    "EntityReviewOperationJournalPort",
    "EntityReviewOperationSchemaMissingError",
    "OperationRecord",
    "bootstrap",
    "decision_mapping_digest",
    "derive_operation_event_id",
    "derive_operation_id",
    "ensure_journal_schema",
]
