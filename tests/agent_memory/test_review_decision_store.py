from __future__ import annotations

from pathlib import Path

import pytest

from app.agent_memory.candidate import MemoryCandidate, MemoryType
from app.agent_memory.review_decision_store import (
    REVIEW_DECISION_RECEIPT_KIND,
    ReviewDecisionStore,
    ReviewDecisionStoreError,
    _default_db_path,
)
from app.agent_memory.review_queue import MemoryCandidateReviewQueue, ReviewDecision
from app.vault.manager import VaultContext


def _vault(vault_id: str, path: Path) -> VaultContext:
    return VaultContext(
        status="selected",
        active_vault_id=vault_id,
        active_vault_name=vault_id,
        active_vault_path=str(path),
    )


def _candidate(*, title: str = "Observed user preference") -> MemoryCandidate:
    return MemoryCandidate(
        title=title,
        memory_type=MemoryType.PREFERENCE_MEMORY,
        inferred=True,
        content="User prefers concise answers.",
        source_refs=["session:2026-06-13T09:00:00Z", "note:preferences.md"],
        derived_from="conversation:abc123",
        generated_by="companion_agent",
    )


def test_decisions_survive_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "review_decisions.sqlite3"
    vault = _vault("vault-a", tmp_path / "vault-a")
    queue = MemoryCandidateReviewQueue()
    candidate = _candidate()
    queue.enqueue(candidate)
    decided = queue.decide(
        candidate.candidate_id,
        ReviewDecision.REJECT,
        decided_by="companion-ui:reviewer",
        notes="Not reliable enough.",
    )

    ReviewDecisionStore(db_path).record_decision(
        decided,
        vault_context=vault,
        channel="test",
    )

    restarted = ReviewDecisionStore(db_path)
    record = restarted.get_decision(
        candidate.candidate_id,
        vault_context=vault,
        channel="test",
    )

    assert record is not None
    assert record.candidate_id == candidate.candidate_id
    assert record.outcome is ReviewDecision.REJECT
    assert record.terminal is True


def test_decision_store_is_vault_scoped(tmp_path: Path) -> None:
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    queue = MemoryCandidateReviewQueue()
    candidate = _candidate()
    queue.enqueue(candidate)
    decided = queue.decide(
        candidate.candidate_id,
        ReviewDecision.PROMOTE,
        decided_by="companion-ui:reviewer",
    )
    vault_a = _vault("vault-a", tmp_path / "vault-a")
    vault_b = _vault("vault-b", tmp_path / "vault-b")

    store.record_decision(decided, vault_context=vault_a, channel="test")

    assert store.get_decision(candidate.candidate_id, vault_context=vault_a, channel="test")
    assert store.get_decision(candidate.candidate_id, vault_context=vault_b, channel="test") is None
    assert store.get_decision(candidate.candidate_id, vault_context=vault_a, channel="other") is None


def test_pending_candidates_are_not_persisted(tmp_path: Path) -> None:
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    vault = _vault("vault-a", tmp_path / "vault-a")
    queue = MemoryCandidateReviewQueue()
    pending = queue.enqueue(_candidate())

    with pytest.raises(ReviewDecisionStoreError):
        store.record_decision(pending, vault_context=vault, channel="test")

    assert store.list_decisions(vault_context=vault, channel="test") == ()


def test_default_db_under_ignored_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default review-decision DB must resolve under the gitignored
    ``runtime/agent_memory/`` runtime path (#2014, AC#5) so local decision DBs
    are never committed."""

    monkeypatch.delenv("AGENT_MEMORY_REVIEW_DECISION_DB", raising=False)
    monkeypatch.delenv("RUNTIME_TRACE_DIR", raising=False)

    default_path = _default_db_path()

    assert default_path.parent == Path("runtime/agent_memory")
    assert default_path == Path("runtime/agent_memory/review_decisions.sqlite3")


def test_decision_record_preserves_provenance(tmp_path: Path) -> None:
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    vault = _vault("vault-a", tmp_path / "vault-a")
    queue = MemoryCandidateReviewQueue()
    candidate = _candidate()
    queue.enqueue(candidate)
    decided = queue.decide(
        candidate.candidate_id,
        ReviewDecision.PROMOTE,
        decided_by="companion-ui:reviewer",
        notes="Looks consistent.",
    )

    record = store.record_decision(decided, vault_context=vault, channel="test")

    assert record.receipt_kind == REVIEW_DECISION_RECEIPT_KIND
    assert record.source_refs == tuple(candidate.source_refs)
    assert record.decided_by == "companion-ui:reviewer"
    assert record.decided_at == decided.decided_at
    assert record.decision_notes == "Looks consistent."
    assert record.generated_by == "companion_agent"
    assert record.derived_from == "conversation:abc123"
    assert record.terminal is False
