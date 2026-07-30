"""Entity-review operation journal proofs — EROJ-01 (#4350, parent #4349).

Real-Postgres proofs of the committed-visibility mechanism specified by
`docs/ENTITY_REVIEW_OPERATION_JOURNAL/COMMIT_OPERATION_AND_OUTBOX_VISIBILITY.md`:

- `test_operation_identity_binds_exact_human_decision` — INV-EROJ-2: one
  deterministic operation id per exact human decision; a changed mapping for
  a still-active queue entry fails closed; a different vault never collides;
  a cleared operation releases the queue entry id for a later re-queue.
- `test_operation_claim_commits_before_first_register_effect` — the initial
  journal row is durable (visible to a fresh connection) even when the very
  first register note write crashes, and the retry resumes the SAME
  operation.
- `test_mid_effect_crash_resumes_and_completes_target_side` — partial-failure
  matrix row 2: a source redirect without its target complement is completed
  on resume, never treated as a complete merge and never re-applied.
- `test_merge_event_commit_is_visible_on_fresh_connection_before_pending_clear`
  — terminal journal state and exactly one deterministically keyed outbox
  event commit atomically (both-or-neither), and a fresh transaction
  observes the original `from_id`, original `into_id`, and `operation_id`.
- `test_caller_transaction_rollback_cannot_clear_pending_or_hide_merge_event`
  — the #4253 protected failure: an outbox insert visible only to the
  caller's own uncommitted transaction never authorizes the pending clear;
  after rollback the retry commits exactly one event and only then clears.
- `test_effect_before_event_commit_recovers_one_durable_event` — a stop after
  both register effects but before the event commit resumes the same
  operation, emits exactly once, and preserves the append-only decision
  mappings byte-for-byte.

These tests run against a real Postgres by contract ("Run the
rollback/visibility proof against Postgres rather than a fake connection"):
cross-connection committed visibility is the mechanism under test and a fake
connection cannot prove it. Applicator *routing* coverage that needs no real
transaction lives non-pg in tests/heimdal/test_entity_confirm.py.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

import psycopg
import pytest

from app.heimdal import entity_review_operation_journal as journal_module
from app.heimdal.attribution_stage import RESOLUTION_AMBIGUOUS, EntityMention
from app.heimdal.entity_confirm import (
    EntityConfirmError,
    ReviewDecision,
    apply_human_review_decisions,
    pending_review_entries,
    queue_for_review,
)
from app.heimdal.entity_register import (
    LIFECYCLE_MERGED,
    EntityRegister,
    EntityRegisterError,
)
from app.heimdal.entity_review_operation_journal import (
    STATE_CLAIMED,
    STATE_CLEARED,
    STATE_EVENT_COMMITTED,
    EntityReviewOperationConflictError,
    EntityReviewOperationJournal,
    EntityReviewOperationJournalError,
    OperationRecord,
    derive_operation_id,
)
from app.heimdal.settings_notes import (
    DEFAULT_SETTINGS_DIR,
    ENTITY_REVIEW,
    SettingsNote,
    note_rel_path,
    read_settings_note,
    write_settings_note,
)
from app.services import outbox as outbox_module
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard

pytestmark = pytest.mark.pg

MERGED_TOPIC = "heimdal.register.entity.merged"


# ---------------------------------------------------------------------------
# Scratch database plumbing (per-test isolation on the configured Postgres)
# ---------------------------------------------------------------------------


def _admin_dsn() -> str:
    from app.db.dsn import resolve_dsn

    dsn = resolve_dsn()
    if not dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    return dsn


@pytest.fixture
def scratch_dsn(monkeypatch: pytest.MonkeyPatch) -> Any:
    """One throwaway database with the journal + outbox schema installed."""
    admin_dsn = _admin_dsn()
    try:
        probe = psycopg.connect(admin_dsn, connect_timeout=2)
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unavailable: {exc}")
    probe.close()

    name = f"scratch_eroj01_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    base, _, _ = admin_dsn.rpartition("/")
    dsn = f"{base}/{name}"

    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    with psycopg.connect(dsn) as conn:
        journal_module.ensure_journal_schema(conn)
    outbox_module.bootstrap()

    yield dsn

    try:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    except Exception:  # pragma: no cover - cleanup best effort
        pass


def _journal(dsn: str) -> EntityReviewOperationJournal:
    return EntityReviewOperationJournal(connection_factory=lambda: psycopg.connect(dsn))


def _merged_event_rows(dsn: str) -> list[tuple[str, dict[str, Any]]]:
    """(id, inner payload) of committed merged-topic outbox rows, fresh conn."""
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT id, payload FROM outbox WHERE topic = %s ORDER BY created_at",
            (MERGED_TOPIC,),
        ).fetchall()
    result: list[tuple[str, dict[str, Any]]] = []
    for row in rows:
        envelope = row[1] if isinstance(row[1], dict) else json.loads(row[1])
        result.append((str(row[0]), dict(envelope.get("payload") or {})))
    return result


def _journal_row(dsn: str, operation_id: str) -> tuple[str, str] | None:
    """(state, outbox_event_id) as observed by an independent fresh connection."""
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT state, outbox_event_id FROM entity_review_operations "
            "WHERE operation_id = %s",
            (operation_id,),
        ).fetchone()
    if row is None:
        return None
    return (str(row[0]), str(row[1]))


# ---------------------------------------------------------------------------
# Vault / register fixtures (temp-vault convention from test_entity_confirm)
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]]):
        self._rows = rows

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)


class _RegisterEmissionStub:
    """In-memory sink for the register's own mint/split emissions so the real
    DB outbox contains ONLY journal-committed rows and event counts are exact."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _FakeCursor:
        text = " ".join(sql.lower().split())
        assert text.startswith("insert into outbox (id,"), text
        row_id = params[0]
        if row_id in self.rows:
            return _FakeCursor([])
        self.rows[row_id] = {"id": row_id, "topic": params[1], "payload": params[2]}
        return _FakeCursor([(row_id,)])

    def close(self) -> None:  # pragma: no cover - psycopg parity
        pass


