"""Review-queue reconciliation replacement tests (#2014, AC#4).

When a candidate is already a stale PENDING entry in the queue and a terminal
decision now exists for it (e.g. discovered on re-intake), reconciliation must
replace the stale pending entry with the terminal projection rather than leaving
it in ``pending()`` or raising "candidate already in queue".

Source authority:
- app/agent_memory/review_queue.py (PR #1913 thread PRRT_kwDOQEip6s6JTzhU)
"""

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


def _vault(path: Path) -> VaultContext:
    return VaultContext(
        status="selected",
        active_vault_id="vault-a",
        active_vault_name="vault-a",
        active_vault_path=str(path),
    )


def _candidate(candidate_id: str) -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id=candidate_id,
        title=f"Candidate {candidate_id}",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        inferred=True,
        content="User prefers concise answers.",
        source_refs=["session:2026-06-14T09:00:00Z"],
        derived_from="conversation:abc123",
        generated_by="companion_agent",
    )


def test_reconcile_replaces_stale_pending(tmp_path: Path) -> None:
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    vault = _vault(tmp_path / "vault-a")
    candidate = _candidate("candidate-stale")

    queue = MemoryCandidateReviewQueue(
        decision_store=store,
        vault_context=vault,
        channel="test",
    )

    # Candidate first enters the queue as a stale pending entry (no decision yet).
    pending_entry = queue.enqueue(candidate)
    assert pending_entry.status is ReviewStatus.PENDING
    assert [item.candidate_id for item in queue.pending()] == ["candidate-stale"]

    # A terminal decision is recorded out of band (e.g. a reject persisted by
    # another surface or a prior session).
    decided = pending_entry.model_copy(
        update={
            "status": ReviewStatus.REJECTED,
            "decision": ReviewDecision.REJECT,
            "decided_by": "companion-ui:reviewer",
            "decided_at": pending_entry.decided_at,
        }
    )
    # Re-decide through a fresh queue to obtain a properly decided entry, then
    # persist it as a terminal decision.
    decide_queue = MemoryCandidateReviewQueue()
    decide_queue.enqueue(candidate)
    decided = decide_queue.decide(
        candidate.candidate_id,
        ReviewDecision.REJECT,
        decided_by="companion-ui:reviewer",
    )
    store.record_decision(decided, vault_context=vault, channel="test")

    # Re-intake of the same candidate must reconcile: the stale pending entry is
    # replaced with the terminal decision, not raised on or left pending.
    reconciled = queue.enqueue(candidate)

    assert reconciled.status is ReviewStatus.REJECTED
    assert reconciled.decision is ReviewDecision.REJECT
    # The stale pending entry is gone.
    assert queue.pending() == []
    # The terminal entry is now the queue's record for this candidate.
    assert queue.get(candidate.candidate_id).status is ReviewStatus.REJECTED
