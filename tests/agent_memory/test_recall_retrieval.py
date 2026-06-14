from __future__ import annotations

from pathlib import Path

import pytest

from app.agent_memory.candidate import MemoryCandidate, MemoryType
from app.agent_memory.materialization import materialize_promoted_memory
from app.agent_memory.promotion import PromotedMemory
from app.agent_memory.recall_retrieval import (
    read_promoted_memories,
    retrieve_relevant_promoted,
)
from app.agent_memory.review_decision_store import ReviewDecisionStore
from app.agent_memory.review_queue import MemoryCandidateReviewQueue, ReviewDecision
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard


def _vault(root: Path) -> VaultContext:
    return VaultContext(
        status="selected",
        active_vault_id="vault-a",
        active_vault_name="Vault A",
        active_vault_path=str(root),
    )


def _allowing_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _candidate(
    candidate_id: str,
    *,
    title: str,
    content: str,
    source_refs: list[str] | None = None,
    inferred: bool = False,
) -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id=candidate_id,
        title=title,
        memory_type=MemoryType.SEMANTIC_MEMORY,
        inferred=inferred,
        content=content,
        source_refs=source_refs or [f"note:{candidate_id}.md", "session:2026-06-13T09:00:00Z"],
        derived_from=f"vault:{candidate_id}.md",
        generated_by="companion_agent",
    )


def _materialize(
    candidate: MemoryCandidate,
    *,
    vault: VaultContext,
    store: ReviewDecisionStore,
    outbox: Path | None = None,
) -> str:
    queue = MemoryCandidateReviewQueue()
    queue.enqueue(candidate)
    entry = queue.decide(
        candidate.candidate_id,
        ReviewDecision.PROMOTE,
        decided_by="companion-ui:reviewer",
        notes="Confirmed.",
    )
    store.record_decision(entry, vault_context=vault, channel="test")
    result = materialize_promoted_memory(
        entry,
        vault_context=vault,
        channel="test",
        decision_store=store,
        write_guard=_allowing_guard(),
        outbox_path=outbox,
    )
    assert result.artifact_path is not None
    return result.artifact_path


