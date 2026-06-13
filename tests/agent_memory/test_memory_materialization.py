from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent_memory.candidate import MemoryCandidate, MemoryType
from app.agent_memory.materialization import (
    MemoryMaterializationError,
    materialize_promoted_memory,
)
from app.agent_memory.review_decision_store import ReviewDecisionStore
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
