"""Entity confirmation surface tests — Epic #3019 slice A17 (JE, #3037).

Covers the governing Issue's three acceptance criteria:

- `test_merge_writes_redirect_and_is_reversible` -- a confirmed merge writes
  `merged_from:` (target) + a redirect (`merged_into` on the source) and is
  reversible via `split()` (red-team F5, exercising the REAL
  `app.heimdal.entity_register.EntityRegister.merge`/`split`, not a mock).
- `test_midband_routes_to_queue` -- mid-band mentions (confidence in
  `[LOW_THRESHOLD, HIGH_THRESHOLD)`) route to the `entities/review.md` queue.
- `test_high_band_auto_links` -- above `HIGH_THRESHOLD`, a mention auto-links
  with no human step (no queue write, no register mutation).

Plus negative/completeness coverage: low-band/unresolved mentions produce no
routing action; a `reject` decision clears the queue without touching the
register; idempotent re-application of an already-applied decision is a
no-op; queuing twice for the same mention replaces rather than duplicates.

No network, no real Postgres: mirrors `tests/heimdal/test_entity_register.py`'s
temp-vault-fixture convention (`VaultContext` over `tmp_path`, `FakeOutboxConn`
in-memory outbox emulation) -- every test exercises the real production
`EntityRegister.merge`/`split` and the real `entities/review.md` note
read/write path, never a mock of either.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from app.heimdal.attribution_stage import (
    RESOLUTION_AMBIGUOUS,
    RESOLUTION_RESOLVED,
    RESOLUTION_UNRESOLVED,
    EntityMention,
)
from app.heimdal.entity_confirm import (
    HIGH_THRESHOLD,
    LOW_THRESHOLD,
    EntityConfirmError,
    ReviewDecision,
    RoutingDecision,
    apply_human_review_decisions,
    pending_review_entries,
    queue_for_review,
    route_mention,
)
from app.heimdal.entity_register import (
    KIND_PERSON,
    LIFECYCLE_CANONICAL,
    LIFECYCLE_MERGED,
    EntityRegister,
)
from app.heimdal.entity_review_operation_journal import (
    STATE_CLAIMED,
    STATE_CLEARED,
    STATE_EVENT_COMMITTED,
    EntityReviewOperationConflictError,
    OperationRecord,
    derive_operation_event_id,
    derive_operation_id,
)
from app.heimdal.settings_notes import (
    DEFAULT_SETTINGS_DIR,
    ENTITY_REVIEW,
    SettingsNote,
    read_settings_note,
    write_settings_note,
)
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard

pytestmark = pytest.mark.not_pg


# ---------------------------------------------------------------------------
# Shared fixtures (mirrors test_entity_register.py)
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, rows: list[tuple]):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeOutboxConn:
    """In-memory emulation of the keyed outbox insert (PK-conflict semantics),
    identical shape to test_entity_register.py's own fake."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def execute(self, sql: str, params: tuple = ()) -> _FakeCursor:
        text = " ".join(sql.lower().split())
        if text.startswith("insert into outbox (id,"):
            assert "on conflict (id) do nothing" in text
            row_id, topic, payload, created_at, attempts = params
            if row_id in self.rows:
                return _FakeCursor([])
            self.rows[row_id] = {
                "id": row_id,
                "topic": topic,
                "payload": payload,
                "created_at": created_at,
                "delivered_at": None,
                "attempts": attempts,
            }
            return _FakeCursor([(row_id,)])
        raise AssertionError(f"unexpected SQL shape reached the outbox: {text!r}")

    def close(self) -> None:  # pragma: no cover - psycopg parity
        pass

    def rows_for(self, topic: str) -> list[dict[str, Any]]:
        return [r for r in self.rows.values() if r["topic"] == topic]