class _CrashingRegister(EntityRegister):
    """Real register whose Nth armed note write raises — a process stop at an
    exact effect boundary, arming AFTER fixture setup writes."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fail_on_write: int | None = None
        self._armed_writes = 0

    def arm(self, fail_on_write: int) -> None:
        self.fail_on_write = fail_on_write
        self._armed_writes = 0

    def disarm(self) -> None:
        self.fail_on_write = None

    def _write_entry(self, entry: Any) -> None:
        if self.fail_on_write is not None:
            self._armed_writes += 1
            if self._armed_writes >= self.fail_on_write:
                raise EntityRegisterError(
                    f"simulated crash before note write #{self._armed_writes}"
                )
        super()._write_entry(entry)


def _vault_root(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _allowing_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _register(vault_root: Path, cls: type[EntityRegister] = EntityRegister) -> EntityRegister:
    return cls(
        vault_context=VaultContext(
            status="selected",
            active_vault_id="vault-test",
            active_vault_name="Vault Test",
            active_vault_path=str(vault_root),
        ),
        write_guard=_allowing_guard(),
        conn=_RegisterEmissionStub(),
    )


def _queue_merge_decision(
    vault_root: Path, register: EntityRegister
) -> tuple[str, str, str, dict[str, Any]]:
    """Mint two entities, queue one mid-band mention, and write one human
    merge decision. Returns (queue_entry_id, from_id, into_id, raw_decision)."""
    source = register.mint_canonical("Anna fran gymmet", aliases=["Anna G"])
    target = register.mint_canonical("Anna Svensson", aliases=["Anna"])
    mention = EntityMention(
        mention_id="mention:eroj-1",
        surface_form="Anna",
        resolution=RESOLUTION_AMBIGUOUS,
        kind_hint="person",
        confidence=0.75,
    )
    entry = queue_for_review(
        vault_root,
        mention,
        candidate_entity_ids=[source, target],
        write_guard=_allowing_guard(),
    )
    raw_decision = ReviewDecision(
        queue_entry_id=entry.queue_entry_id,
        action="merge",
        from_id=source,
        into_id=target,
    ).to_dict()
    note = read_settings_note(vault_root, ENTITY_REVIEW, settings_dir=DEFAULT_SETTINGS_DIR)
    assert note is not None
    write_settings_note(
        vault_root,
        SettingsNote(spec=ENTITY_REVIEW, values={**note.values, "decisions": [raw_decision]}),
        settings_dir=DEFAULT_SETTINGS_DIR,
        write_guard=_allowing_guard(),
    )
    return entry.queue_entry_id, source, target, raw_decision


def _review_note_path(vault_root: Path) -> Path:
    return vault_root / note_rel_path(ENTITY_REVIEW, settings_dir=DEFAULT_SETTINGS_DIR)


def _persisted_decisions(vault_root: Path) -> list[Any]:
    note = read_settings_note(vault_root, ENTITY_REVIEW, settings_dir=DEFAULT_SETTINGS_DIR)
    assert note is not None
    return list(note.values.get("decisions") or [])


def _claim_kwargs(
    vault_root: Path, queue_entry_id: str, from_id: str, into_id: str, raw_decision: dict[str, Any]
) -> dict[str, Any]:
    return {
        "vault_identity": str(vault_root.resolve()),
        "queue_entry_id": queue_entry_id,
        "decision_position": 0,
        "decision_digest": journal_module.decision_mapping_digest(raw_decision),
        "from_id": from_id,
        "into_id": into_id,
    }


# ---------------------------------------------------------------------------
# AC 1 — deterministic identity, fail-closed digest binding (INV-EROJ-2)
# ---------------------------------------------------------------------------


def test_operation_identity_binds_exact_human_decision(
    scratch_dsn: str, tmp_path: Path
) -> None:
    vault_root = _vault_root(tmp_path)
    register = _register(vault_root)
    queue_entry_id, from_id, into_id, raw_decision = _queue_merge_decision(vault_root, register)
    journal = _journal(scratch_dsn)
    kwargs = _claim_kwargs(vault_root, queue_entry_id, from_id, into_id, raw_decision)

    # Deterministic across retries: the derivation is a pure function of the
    # INV-EROJ-2 tuple, and every varied component derives a different id.
    baseline = derive_operation_id(**kwargs)
    assert derive_operation_id(**kwargs) == baseline
    assert derive_operation_id(**{**kwargs, "vault_identity": "/other/vault"}) != baseline
    assert derive_operation_id(**{**kwargs, "queue_entry_id": "review:other"}) != baseline
    assert derive_operation_id(**{**kwargs, "decision_position": 1}) != baseline
    assert (
        derive_operation_id(**{**kwargs, "decision_digest": "0" * 64}) != baseline
    )
    assert derive_operation_id(**{**kwargs, "from_id": into_id, "into_id": from_id}) != baseline

    # An identical retry selects the same committed row.
    first = journal.claim_operation(**kwargs)
    again = journal.claim_operation(**kwargs)
    assert first.operation_id == baseline == again.operation_id
    assert first.state == STATE_CLAIMED
    with psycopg.connect(scratch_dsn) as conn:
        count = conn.execute(
            "SELECT count(*) FROM entity_review_operations WHERE queue_entry_id = %s",
            (queue_entry_id,),
        ).fetchone()
    assert count == (1,)

    # A changed decision mapping for the same still-active queue entry fails
    # closed instead of minting a colliding second operation.
    edited = dict(raw_decision)
    edited["audit_tag"] = "human-edited-after-claim"
    changed = {
        **kwargs,
        "decision_position": 1,
        "decision_digest": journal_module.decision_mapping_digest(edited),
    }
    with pytest.raises(EntityReviewOperationConflictError):
        journal.claim_operation(**changed)
    with psycopg.connect(scratch_dsn) as conn:
        count = conn.execute(
            "SELECT count(*) FROM entity_review_operations WHERE queue_entry_id = %s",
            (queue_entry_id,),
        ).fetchone()
    assert count == (1,), "a conflicting claim must not create a second operation"

    # A different vault cannot collide with this queue entry's operation.
    other_vault = journal.claim_operation(**{**kwargs, "vault_identity": "/other/vault"})
    assert other_vault.operation_id != baseline

    # Once the original operation is fully cleared it releases the queue
    # entry id: a genuinely new review of a re-queued entry may claim.
    committed = journal.commit_merge_event(first)
    assert journal.verify_committed_visibility(committed) is True
    journal.mark_cleared(committed)
    reclaimed = journal.claim_operation(**changed)
    assert reclaimed.operation_id != baseline
    assert reclaimed.state == STATE_CLAIMED


# ---------------------------------------------------------------------------
# AC 2 — the initial journal row commits before the first register effect
# ---------------------------------------------------------------------------


def test_operation_claim_commits_before_first_register_effect(
    scratch_dsn: str, tmp_path: Path
) -> None:
    vault_root = _vault_root(tmp_path)
    register = _register(vault_root, _CrashingRegister)
    assert isinstance(register, _CrashingRegister)
    queue_entry_id, from_id, into_id, raw_decision = _queue_merge_decision(vault_root, register)
    journal = _journal(scratch_dsn)
    expected_id = derive_operation_id(
        **_claim_kwargs(vault_root, queue_entry_id, from_id, into_id, raw_decision)
    )
    decisions_before = _persisted_decisions(vault_root)

    # Crash at the very first register note write of the merge.
    register.arm(fail_on_write=1)
    with pytest.raises(EntityConfirmError, match="simulated crash"):
        apply_human_review_decisions(vault_root, register=register, journal=journal)

    # The operation row is already durable — an independent fresh connection
    # observes it — while no register effect exists and pending is intact.
    row = _journal_row(scratch_dsn, expected_id)
    assert row is not None and row[0] == STATE_CLAIMED
    source_entry = register.get_entry(from_id)
    assert source_entry is not None and source_entry.lifecycle != LIFECYCLE_MERGED
    assert [e.queue_entry_id for e in pending_review_entries(vault_root)] == [queue_entry_id]
    assert _merged_event_rows(scratch_dsn) == []

    # The retry resumes the SAME operation and completes it exactly once.
    register.disarm()
    applied = apply_human_review_decisions(vault_root, register=register, journal=journal)
    assert len(applied) == 1
    assert applied[0].merged is True
    assert applied[0].operation_id == expected_id
    row = _journal_row(scratch_dsn, expected_id)
    assert row is not None and row[0] == STATE_CLEARED
    events = _merged_event_rows(scratch_dsn)
    assert len(events) == 1
    assert pending_review_entries(vault_root) == ()
    assert _persisted_decisions(vault_root) == decisions_before


def test_mid_effect_crash_resumes_and_completes_target_side(
    scratch_dsn: str, tmp_path: Path
) -> None:
    """Partial-failure matrix row 2: source redirect written, complement absent."""
    vault_root = _vault_root(tmp_path)
    register = _register(vault_root, _CrashingRegister)
    assert isinstance(register, _CrashingRegister)
    queue_entry_id, from_id, into_id, raw_decision = _queue_merge_decision(vault_root, register)
    journal = _journal(scratch_dsn)
    expected_id = derive_operation_id(
        **_claim_kwargs(vault_root, queue_entry_id, from_id, into_id, raw_decision)
    )

    # Crash between the source-redirect write and the target-complement write.
    register.arm(fail_on_write=2)
    with pytest.raises(EntityConfirmError, match="simulated crash"):
        apply_human_review_decisions(vault_root, register=register, journal=journal)

    source_entry = register.get_entry(from_id)
    target_entry = register.get_entry(into_id)
    assert source_entry is not None and source_entry.merged_into == into_id
    assert target_entry is not None and from_id not in target_entry.merged_from
    assert _merged_event_rows(scratch_dsn) == [], (
        "a source redirect alone must never be treated as a complete merge"
    )
    assert [e.queue_entry_id for e in pending_review_entries(vault_root)] == [queue_entry_id]

    register.disarm()
    applied = apply_human_review_decisions(vault_root, register=register, journal=journal)
    assert len(applied) == 1 and applied[0].operation_id == expected_id
    target_entry = register.get_entry(into_id)
    assert target_entry is not None and from_id in target_entry.merged_from
    assert len(_merged_event_rows(scratch_dsn)) == 1
    assert pending_review_entries(vault_root) == ()


# ---------------------------------------------------------------------------
# AC 3 — atomic terminal commit, fresh-connection visibility
# ---------------------------------------------------------------------------


def test_merge_event_commit_is_visible_on_fresh_connection_before_pending_clear(
    scratch_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = _vault_root(tmp_path)
    register = _register(vault_root)
    queue_entry_id, from_id, into_id, raw_decision = _queue_merge_decision(vault_root, register)
    journal = _journal(scratch_dsn)
    operation = journal.claim_operation(
        **_claim_kwargs(vault_root, queue_entry_id, from_id, into_id, raw_decision)
    )
    register.ensure_merge_effects(from_id, into_id)

    # Atomicity, negative half: a failure inside the journal-owned transaction
    # commits NEITHER the terminal state nor the event.
    real_write = journal_module.write_outbox_event

    def _boom(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("simulated failure inside the journal-owned transaction")

    monkeypatch.setattr(journal_module, "write_outbox_event", _boom)
    with pytest.raises(RuntimeError, match="journal-owned transaction"):
        journal.commit_merge_event(operation)
    monkeypatch.setattr(journal_module, "write_outbox_event", real_write)
    row = _journal_row(scratch_dsn, operation.operation_id)
    assert row is not None and row[0] == STATE_CLAIMED
    assert _merged_event_rows(scratch_dsn) == []

    # Atomicity, positive half: one journal-owned transaction commits both,
    # and an INDEPENDENT fresh connection observes the terminal journal state
    # plus the matching outbox row with the original pair and operation id —
    # all while the queue entry is still pending (clear comes only later).
    committed = journal.commit_merge_event(operation)
    assert committed.state == STATE_EVENT_COMMITTED
    row = _journal_row(scratch_dsn, operation.operation_id)
    assert row is not None and row[0] == STATE_EVENT_COMMITTED
    events = _merged_event_rows(scratch_dsn)
    assert len(events) == 1
    event_id, payload = events[0]
    assert event_id == operation.outbox_event_id
    assert payload["from_id"] == from_id
    assert payload["into_id"] == into_id
    assert payload["operation_id"] == operation.operation_id
    assert [e.queue_entry_id for e in pending_review_entries(vault_root)] == [queue_entry_id]

    # Exactly one: an idempotent retry of the terminal commit adds nothing.
    journal.commit_merge_event(operation)
    assert len(_merged_event_rows(scratch_dsn)) == 1
    assert journal.verify_committed_visibility(committed) is True


# ---------------------------------------------------------------------------
# AC 4 — the #4253 failure: caller-transaction visibility never clears pending
# ---------------------------------------------------------------------------


class _CallerTransactionJournal(EntityReviewOperationJournal):
    """The #4253 defect as a journal double: the 'commit' step writes the
    outbox row on a CALLER-owned transaction it never commits, then reports
    the operation as event-committed. Everything else (claim, the fence,
    mark_cleared) is the real Postgres implementation — the fence must be
    what stops this lie from clearing `pending`."""

    def __init__(self, *, connection_factory: Any, caller_conn: Any) -> None:
        super().__init__(connection_factory=connection_factory)
        self.caller_conn = caller_conn

    def commit_merge_event(self, operation: OperationRecord) -> OperationRecord:
        from app.events.models import new_event

        event = new_event(
            event_type=MERGED_TOPIC,
            payload={
                "from_id": operation.from_id,
                "into_id": operation.into_id,
                "operation_id": operation.operation_id,
            },
            source="heimdal.entity_review",
        )
        outbox_module.write_outbox_event(
            event, conn=self.caller_conn, idempotency_key=operation.outbox_event_id
        )
        # Same-transaction read-your-own-write: the caller can see the row...
        seen = self.caller_conn.execute(
            "SELECT count(*) FROM outbox WHERE id = %s", (operation.outbox_event_id,)
        ).fetchone()
        assert seen == (1,), "the caller transaction must see its own uncommitted insert"
        # ...and on the #4253 path that visibility was treated as durability.
        return replace(operation, state=STATE_EVENT_COMMITTED)


def test_caller_transaction_rollback_cannot_clear_pending_or_hide_merge_event(
    scratch_dsn: str, tmp_path: Path
) -> None:
    vault_root = _vault_root(tmp_path)
    register = _register(vault_root)
    queue_entry_id, from_id, into_id, raw_decision = _queue_merge_decision(vault_root, register)
    decisions_before = _persisted_decisions(vault_root)

    caller_conn = psycopg.connect(scratch_dsn)  # manual commit — a caller-owned txn
    try:
        broken = _CallerTransactionJournal(
            connection_factory=lambda: psycopg.connect(scratch_dsn),
            caller_conn=caller_conn,
        )

        # The applicator refuses the clear: the fresh-transaction fence cannot
        # observe the uncommitted caller-side insert (nor a committed terminal
        # journal state), so the queue entry MUST stay pending.
        with pytest.raises(EntityConfirmError, match="committed visibility"):
            apply_human_review_decisions(vault_root, register=register, journal=broken)
        assert [e.queue_entry_id for e in pending_review_entries(vault_root)] == [
            queue_entry_id
        ], "same-connection visibility must never authorize a pending clear"
        assert _persisted_decisions(vault_root) == decisions_before
        assert _merged_event_rows(scratch_dsn) == [], (
            "no committed merge event may exist yet"
        )

        # The caller rolls back: its event insert vanishes — this is exactly
        # where #4253 lost the only merge event after pending was cleared.
        caller_conn.rollback()
        assert _merged_event_rows(scratch_dsn) == []
    finally:
        caller_conn.close()

    # Because the retry anchor survived, the retry resumes the SAME operation
    # through the real journal and commits exactly one visible merge event.
    journal = _journal(scratch_dsn)
    applied = apply_human_review_decisions(vault_root, register=register, journal=journal)
    assert len(applied) == 1 and applied[0].merged is True
    events = _merged_event_rows(scratch_dsn)
    assert len(events) == 1
    assert events[0][1]["from_id"] == from_id
    assert events[0][1]["into_id"] == into_id
    assert events[0][1]["operation_id"] == applied[0].operation_id
    assert pending_review_entries(vault_root) == ()
    assert _persisted_decisions(vault_root) == decisions_before


# ---------------------------------------------------------------------------
# AC 5 — stop after effects, before event commit: one durable event on resume
# ---------------------------------------------------------------------------


def test_effect_before_event_commit_recovers_one_durable_event(
    scratch_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = _vault_root(tmp_path)
    register = _register(vault_root)
    queue_entry_id, from_id, into_id, raw_decision = _queue_merge_decision(vault_root, register)
    journal = _journal(scratch_dsn)
    note_bytes_before = _review_note_path(vault_root).read_bytes()
    decisions_before = _persisted_decisions(vault_root)

    # Stop AFTER both register effects but BEFORE the event commit.
    real_commit = EntityReviewOperationJournal.commit_merge_event

    def _crash(
        self: EntityReviewOperationJournal, operation: OperationRecord
    ) -> OperationRecord:
        raise EntityReviewOperationJournalError("simulated stop before event commit")

    monkeypatch.setattr(EntityReviewOperationJournal, "commit_merge_event", _crash)
    with pytest.raises(EntityConfirmError, match="simulated stop"):
        apply_human_review_decisions(vault_root, register=register, journal=journal)
    monkeypatch.setattr(EntityReviewOperationJournal, "commit_merge_event", real_commit)

    # Both effects exist, no event, operation still claimed, review note
    # byte-for-byte untouched (pending AND append-only decisions).
    source_entry = register.get_entry(from_id)
    target_entry = register.get_entry(into_id)
    assert source_entry is not None and source_entry.merged_into == into_id
    assert target_entry is not None and from_id in target_entry.merged_from
    assert _merged_event_rows(scratch_dsn) == []
    expected_id = derive_operation_id(
        **_claim_kwargs(vault_root, queue_entry_id, from_id, into_id, raw_decision)
    )
    row = _journal_row(scratch_dsn, expected_id)
    assert row is not None and row[0] == STATE_CLAIMED
    assert _review_note_path(vault_root).read_bytes() == note_bytes_before

    # Resume: the same operation validates the existing effects, commits
    # exactly one event for the original pair, and only then clears pending.
    applied = apply_human_review_decisions(vault_root, register=register, journal=journal)
    assert len(applied) == 1
    assert applied[0].operation_id == expected_id
    events = _merged_event_rows(scratch_dsn)
    assert len(events) == 1
    assert events[0][1] == {
        "from_id": from_id,
        "into_id": into_id,
        "operation_id": expected_id,
    }
    assert pending_review_entries(vault_root) == ()
    # The append-only human decision mappings survive byte-for-byte.
    assert _persisted_decisions(vault_root) == decisions_before

    # A later replay is a no-op: nothing pending, still exactly one event.
    assert apply_human_review_decisions(vault_root, register=register, journal=journal) == ()
    assert len(_merged_event_rows(scratch_dsn)) == 1
