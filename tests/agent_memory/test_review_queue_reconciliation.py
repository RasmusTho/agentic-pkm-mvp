from __future__ import annotations

from pathlib import Path

from app.agent_memory.candidate import MemoryCandidate, MemoryType
from app.agent_memory.review_decision_store import ReviewDecisionStore
from app.agent_memory.review_queue import (
    MemoryCandidateReviewQueue,
    ReviewDecision,
    ReviewStatus,
)
from app.vault.manager import VaultContext


def _vault(vault_id: str, path: Path) -> VaultContext:
    return VaultContext(
        status="selected",
        active_vault_id=vault_id,
        active_vault_name=vault_id,
        active_vault_path=str(path),
    )


def _candidate(candidate_id: str, *, title: str | None = None) -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id=candidate_id,
        title=title or f"Candidate {candidate_id}",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        inferred=True,
        content="User prefers concise answers.",
        source_refs=["session:2026-06-13T09:00:00Z"],
        derived_from="conversation:abc123",
        generated_by="companion_agent",
    )


def _decide(
    store: ReviewDecisionStore,
    candidate: MemoryCandidate,
    *,
    vault: VaultContext,
    channel: str,
    decision: ReviewDecision,
) -> None:
    queue = MemoryCandidateReviewQueue()
    queue.enqueue(candidate)
    decided = queue.decide(
        candidate.candidate_id,
        decision,
        decided_by="companion-ui:reviewer",
    )
    store.record_decision(decided, vault_context=vault, channel=channel)


def _reconciled_queue(
    *,
    store: ReviewDecisionStore,
    vault: VaultContext,
    channel: str = "test",
) -> MemoryCandidateReviewQueue:
    return MemoryCandidateReviewQueue(
        decision_store=store,
        vault_context=vault,
        channel=channel,
    )


def test_decided_candidates_not_resurfaced(tmp_path: Path) -> None:
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    vault = _vault("vault-a", tmp_path / "vault-a")
    candidate = _candidate("candidate-terminal")
    _decide(
        store,
        candidate,
        vault=vault,
        channel="test",
        decision=ReviewDecision.REJECT,
    )

    restarted_queue = _reconciled_queue(store=store, vault=vault)
    entry = restarted_queue.enqueue(candidate)

    assert entry.status is ReviewStatus.REJECTED
    assert restarted_queue.pending() == []
    assert restarted_queue.decided() == []


def test_promoted_but_unmaterialized_candidate_stays_actionable(tmp_path: Path) -> None:
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    vault = _vault("vault-a", tmp_path / "vault-a")
    candidate = _candidate("candidate-promoted")
    _decide(
        store,
        candidate,
        vault=vault,
        channel="test",
        decision=ReviewDecision.PROMOTE,
    )

    restarted_queue = _reconciled_queue(store=store, vault=vault)
    entry = restarted_queue.enqueue(candidate)

    assert entry.status is ReviewStatus.PENDING
    assert [item.candidate_id for item in restarted_queue.pending()] == [
        "candidate-promoted"
    ]


def test_undecided_candidates_still_pending(tmp_path: Path) -> None:
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    vault = _vault("vault-a", tmp_path / "vault-a")
    candidate = _candidate("candidate-new")

    restarted_queue = _reconciled_queue(store=store, vault=vault)
    entry = restarted_queue.enqueue(candidate)

    assert entry.status is ReviewStatus.PENDING
    assert [item.candidate_id for item in restarted_queue.pending()] == ["candidate-new"]


def test_reconciliation_is_vault_scoped(tmp_path: Path) -> None:
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    vault_a = _vault("vault-a", tmp_path / "vault-a")
    vault_b = _vault("vault-b", tmp_path / "vault-b")
    candidate = _candidate("candidate-scoped")
    _decide(
        store,
        candidate,
        vault=vault_a,
        channel="test",
        decision=ReviewDecision.REJECT,
    )

    other_vault_queue = _reconciled_queue(store=store, vault=vault_b)
    other_channel_queue = _reconciled_queue(store=store, vault=vault_a, channel="other")

    assert other_vault_queue.enqueue(candidate).status is ReviewStatus.PENDING
    assert other_channel_queue.enqueue(candidate).status is ReviewStatus.PENDING