class _InMemoryJournal:
    """In-process `EntityReviewOperationJournalPort` double for applicator
    ROUTING coverage: honest deterministic identity, fail-closed digest
    conflicts, and monotonic states — but no transaction physics. The
    committed-visibility fence itself is only proven against real Postgres
    (tests/heimdal/test_entity_review_operation_journal.py, pg-marked).

    ``log`` records ("<journal method>", operation_id) in call order and may
    be shared with `_LoggingRegister` to assert journal-vs-register ordering.
    ``visibility`` simulates the fence outcome: False models "the fresh
    transaction cannot observe the committed evidence"."""

    def __init__(self, *, visibility: bool = True, log: list[tuple[str, str]] | None = None):
        self.visibility = visibility
        self.log = log if log is not None else []
        self.operations: dict[str, OperationRecord] = {}

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
        operation_id = derive_operation_id(
            vault_identity=vault_identity,
            queue_entry_id=queue_entry_id,
            decision_position=decision_position,
            decision_digest=decision_digest,
            from_id=from_id,
            into_id=into_id,
        )
        record = self.operations.get(operation_id)
        if record is None:
            for other in self.operations.values():
                if (
                    other.vault_identity == vault_identity
                    and other.queue_entry_id == queue_entry_id
                    and other.state != STATE_CLEARED
                ):
                    raise EntityReviewOperationConflictError(
                        f"queue entry {queue_entry_id!r} already has active operation "
                        f"{other.operation_id}"
                    )
            record = OperationRecord(
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
            self.operations[operation_id] = record
        self.log.append(("claim_operation", operation_id))
        return record

    def find_active_operation(
        self, *, vault_identity: str, queue_entry_id: str
    ) -> OperationRecord | None:
        self.log.append(("find_active_operation", queue_entry_id))
        for record in self.operations.values():
            if (
                record.vault_identity == vault_identity
                and record.queue_entry_id == queue_entry_id
                and record.state != STATE_CLEARED
            ):
                return record
        return None

    def find_cleared_operation(
        self,
        *,
        vault_identity: str,
        queue_entry_id: str,
        from_id: str | None = None,
        into_id: str | None = None,
    ) -> OperationRecord | None:
        self.log.append(("find_cleared_operation", queue_entry_id))
        for record in self.operations.values():
            if (
                record.vault_identity == vault_identity
                and record.queue_entry_id == queue_entry_id
                and record.state == STATE_CLEARED
                and (from_id is None or record.from_id == from_id)
                and (into_id is None or record.into_id == into_id)
            ):
                return record
        return None

    def commit_merge_event(self, operation: OperationRecord) -> OperationRecord:
        record = self.operations[operation.operation_id]
        if record.state == STATE_CLAIMED:
            record = replace(record, state=STATE_EVENT_COMMITTED)
            self.operations[record.operation_id] = record
        self.log.append(("commit_merge_event", record.operation_id))
        return record

    def verify_committed_visibility(self, operation: OperationRecord) -> bool:
        self.log.append(("verify_committed_visibility", operation.operation_id))
        record = self.operations.get(operation.operation_id)
        return bool(
            self.visibility
            and record is not None
            and record.state in (STATE_EVENT_COMMITTED, STATE_CLEARED)
        )

    def mark_cleared(self, operation: OperationRecord) -> OperationRecord:
        record = replace(self.operations[operation.operation_id], state=STATE_CLEARED)
        self.operations[record.operation_id] = record
        self.log.append(("mark_cleared", record.operation_id))
        return record


class _LoggingRegister(EntityRegister):
    """Real register that mirrors every note write into a shared call log so
    tests can prove journal-before-register ordering."""

    def __init__(self, *args: Any, log: list[tuple[str, str]], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._log = log

    def _write_entry(self, entry: Any) -> None:
        self._log.append(("register_write", entry.entity_id))
        super()._write_entry(entry)


def _vault_root(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    (root / "settings").mkdir(exist_ok=True)
    (root / "settings" / "vault.md").write_text(
        "---\nschema: design-handoff.vault.v1\nvaultId: vault-test\n---\n",
        encoding="utf-8",
    )
    return root


def _vault_context(root: Path) -> VaultContext:
    return VaultContext(
        status="selected",
        active_vault_id="vault-test",
        active_vault_name="Vault Test",
        active_vault_path=str(root),
    )


def _allowing_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _register(vault_root: Path, *, conn: Any = None) -> EntityRegister:
    return EntityRegister(
        vault_context=_vault_context(vault_root),
        write_guard=_allowing_guard(),
        conn=conn if conn is not None else FakeOutboxConn(),
    )


def _mention(
    *,
    resolution: str,
    confidence: float | None,
    surface_form: str = "Anna",
    mention_id: str = "mention:test-1",
) -> EntityMention:
    return EntityMention(
        mention_id=mention_id,
        surface_form=surface_form,
        resolution=resolution,
        kind_hint="person",
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# AC: a confirmed merge writes `merged_from:` + a redirect and is reversible
# via `split()`.
# ---------------------------------------------------------------------------


def test_merge_writes_redirect_and_is_reversible(tmp_path: Path) -> None:
    vault_root = _vault_root(tmp_path)
    conn = FakeOutboxConn()
    register = _register(vault_root, conn=conn)

    anna = register.mint_canonical("Anna Svensson", kind=KIND_PERSON, aliases=["Anna"])
    anna_gym = register.mint_canonical("Anna från gymmet", kind=KIND_PERSON, aliases=["Anna G"])

    # Queue a mid-band mention, then confirm the merge via a one-line note
    # edit in entities/review.md's human-editable `decisions` field -- the
    # ruling mechanism this module provides, not a bespoke API.
    mention = _mention(resolution=RESOLUTION_AMBIGUOUS, confidence=0.75, mention_id="mention:merge-1")
    entry = queue_for_review(
        vault_root,
        mention,
        candidate_entity_ids=[anna_gym, anna],
    )

    note = SettingsNote(
        spec=ENTITY_REVIEW,
        values={
            "pending": [e.to_dict() for e in pending_review_entries(vault_root)],
            "decisions": [
                ReviewDecision(
                    queue_entry_id=entry.queue_entry_id,
                    action="merge",
                    from_id=anna_gym,
                    into_id=anna,
                ).to_dict()
            ],
        },
    )
    write_settings_note(vault_root, note, settings_dir=DEFAULT_SETTINGS_DIR, write_guard=_allowing_guard())

    journal = _InMemoryJournal()
    applied = apply_human_review_decisions(vault_root, register=register, journal=journal)
    assert len(applied) == 1
    assert applied[0].merged is True
    assert applied[0].action == "merge"
    assert applied[0].operation_id is not None

    # Redirect: the source note carries `merged_into` (append-only — HEIM-1).
    source_entry = register.get_entry(anna_gym)
    assert source_entry is not None
    assert source_entry.lifecycle == LIFECYCLE_MERGED
    assert source_entry.merged_into == anna
    assert register.resolve_redirects(anna_gym) == anna

    # `merged_from:` — the target-side complement of the redirect.
    target_entry = register.get_entry(anna)
    assert target_entry is not None
    assert anna_gym in target_entry.merged_from

    # The queue entry is cleared once the ruling is applied.
    assert pending_review_entries(vault_root) == ()

    # Idempotent: re-applying (no new decisions/pending) does nothing.
    again = apply_human_review_decisions(vault_root, register=register, journal=journal)
    assert again == ()

    # Reversible via split() (F5) — A1's own mechanism, not reimplemented.
    new_ids = register.split(anna, {"Anna från gymmet": ["Anna från gymmet", "Anna G"]})
    assert len(new_ids) == 1
    restored_anna_gym = new_ids[0]

    assert register.resolve_redirects(anna_gym) == restored_anna_gym
    assert register.resolve_redirects(anna_gym) != anna

    # merged_from on the original target no longer claims the reversed id.
    target_after_split = register.get_entry(anna)
    assert target_after_split is not None
    assert anna_gym not in target_after_split.merged_from

    # The restored entity carries the reclaimed merged_from record.
    restored_entry = register.get_entry(restored_anna_gym)
    assert restored_entry is not None
    assert restored_entry.lifecycle == LIFECYCLE_CANONICAL
    assert anna_gym in restored_entry.merged_from


def test_applicator_refuses_vault_root_register_mismatch(tmp_path: Path) -> None:
    register_root = _vault_root(tmp_path / "register")
    applicator_root = _vault_root(tmp_path / "applicator")
    register = _register(register_root)
    source = register.mint_canonical("Anna fran gymmet")
    target = register.mint_canonical("Anna Svensson")
    entry = queue_for_review(
        applicator_root,
        _mention(resolution=RESOLUTION_AMBIGUOUS, confidence=0.75),
        candidate_entity_ids=[source, target],
    )
    write_settings_note(
        applicator_root,
        SettingsNote(
            spec=ENTITY_REVIEW,
            values={
                "pending": [item.to_dict() for item in pending_review_entries(applicator_root)],
                "decisions": [
                    ReviewDecision(queue_entry_id=entry.queue_entry_id, action="reject").to_dict()
                ],
            },
        ),
        settings_dir=DEFAULT_SETTINGS_DIR,
        write_guard=_allowing_guard(),
    )

    with pytest.raises(EntityConfirmError, match="does not match"):
        apply_human_review_decisions(
            applicator_root, register=register, journal=_InMemoryJournal()
        )

def test_reject_decision_clears_queue_without_register_mutation(tmp_path: Path) -> None:
    vault_root = _vault_root(tmp_path)
    register = _register(vault_root)

    anna = register.mint_canonical("Anna Svensson", kind=KIND_PERSON, aliases=["Anna"])
    other = register.mint_canonical("Anna Karlsson", kind=KIND_PERSON, aliases=["Anna K"])

    mention = _mention(resolution=RESOLUTION_AMBIGUOUS, confidence=0.7, mention_id="mention:reject-1")
    entry = queue_for_review(vault_root, mention, candidate_entity_ids=[anna, other])

    note = SettingsNote(
        spec=ENTITY_REVIEW,
        values={
            "pending": [e.to_dict() for e in pending_review_entries(vault_root)],
            "decisions": [ReviewDecision(queue_entry_id=entry.queue_entry_id, action="reject").to_dict()],
        },
    )
    write_settings_note(vault_root, note, settings_dir=DEFAULT_SETTINGS_DIR, write_guard=_allowing_guard())

    applied = apply_human_review_decisions(vault_root, register=register)
    assert len(applied) == 1
    assert applied[0].action == "reject"
    assert applied[0].merged is False

    # No register mutation: neither entity was merged/redirected.
    assert register.get_entry(anna).lifecycle == LIFECYCLE_CANONICAL
    assert register.get_entry(other).lifecycle == LIFECYCLE_CANONICAL
    assert pending_review_entries(vault_root) == ()


def test_review_decision_rejects_invalid_action() -> None:
    with pytest.raises(EntityConfirmError):
        ReviewDecision(queue_entry_id="review:x", action="bogus")


def test_review_decision_undo_is_valid_compensating_entry() -> None:
    decision = ReviewDecision(queue_entry_id="review:x", action="undo")

    assert decision.to_dict()["queue_entry_id"] == "review:x"
    assert decision.to_dict()["action"] == "undo"
    assert "from_id" not in decision.to_dict()
    assert "into_id" not in decision.to_dict()

    with pytest.raises(EntityConfirmError, match="queue_entry_id only"):
        ReviewDecision(
            queue_entry_id="review:x",
            action="undo",
            from_id="ent:a",
            into_id="ent:b",
        )


def test_review_decision_merge_requires_ids() -> None:
    with pytest.raises(EntityConfirmError):
        ReviewDecision(queue_entry_id="review:x", action="merge")


@pytest.mark.parametrize("terminal_action", ["merge", "reject"])
def test_apply_human_review_decisions_folds_compensating_undo_without_deleting_history(
    tmp_path: Path,
    terminal_action: str,
) -> None:
    vault_root = _vault_root(tmp_path)
    register = _register(vault_root)
    source = register.mint_canonical("Source")
    target = register.mint_canonical("Target")
    mention = _mention(
        resolution=RESOLUTION_AMBIGUOUS,
        confidence=0.75,
        mention_id=f"mention:undo-{terminal_action}",
    )
    entry = queue_for_review(vault_root, mention, candidate_entity_ids=[source, target])
    terminal = ReviewDecision(
        queue_entry_id=entry.queue_entry_id,
        action=terminal_action,
        from_id=source if terminal_action == "merge" else None,
        into_id=target if terminal_action == "merge" else None,
    )
    undo = ReviewDecision(queue_entry_id=entry.queue_entry_id, action="undo")
    history = [terminal.to_dict(), undo.to_dict()]
    note = SettingsNote(
        spec=ENTITY_REVIEW,
        values={
            "pending": [entry.to_dict()],
            "decisions": history,
        },
    )
    write_settings_note(
        vault_root,
        note,
        settings_dir=DEFAULT_SETTINGS_DIR,
        write_guard=_allowing_guard(),
    )

    assert apply_human_review_decisions(vault_root, register=register) == ()
    assert pending_review_entries(vault_root) == (entry,)
    assert register.get_entry(source).lifecycle == LIFECYCLE_CANONICAL
    assert register.get_entry(target).lifecycle == LIFECYCLE_CANONICAL

    persisted = read_settings_note(
        vault_root,
        ENTITY_REVIEW,
        settings_dir=DEFAULT_SETTINGS_DIR,
    )
    assert persisted is not None
    assert persisted.values["decisions"] == history


@pytest.mark.parametrize("terminal_action", ["merge", "reject"])
def test_apply_human_review_decisions_applies_terminal_uncompensated_decision(
    tmp_path: Path,
    terminal_action: str,
) -> None:
    vault_root = _vault_root(tmp_path)
    register = _register(vault_root)
    source = register.mint_canonical("Source")
    target = register.mint_canonical("Target")
    mention = _mention(
        resolution=RESOLUTION_AMBIGUOUS,
        confidence=0.75,
        mention_id=f"mention:terminal-{terminal_action}",
    )
    entry = queue_for_review(vault_root, mention, candidate_entity_ids=[source, target])
    decision = ReviewDecision(
        queue_entry_id=entry.queue_entry_id,
        action=terminal_action,
        from_id=source if terminal_action == "merge" else None,
        into_id=target if terminal_action == "merge" else None,
    )
    raw_decision = decision.to_dict()
    raw_decision.pop("decided_at")
    raw_decision["audit_tag"] = "retain-forward-compatible-history"
    note = SettingsNote(
        spec=ENTITY_REVIEW,
        values={
            "pending": [entry.to_dict()],
            "decisions": [raw_decision],
        },
    )
    write_settings_note(
        vault_root,
        note,
        settings_dir=DEFAULT_SETTINGS_DIR,
        write_guard=_allowing_guard(),
    )

    applied = apply_human_review_decisions(
        vault_root, register=register, journal=_InMemoryJournal()
    )

    assert len(applied) == 1
    assert applied[0].action == terminal_action
    assert applied[0].merged is (terminal_action == "merge")
    assert pending_review_entries(vault_root) == ()
    assert register.get_entry(source).lifecycle == (
        LIFECYCLE_MERGED if terminal_action == "merge" else LIFECYCLE_CANONICAL
    )
    persisted = read_settings_note(
        vault_root,
        ENTITY_REVIEW,
        settings_dir=DEFAULT_SETTINGS_DIR,
    )
    assert persisted is not None
    assert persisted.values["decisions"] == [raw_decision]


def test_apply_human_review_decisions_accepts_new_intent_after_undo(tmp_path: Path) -> None:
    vault_root = _vault_root(tmp_path)
    register = _register(vault_root)
    source = register.mint_canonical("Source")
    target = register.mint_canonical("Target")
    mention = _mention(
        resolution=RESOLUTION_AMBIGUOUS,
        confidence=0.75,
        mention_id="mention:undo-redecide",
    )
    entry = queue_for_review(vault_root, mention, candidate_entity_ids=[source, target])
    decisions = [
        ReviewDecision(
            queue_entry_id=entry.queue_entry_id,
            action="merge",
            from_id=source,
            into_id=target,
        ).to_dict(),
        ReviewDecision(queue_entry_id=entry.queue_entry_id, action="undo").to_dict(),
        ReviewDecision(queue_entry_id=entry.queue_entry_id, action="reject").to_dict(),
    ]
    write_settings_note(
        vault_root,
        SettingsNote(
            spec=ENTITY_REVIEW,
            values={"pending": [entry.to_dict()], "decisions": decisions},
        ),
        settings_dir=DEFAULT_SETTINGS_DIR,
        write_guard=_allowing_guard(),
    )

    applied = apply_human_review_decisions(vault_root, register=register)

    assert len(applied) == 1
    assert applied[0].action == "reject"
    assert applied[0].merged is False
    assert register.get_entry(source).lifecycle == LIFECYCLE_CANONICAL
    assert pending_review_entries(vault_root) == ()


# ---------------------------------------------------------------------------
# AC: mid-band mentions route to the entities/review.md queue.
# ---------------------------------------------------------------------------


def test_midband_routes_to_queue(tmp_path: Path) -> None:
    vault_root = _vault_root(tmp_path)

    mid_mention = _mention(resolution=RESOLUTION_AMBIGUOUS, confidence=0.75, mention_id="mention:mid-1")
    decision = route_mention(mid_mention)
    assert decision == RoutingDecision.QUEUE_FOR_REVIEW

    entry = queue_for_review(vault_root, mid_mention, candidate_entity_ids=["ent:a", "ent:b"])
    assert entry.queue_entry_id == f"review:{mid_mention.mention_id}"

    pending = pending_review_entries(vault_root)
    assert len(pending) == 1
    assert pending[0].mention_id == mid_mention.mention_id
    assert pending[0].confidence == 0.75
    assert pending[0].candidate_entity_ids == ("ent:a", "ent:b")

    # The note is real markdown on disk at entities/review.md, not only an
    # in-memory return value.
    review_path = vault_root / DEFAULT_SETTINGS_DIR / "entities" / "review.md"
    assert review_path.exists()
    text = review_path.read_text(encoding="utf-8")
    assert "entity_review" in text
    assert mid_mention.mention_id in text


def test_midband_boundaries_are_inclusive_of_high_exclusive(tmp_path: Path) -> None:
    # Exactly at LOW_THRESHOLD: still mid-band (inclusive lower bound).
    at_low = _mention(resolution=RESOLUTION_RESOLVED, confidence=LOW_THRESHOLD, mention_id="mention:low-edge")
    assert route_mention(at_low) == RoutingDecision.QUEUE_FOR_REVIEW

    # Just below HIGH_THRESHOLD: still mid-band.
    just_under_high = _mention(
        resolution=RESOLUTION_RESOLVED, confidence=HIGH_THRESHOLD - 0.01, mention_id="mention:high-edge"
    )
    assert route_mention(just_under_high) == RoutingDecision.QUEUE_FOR_REVIEW


def test_queue_for_review_replaces_stale_entry_for_same_mention(tmp_path: Path) -> None:
    vault_root = _vault_root(tmp_path)
    mention = _mention(resolution=RESOLUTION_AMBIGUOUS, confidence=0.65, mention_id="mention:dup-1")

    queue_for_review(vault_root, mention, candidate_entity_ids=["ent:a"])
    queue_for_review(vault_root, mention, candidate_entity_ids=["ent:a", "ent:c"])

    pending = pending_review_entries(vault_root)
    assert len(pending) == 1
    assert pending[0].candidate_entity_ids == ("ent:a", "ent:c")


def test_queue_for_review_requires_confidence(tmp_path: Path) -> None:
    vault_root = _vault_root(tmp_path)
    mention = _mention(resolution=RESOLUTION_AMBIGUOUS, confidence=None, mention_id="mention:no-conf")
    with pytest.raises(EntityConfirmError):
        queue_for_review(vault_root, mention)


# ---------------------------------------------------------------------------
# AC: above the high threshold, a mention auto-links with no human step.
# ---------------------------------------------------------------------------


def test_high_band_auto_links(tmp_path: Path) -> None:
    vault_root = _vault_root(tmp_path)

    high_mention = _mention(resolution=RESOLUTION_RESOLVED, confidence=0.95, mention_id="mention:high-1")
    decision = route_mention(high_mention)
    assert decision == RoutingDecision.AUTO_LINK

    # No human step: nothing is written to the review queue for a high-band
    # mention (the caller simply does not call queue_for_review/confirm for
    # AUTO_LINK -- there is no code path here that queues it).
    assert pending_review_entries(vault_root) == ()
    review_path = vault_root / DEFAULT_SETTINGS_DIR / "entities" / "review.md"
    assert not review_path.exists()


def test_high_band_boundary_is_inclusive(tmp_path: Path) -> None:
    exactly_high = _mention(resolution=RESOLUTION_RESOLVED, confidence=HIGH_THRESHOLD, mention_id="mention:exact-high")
    assert route_mention(exactly_high) == RoutingDecision.AUTO_LINK


# ---------------------------------------------------------------------------
# Negative / completeness coverage.
# ---------------------------------------------------------------------------


def test_unresolved_mention_never_routes(tmp_path: Path) -> None:
    unresolved = _mention(resolution=RESOLUTION_UNRESOLVED, confidence=0.5, mention_id="mention:unresolved-1")
    assert route_mention(unresolved) == RoutingDecision.NO_ACTION


def test_low_band_mention_produces_no_action(tmp_path: Path) -> None:
    low = _mention(resolution=RESOLUTION_AMBIGUOUS, confidence=0.4, mention_id="mention:low-1")
    assert route_mention(low) == RoutingDecision.NO_ACTION


def test_mention_with_no_confidence_produces_no_action() -> None:
    no_confidence = _mention(resolution=RESOLUTION_AMBIGUOUS, confidence=None, mention_id="mention:no-conf-2")
    assert route_mention(no_confidence) == RoutingDecision.NO_ACTION


def test_apply_decisions_is_idempotent_and_skips_unknown_ids(tmp_path: Path) -> None:
    vault_root = _vault_root(tmp_path)
    register = _register(vault_root)

    a = register.mint_canonical("Alpha")
    b = register.mint_canonical("Beta")

    # A decision referencing a queue_entry_id that was never queued (stale /
    # already-applied) is skipped, not an error -- re-running is always safe.
    note = SettingsNote(
        spec=ENTITY_REVIEW,
        values={
            "pending": [],
            "decisions": [
                ReviewDecision(queue_entry_id="review:mention:ghost", action="merge", from_id=a, into_id=b).to_dict()
            ],
        },
    )
    write_settings_note(vault_root, note, settings_dir=DEFAULT_SETTINGS_DIR, write_guard=_allowing_guard())

    applied = apply_human_review_decisions(vault_root, register=register)
    assert applied == ()
    # Untouched: no merge happened for the ghost decision.
    assert register.get_entry(a).lifecycle == LIFECYCLE_CANONICAL
    assert register.get_entry(b).lifecycle == LIFECYCLE_CANONICAL


def test_apply_human_review_decisions_no_note_yet_is_a_noop(tmp_path: Path) -> None:
    vault_root = _vault_root(tmp_path)
    register = _register(vault_root)
    assert apply_human_review_decisions(vault_root, register=register) == ()


# ---------------------------------------------------------------------------
# EROJ-01 (#4350): the production applicator clears a merge only through the
# committed-visibility fence; reject and pre-application undo are unchanged.
# ---------------------------------------------------------------------------


def _queue_one_merge(
    vault_root: Path, register: EntityRegister
) -> tuple[str, str, str]:
    source = register.mint_canonical("Source")
    target = register.mint_canonical("Target")
    mention = _mention(
        resolution=RESOLUTION_AMBIGUOUS, confidence=0.75, mention_id="mention:fence-1"
    )
    entry = queue_for_review(vault_root, mention, candidate_entity_ids=[source, target])
    write_settings_note(
        vault_root,
        SettingsNote(
            spec=ENTITY_REVIEW,
            values={
                "pending": [entry.to_dict()],
                "decisions": [
                    ReviewDecision(
                        queue_entry_id=entry.queue_entry_id,
                        action="merge",
                        from_id=source,
                        into_id=target,
                    ).to_dict()
                ],
            },
        ),
        settings_dir=DEFAULT_SETTINGS_DIR,
        write_guard=_allowing_guard(),
    )
    return entry.queue_entry_id, source, target


def test_apply_merge_uses_committed_journal_before_pending_clear(tmp_path: Path) -> None:
    vault_root = _vault_root(tmp_path)
    log: list[tuple[str, str]] = []
    register = _LoggingRegister(
        vault_context=VaultContext(
            status="selected",
            active_vault_id="vault-test",
            active_vault_name="Vault Test",
            active_vault_path=str(vault_root),
        ),
        write_guard=_allowing_guard(),
        conn=FakeOutboxConn(),
        log=log,
    )
    queue_entry_id, source, target = _queue_one_merge(vault_root, register)

    # Without a journal, a merge decision cannot be applied at all: no
    # register mutation, no pending clear, loud failure.
    with pytest.raises(EntityConfirmError, match="committed-visibility fence"):
        apply_human_review_decisions(vault_root, register=register)
    assert register.get_entry(source).lifecycle == LIFECYCLE_CANONICAL
    assert [e.queue_entry_id for e in pending_review_entries(vault_root)] == [queue_entry_id]

    # With a journal whose fence cannot observe the committed evidence, the
    # queue entry MUST stay pending — same-writer belief is never durability.
    journal = _InMemoryJournal(visibility=False, log=log)
    log.clear()
    with pytest.raises(EntityConfirmError, match="committed visibility"):
        apply_human_review_decisions(vault_root, register=register, journal=journal)
    assert [e.queue_entry_id for e in pending_review_entries(vault_root)] == [queue_entry_id]
    methods = [name for name, _ in log]
    assert "mark_cleared" not in methods, "an unobserved commit must never authorize a clear"
    assert methods.index("claim_operation") < methods.index("register_write"), (
        "the operation must commit before the first register effect"
    )

    # Once the fence observes the committed evidence, the SAME in-flight
    # operation is finished through the entry-keyed resume path: fence before
    # mark_cleared, and no second event commit for an already-committed
    # operation.
    journal.visibility = True
    log.clear()
    applied = apply_human_review_decisions(vault_root, register=register, journal=journal)
    assert len(applied) == 1 and applied[0].merged is True
    assert pending_review_entries(vault_root) == ()
    methods = [name for name, _ in log]
    assert "commit_merge_event" not in methods, (
        "an already event-committed operation must resume, never re-commit"
    )
    assert methods.index("find_active_operation") < methods.index(
        "verify_committed_visibility"
    )
    assert methods.index("verify_committed_visibility") < methods.index("mark_cleared")

    # Reject keeps its current journal-free semantics on a fresh entry.
    other = _mention(
        resolution=RESOLUTION_AMBIGUOUS, confidence=0.7, mention_id="mention:fence-reject"
    )
    entry = queue_for_review(vault_root, other, candidate_entity_ids=[target])
    note = read_settings_note(vault_root, ENTITY_REVIEW, settings_dir=DEFAULT_SETTINGS_DIR)
    assert note is not None
    write_settings_note(
        vault_root,
        SettingsNote(
            spec=ENTITY_REVIEW,
            values={
                **note.values,
                "decisions": [
                    *list(note.values.get("decisions") or []),
                    ReviewDecision(queue_entry_id=entry.queue_entry_id, action="reject").to_dict(),
                ],
            },
        ),
        settings_dir=DEFAULT_SETTINGS_DIR,
        write_guard=_allowing_guard(),
    )
    applied = apply_human_review_decisions(vault_root, register=register)
    assert [a.action for a in applied] == ["reject"]
    assert pending_review_entries(vault_root) == ()


def test_client_approval_is_canonicalized_by_hub_before_merge_execution(
    tmp_path: Path,
) -> None:
    """INV-EROJ-1: an iPad client record is a proposal-bound review signal.

    The Hub fold validates that the signal is bound to a displayed pending
    proposal and canonicalizes the approval into a journaled operation BEFORE
    any register mutation; a client record alone (unbound, or compensated by
    a pre-application undo) is never replayed as a merge command."""
    vault_root = _vault_root(tmp_path)
    log: list[tuple[str, str]] = []
    register = _LoggingRegister(
        vault_context=VaultContext(
            status="selected",
            active_vault_id="vault-test",
            active_vault_name="Vault Test",
            active_vault_path=str(vault_root),
        ),
        write_guard=_allowing_guard(),
        conn=FakeOutboxConn(),
        log=log,
    )
    journal = _InMemoryJournal(log=log)
    source = register.mint_canonical("Source")
    target = register.mint_canonical("Target")

    # A client approval that is NOT bound to any displayed proposal (no such
    # pending entry) is skipped outright: no operation, no register mutation.
    write_settings_note(
        vault_root,
        SettingsNote(
            spec=ENTITY_REVIEW,
            values={
                "pending": [],
                "decisions": [
                    ReviewDecision(
                        queue_entry_id="review:mention:not-displayed",
                        action="merge",
                        from_id=source,
                        into_id=target,
                    ).to_dict()
                ],
            },
        ),
        settings_dir=DEFAULT_SETTINGS_DIR,
        write_guard=_allowing_guard(),
    )
    log.clear()
    assert apply_human_review_decisions(vault_root, register=register, journal=journal) == ()
    assert log == [], "an unbound client record must not reach the journal or the register"
    assert register.get_entry(source).lifecycle == LIFECYCLE_CANONICAL

    # An approval compensated by a pre-application undo folds to undecided:
    # still no operation and no register mutation, history retained.
    mention = _mention(
        resolution=RESOLUTION_AMBIGUOUS, confidence=0.75, mention_id="mention:approve-1"
    )
    entry = queue_for_review(vault_root, mention, candidate_entity_ids=[source, target])
    approval = ReviewDecision(
        queue_entry_id=entry.queue_entry_id, action="merge", from_id=source, into_id=target
    ).to_dict()
    undo = ReviewDecision(queue_entry_id=entry.queue_entry_id, action="undo").to_dict()
    write_settings_note(
        vault_root,
        SettingsNote(
            spec=ENTITY_REVIEW,
            values={"pending": [entry.to_dict()], "decisions": [approval, undo]},
        ),
        settings_dir=DEFAULT_SETTINGS_DIR,
        write_guard=_allowing_guard(),
    )
    log.clear()
    assert apply_human_review_decisions(vault_root, register=register, journal=journal) == ()
    assert log == []
    assert [e.queue_entry_id for e in pending_review_entries(vault_root)] == [
        entry.queue_entry_id
    ]

    # A new uncompensated approval bound to the displayed proposal IS
    # canonicalized: the Hub claims the operation BEFORE the first register
    # mutation and only the Hub executes the merge.
    note = read_settings_note(vault_root, ENTITY_REVIEW, settings_dir=DEFAULT_SETTINGS_DIR)
    assert note is not None
    re_approval = ReviewDecision(
        queue_entry_id=entry.queue_entry_id, action="merge", from_id=source, into_id=target
    ).to_dict()
    write_settings_note(
        vault_root,
        SettingsNote(
            spec=ENTITY_REVIEW,
            values={
                **note.values,
                "decisions": [*list(note.values.get("decisions") or []), re_approval],
            },
        ),
        settings_dir=DEFAULT_SETTINGS_DIR,
        write_guard=_allowing_guard(),
    )
    log.clear()
    applied = apply_human_review_decisions(vault_root, register=register, journal=journal)
    assert len(applied) == 1 and applied[0].merged is True
    methods = [name for name, _ in log]
    assert "claim_operation" in methods and "register_write" in methods
    assert methods.index("claim_operation") < methods.index("register_write"), (
        "the Hub must canonicalize the approval into the operation before any "
        "register mutation"
    )
    assert register.get_entry(source).merged_into == target
    assert pending_review_entries(vault_root) == ()


def test_invalid_merge_decision_never_strands_an_operation(tmp_path: Path) -> None:
    """Review F6 (#4350): pre-claim validation ordering. A decision that
    cannot be executed from current notes (typo'd entity id) is refused
    BEFORE any operation is bound, so no active journal row is stranded and
    a corrected decision can proceed normally afterwards."""
    vault_root = _vault_root(tmp_path)
    register = _register(vault_root)
    journal = _InMemoryJournal()
    source = register.mint_canonical("Source")
    target = register.mint_canonical("Target")
    mention = _mention(
        resolution=RESOLUTION_AMBIGUOUS, confidence=0.75, mention_id="mention:typo-1"
    )
    entry = queue_for_review(vault_root, mention, candidate_entity_ids=[source, target])
    typo = ReviewDecision(
        queue_entry_id=entry.queue_entry_id,
        action="merge",
        from_id=source,
        into_id="ent:no-such-entity",
    ).to_dict()
    write_settings_note(
        vault_root,
        SettingsNote(
            spec=ENTITY_REVIEW,
            values={"pending": [entry.to_dict()], "decisions": [typo]},
        ),
        settings_dir=DEFAULT_SETTINGS_DIR,
        write_guard=_allowing_guard(),
    )

    with pytest.raises(EntityConfirmError, match="unknown into_id"):
        apply_human_review_decisions(vault_root, register=register, journal=journal)
    assert journal.operations == {}, (
        "a refused pre-claim validation must not bind an operation row"
    )
    assert [e.queue_entry_id for e in pending_review_entries(vault_root)] == [
        entry.queue_entry_id
    ]

    # The corrected decision proceeds without any identity conflict.
    note = read_settings_note(vault_root, ENTITY_REVIEW, settings_dir=DEFAULT_SETTINGS_DIR)
    assert note is not None
    corrected = ReviewDecision(
        queue_entry_id=entry.queue_entry_id, action="merge", from_id=source, into_id=target
    ).to_dict()
    write_settings_note(
        vault_root,
        SettingsNote(
            spec=ENTITY_REVIEW,
            values={
                **note.values,
                "decisions": [*list(note.values.get("decisions") or []), corrected],
            },
        ),
        settings_dir=DEFAULT_SETTINGS_DIR,
        write_guard=_allowing_guard(),
    )
    applied = apply_human_review_decisions(vault_root, register=register, journal=journal)
    assert len(applied) == 1 and applied[0].merged is True
    assert pending_review_entries(vault_root) == ()
