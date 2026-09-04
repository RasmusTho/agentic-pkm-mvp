from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.agent_memory.materialization as materialization_module
from app.agent_memory.candidate import MemoryCandidate, MemoryType
from app.agent_memory.materialization import (
    MemoryMaterializationError,
    materialize_promoted_memory,
)
from app.agent_memory.review_decision_store import (
    ReviewDecisionStore,
    ReviewDecisionStoreError,
)
from app.agent_memory.review_queue import MemoryCandidateReviewQueue, ReviewDecision
from app.receipts.promotion_receipts import query_promotion_receipts
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard, WritesBlockedError


def _vault(root: Path) -> VaultContext:
    return VaultContext(
        status="selected",
        active_vault_id="vault-a",
        active_vault_name="Vault A",
        active_vault_path=str(root),
    )


def _candidate(
    *,
    candidate_id: str = "candidate-semantic",
    memory_type: MemoryType = MemoryType.SEMANTIC_MEMORY,
    title: str = "Explicit semantic memory",
) -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id=candidate_id,
        title=title,
        memory_type=memory_type,
        inferred=False,
        content="The user explicitly prefers design docs before code.",
        source_refs=["note:source.md", "session:2026-06-13T09:00:00Z"],
        derived_from="vault:source.md",
        generated_by="companion_agent",
        scope_id="scope:test/materialization",
    )


def _promoted(
    candidate: MemoryCandidate,
    *,
    store: ReviewDecisionStore,
    vault: VaultContext,
    channel: str = "test",
):
    queue = MemoryCandidateReviewQueue()
    queue.enqueue(candidate)
    entry = queue.decide(
        candidate.candidate_id,
        ReviewDecision.PROMOTE,
        decided_by="companion-ui:reviewer",
        notes="Confirmed.",
    )
    store.record_decision(entry, vault_context=vault, channel=channel)
    return entry


def _allowing_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _blocked_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "safe_mode", "reason": "operator hold"})


def test_promotion_materializes_via_writeguard_with_receipt(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    Path(vault.active_vault_path).mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(_candidate(), store=store, vault=vault)

    result = materialize_promoted_memory(
        entry,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    )

    assert result.status == "materialized"
    assert result.artifact_path is not None
    note_path = Path(vault.active_vault_path) / result.artifact_path
    assert note_path.exists()

    receipts = query_promotion_receipts(vault_root=Path(vault.active_vault_path), outbox_path=outbox)
    assert [row.receipt_id for row in receipts.rows] == [result.receipt_id]
    assert receipts.rows[0].artifact_path == result.artifact_path
    assert receipts.rows[0].outcome_status == "applied"
    assert store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    ).terminal is True


def test_blocked_writes_prevent_materialization(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    Path(vault.active_vault_path).mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    entry = _promoted(_candidate(), store=store, vault=vault)

    with pytest.raises(MemoryMaterializationError) as excinfo:
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_blocked_guard(),
            outbox_path=tmp_path / "outbox.jsonl",
        )

    assert isinstance(excinfo.value.__cause__, WritesBlockedError)
    assert not list(Path(vault.active_vault_path).rglob("*.md"))