def test_reads_promoted_memory_from_durable_set(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault = _vault(vault_root)
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    candidate = _candidate(
        "candidate-design-docs",
        title="Design docs before code",
        content="The user prefers reading owner docs before implementation.",
    )
    artifact_path = _materialize(candidate, vault=vault, store=store, outbox=outbox)

    memories = read_promoted_memories(vault_root=vault_root, outbox_path=outbox)

    assert len(memories) == 1
    promoted = memories[0]
    assert isinstance(promoted, PromotedMemory)
    assert promoted.candidate.candidate_id == candidate.candidate_id
    assert promoted.candidate.title == "Design docs before code"
    assert promoted.candidate.content == candidate.content
    assert promoted.candidate.source_refs == candidate.source_refs
    assert promoted.candidate.inferred is False
    assert promoted.decided_by == "companion-ui:reviewer"
    assert (vault_root / artifact_path).exists()


def test_reads_materialization_default_receipts_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault = _vault(vault_root)
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    candidate = _candidate(
        "candidate-default-receipts",
        title="Default receipts are visible",
        content="Recall reads the default materialization receipts path.",
    )
    _materialize(candidate, vault=vault, store=store)

    memories = read_promoted_memories(vault_root=vault_root)

    assert [memory.candidate.candidate_id for memory in memories] == [
        "candidate-default-receipts"
    ]


def test_preserves_inferred_posture_from_materialized_note(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault = _vault(vault_root)
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    candidate = _candidate(
        "candidate-inferred",
        title="Inferred multi-source memory",
        content="The agent inferred this from multiple source notes.",
        inferred=True,
        source_refs=["note:first.md", "note:second.md"],
    )
    _materialize(candidate, vault=vault, store=store, outbox=outbox)

    memories = read_promoted_memories(vault_root=vault_root, outbox_path=outbox)

    assert memories[0].candidate.inferred is True


def test_missing_inferred_metadata_defaults_conservatively(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    memory_dir = vault_root / "Agent Memory"
    memory_dir.mkdir(parents=True)
    note_path = memory_dir / "legacy.md"
    note_path.write_text(
        """---
artifact_type: semantic_memory
agent_promoted: true
promoted_from_candidate_id: candidate-legacy
source_refs:
- note:legacy-a.md
- note:legacy-b.md
decided_by: companion-ui:reviewer
decided_at: '2026-06-13T09:00:00Z'
---

# Legacy inferred posture

Older notes did not persist an inferred field.
""",
        encoding="utf-8",
    )
    records = [
        {
            "event": "promotion.transition.applied",
            "event_id": "receipt-legacy",
            "trace_id": "trace-legacy",
            "timestamp": "2026-06-13T09:05:00Z",
            "payload": {
                "receipt_id": "receipt-legacy",
                "transition_family": "agent_memory_materialization",
                "target_maturity": "semantic_memory",
                "artifact_uuid": "artifact-legacy",
                "artifact_path": "Agent Memory/legacy.md",
                "authority": {
                    "requested_by": "companion-ui:reviewer",
                },
                "basis": {
                    "candidate_id": "candidate-legacy",
                    "source_refs": ["note:legacy-a.md", "note:legacy-b.md"],
                },
                "outcome": {
                    "status": "applied",
                    "review_state": "accepted",
                    "maturity": "semantic_memory",
                },
                "artifact_linkage": {
                    "artifact_uuid": "artifact-legacy",
                    "artifact_path": "Agent Memory/legacy.md",
                    "candidate_id": "candidate-legacy",
                },
            },
        }
    ]

    memories = read_promoted_memories(vault_root=vault_root, records=records)

    assert memories[0].candidate.inferred is True


def test_selects_relevant_topk_and_caps(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault = _vault(vault_root)
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    _materialize(
        _candidate(
            "candidate-watcher-default",
            title="Watcher default posture",
            content="Watcher launchers should use loopback default unless LAN is explicit.",
            source_refs=["note:watcher-default.md"],
        ),
        vault=vault,
        store=store,
        outbox=outbox,
    )
    _materialize(
        _candidate(
            "candidate-watcher-audit",
            title="Watcher audit",
            content="Audit watcher receipts before promotion.",
            source_refs=["note:watcher-audit.md"],
        ),
        vault=vault,
        store=store,
        outbox=outbox,
    )
    _materialize(
        _candidate(
            "candidate-recall-runtime",
            title="Recall runtime",
            content="Guarded memory recall remains read-only awareness.",
            source_refs=["note:recall-runtime.md"],
        ),
        vault=vault,
        store=store,
        outbox=outbox,
    )

    results = retrieve_relevant_promoted(
        "watcher default loopback",
        k=2,
        vault_root=vault_root,
        outbox_path=outbox,
    )

    assert [item.promoted.candidate.candidate_id for item in results] == [
        "candidate-watcher-default",
        "candidate-watcher-audit",
    ]
    assert len(results) == 2
    assert results[0].score > results[1].score
    assert "watcher" in results[0].reason
    assert (
        retrieve_relevant_promoted(
            "unrelated quantum bananas",
            k=3,
            vault_root=vault_root,
            outbox_path=outbox,
        )
        == []
    )


def test_pure_and_safe_on_empty(tmp_path: Path) -> None:
    missing_vault = tmp_path / "missing-vault"
    missing_outbox = tmp_path / "missing-outbox.jsonl"

    assert read_promoted_memories(vault_root=missing_vault, outbox_path=missing_outbox) == []
    assert (
        retrieve_relevant_promoted(
            "watcher default",
            vault_root=missing_vault,
            outbox_path=missing_outbox,
        )
        == []
    )
    assert not missing_vault.exists()
    assert not missing_outbox.exists()

    vault_root = tmp_path / "empty-vault"
    vault_root.mkdir()
    before = sorted(path.relative_to(vault_root).as_posix() for path in vault_root.rglob("*"))
    assert retrieve_relevant_promoted("", vault_root=vault_root, outbox_path=missing_outbox) == []
    after = sorted(path.relative_to(vault_root).as_posix() for path in vault_root.rglob("*"))
    assert after == before