def test_semantic_materialization_requires_scope_before_write(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    Path(vault.active_vault_path).mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    candidate = _candidate().model_copy(update={"scope_id": None})
    entry = _promoted(candidate, store=store, vault=vault)

    with pytest.raises(MemoryMaterializationError, match="candidate.scope_id"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert not list(Path(vault.active_vault_path).rglob("*.md"))
    assert not outbox.exists()
    record = store.get_decision(
        candidate.candidate_id, vault_context=vault, channel="test"
    )
    assert record is not None
    assert record.terminal is False


def test_materialization_requires_entry_scope_to_match_persisted_decision(
    tmp_path: Path,
) -> None:
    vault = _vault(tmp_path / "vault")
    Path(vault.active_vault_path).mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    candidate = _candidate(candidate_id="candidate-scope-cas")
    _promoted(candidate, store=store, vault=vault)

    stale_candidate = candidate.model_copy(update={"scope_id": "scope:test/other"})
    queue = MemoryCandidateReviewQueue()
    queue.enqueue(stale_candidate)
    stale_entry = queue.decide(
        stale_candidate.candidate_id,
        ReviewDecision.PROMOTE,
        decided_by="companion-ui:reviewer",
        notes="Stale in-memory review entry.",
    )

    with pytest.raises(MemoryMaterializationError, match="persisted review decision"):
        materialize_promoted_memory(
            stale_entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert not list(Path(vault.active_vault_path).rglob("*.md"))
    assert not outbox.exists()
    record = store.get_decision(
        candidate.candidate_id, vault_context=vault, channel="test"
    )
    assert record is not None
    assert record.scope_id == "scope:test/materialization"
    assert record.terminal is False


def test_materialization_refuses_intervening_same_scope_rejection(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    Path(vault.active_vault_path).mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    candidate = _candidate(candidate_id="candidate-revoked")
    stale_promote = _promoted(candidate, store=store, vault=vault)

    replacement_queue = MemoryCandidateReviewQueue()
    replacement_queue.enqueue(candidate)
    rejection = replacement_queue.decide(
        candidate.candidate_id,
        ReviewDecision.REJECT,
        decided_by="companion-ui:reviewer",
        notes="Promotion authority revoked before materialization.",
    )
    store.record_decision(rejection, vault_context=vault, channel="test")

    with pytest.raises(MemoryMaterializationError, match="persisted promote decision"):
        materialize_promoted_memory(
            stale_promote,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert not list(Path(vault.active_vault_path).rglob("*.md"))
    assert not outbox.exists()
    record = store.get_decision(
        candidate.candidate_id, vault_context=vault, channel="test"
    )
    assert record is not None
    assert record.outcome is ReviewDecision.REJECT
    assert record.terminal is True


def test_duplicate_materializer_refuses_after_terminal_success(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    Path(vault.active_vault_path).mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-single-writer"),
        store=store,
        vault=vault,
    )

    first = materialize_promoted_memory(
        entry,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    )
    with pytest.raises(MemoryMaterializationError, match="already terminal"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert first.artifact_path is not None
    assert len(list(Path(vault.active_vault_path).rglob("*.md"))) == 1
    receipts = query_promotion_receipts(
        vault_root=Path(vault.active_vault_path),
        outbox_path=outbox,
    )
    assert [row.outcome_status for row in receipts.rows] == ["applied"]


def test_retry_reconciles_applied_receipt_after_late_query_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-late-query"),
        store=store,
        vault=vault,
    )
    original_query = materialization_module.query_promotion_receipts
    query_calls = 0

    def fail_post_append_query(*args, **kwargs):
        nonlocal query_calls
        query_calls += 1
        if query_calls == 2:
            raise RuntimeError("injected post-append query failure")
        return original_query(*args, **kwargs)

    monkeypatch.setattr(
        materialization_module,
        "query_promotion_receipts",
        fail_post_append_query,
    )
    with pytest.raises(MemoryMaterializationError, match="interrupted"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    assert len(list(vault_root.rglob("*.md"))) == 1
    assert len(outbox.read_text(encoding="utf-8").splitlines()) == 1
    interrupted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert interrupted.terminal is False
    assert interrupted.materializing is True

    changed_candidate = entry.candidate.model_copy(
        update={"content": "Changed candidate content after restart."}
    )
    changed_queue = MemoryCandidateReviewQueue()
    changed_queue.enqueue(changed_candidate)
    changed_retry = changed_queue.decide(
        changed_candidate.candidate_id,
        ReviewDecision.PROMOTE,
        decided_by="companion-ui:restart-reviewer",
    )
    with pytest.raises(ReviewDecisionStoreError, match="content cannot change"):
        store.record_decision(
            changed_retry,
            vault_context=vault,
            channel="test",
        )

    monkeypatch.setattr(
        materialization_module,
        "query_promotion_receipts",
        original_query,
    )
    retry_queue = MemoryCandidateReviewQueue()
    retry_queue.enqueue(entry.candidate)
    retry_entry = retry_queue.decide(
        entry.candidate_id,
        ReviewDecision.PROMOTE,
        decided_by="companion-ui:restart-reviewer",
        notes="Retry after restart.",
    )
    persisted_retry = store.record_decision(
        retry_entry,
        vault_context=vault,
        channel="test",
    )
    assert persisted_retry.decided_by == "companion-ui:reviewer"
    result = materialize_promoted_memory(
        retry_entry,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    )

    assert result.status == "materialized"
    assert len(list(vault_root.rglob("*.md"))) == 1
    assert len(outbox.read_text(encoding="utf-8").splitlines()) == 1
    completed = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert completed.terminal is True
    assert completed.materializing is False


def test_retry_reuses_candidate_note_after_receipt_append_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(
        _candidate(candidate_id="candidate-late-append"),
        store=store,
        vault=vault,
    )
    original_append = materialization_module._append_promotion_receipt

    def fail_receipt_append(*args, **kwargs):
        raise RuntimeError("injected receipt append failure")

    monkeypatch.setattr(
        materialization_module,
        "_append_promotion_receipt",
        fail_receipt_append,
    )
    with pytest.raises(MemoryMaterializationError, match="interrupted"):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    first_note = next(vault_root.rglob("*.md"))
    first_body = first_note.read_text(encoding="utf-8")
    assert not outbox.exists()
    interrupted = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert interrupted.terminal is False
    assert interrupted.materializing is True

    rejection_queue = MemoryCandidateReviewQueue()
    rejection_queue.enqueue(entry.candidate)
    rejection = rejection_queue.decide(
        entry.candidate_id,
        ReviewDecision.REJECT,
        decided_by="companion-ui:restart-reviewer",
    )
    with pytest.raises(ReviewDecisionStoreError, match="in progress"):
        store.record_decision(rejection, vault_context=vault, channel="test")

    monkeypatch.setattr(
        materialization_module,
        "_append_promotion_receipt",
        original_append,
    )
    retry_queue = MemoryCandidateReviewQueue()
    retry_queue.enqueue(entry.candidate)
    retry_entry = retry_queue.decide(
        entry.candidate_id,
        ReviewDecision.PROMOTE,
        decided_by="companion-ui:restart-reviewer",
        notes="Retry after restart.",
    )
    store.record_decision(retry_entry, vault_context=vault, channel="test")
    result = materialize_promoted_memory(
        retry_entry,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    )

    assert result.artifact_path == first_note.relative_to(vault_root).as_posix()
    assert first_note.read_text(encoding="utf-8") == first_body
    assert len(list(vault_root.rglob("*.md"))) == 1
    assert len(outbox.read_text(encoding="utf-8").splitlines()) == 1
    completed = store.get_decision(
        entry.candidate_id, vault_context=vault, channel="test"
    )
    assert completed.terminal is True
    assert completed.materializing is False


def test_blocked_materialization_keeps_promotion_actionable(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    Path(vault.active_vault_path).mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    candidate = _candidate(candidate_id="candidate-retry")
    entry = _promoted(candidate, store=store, vault=vault)

    with pytest.raises(MemoryMaterializationError):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_blocked_guard(),
            outbox_path=outbox,
        )

    raw_receipts = [json.loads(line) for line in outbox.read_text(encoding="utf-8").splitlines()]
    assert raw_receipts[0]["payload"]["outcome"]["status"] == "failed"
    assert store.get_decision(
        candidate.candidate_id, vault_context=vault, channel="test"
    ).terminal is False

    rebuilt = MemoryCandidateReviewQueue(
        decision_store=store,
        vault_context=vault,
        channel="test",
    )
    assert rebuilt.enqueue(candidate).candidate_id == candidate.candidate_id
    assert [item.candidate_id for item in rebuilt.pending()] == [candidate.candidate_id]


def test_materialization_create_race_does_not_append_applied_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    entry = _promoted(_candidate(candidate_id="candidate-raced"), store=store, vault=vault)
    real_write = materialization_module.write_note_relative

    def interleaved_write(note_rel_path: str, content: str, **kwargs: object):
        target = Path(str(kwargs["vault_root"])) / note_rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("foreign raced materialization\n", encoding="utf-8")
        return real_write(note_rel_path, content, **kwargs)

    monkeypatch.setattr(materialization_module, "write_note_relative", interleaved_write)

    with pytest.raises(MemoryMaterializationError):
        materialize_promoted_memory(
            entry,
            vault_context=vault,
            channel="test",
            decision_store=store,
            write_guard=_allowing_guard(),
            outbox_path=outbox,
        )

    receipts = query_promotion_receipts(vault_root=vault_root, outbox_path=outbox)
    assert [row.outcome_status for row in receipts.rows] == ["failed"]


def test_materialized_note_preserves_provenance_and_human_authorship(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    vault_root = Path(vault.active_vault_path)
    vault_root.mkdir()
    existing = vault_root / "Agent Memory" / "explicit-semantic-memory-candidat.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("Human-authored note stays put.\n", encoding="utf-8")
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    candidate = _candidate(candidate_id="candidate-")
    entry = _promoted(candidate, store=store, vault=vault)

    result = materialize_promoted_memory(
        entry,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=tmp_path / "outbox.jsonl",
    )

    assert existing.read_text(encoding="utf-8") == "Human-authored note stays put.\n"
    assert result.artifact_path == "Agent Memory/explicit-semantic-memory-candidat-2.md"
    body = (vault_root / result.artifact_path).read_text(encoding="utf-8")
    assert "agent-promoted-memory" in body
    assert "promoted_from_candidate_id: candidate-" in body
    assert "scope_id: scope:test/materialization" in body
    assert "companion-ui:reviewer" in body
    assert "note:source.md" in body
    assert "The user explicitly prefers design docs before code." in body


def test_non_semantic_promotion_does_not_materialize(tmp_path: Path) -> None:
    vault = _vault(tmp_path / "vault")
    Path(vault.active_vault_path).mkdir()
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    candidate = _candidate(
        candidate_id="candidate-preference",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        title="Preference memory",
    )
    entry = _promoted(candidate, store=store, vault=vault)

    result = materialize_promoted_memory(
        entry,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=tmp_path / "outbox.jsonl",
    )

    assert result.status == "not_semantic"
    assert result.artifact_path is None
    assert not list(Path(vault.active_vault_path).rglob("*.md"))
    assert store.get_decision(
        candidate.candidate_id, vault_context=vault, channel="test"
    ).terminal is True
