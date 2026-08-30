from __future__ import annotations

import json
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
    scope_id: str = "scope:work/project-alpha",
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
        scope_id=scope_id,
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
    assert promoted.candidate.scope_id == candidate.scope_id
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
uuid: artifact-legacy
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


def test_scope_bound_promoted_recall_excludes_private_memory(tmp_path: Path) -> None:
    """A bound recall only admits promoted memories with the same persisted scope."""
    vault_root = tmp_path / "vault"
    memory_dir = vault_root / "Agent Memory"
    memory_dir.mkdir(parents=True)
    records = []
    for candidate_id, authority_line, receipt_scope, title in (
        ("candidate-work", "scope_id: scope-work\n", "scope-work", "Work deployment posture"),
        (
            "candidate-private",
            "scope_id: scope-private\n",
            "scope-private",
            "Private deployment posture",
        ),
        ("candidate-legacy", "", None, "Legacy deployment posture"),
        (
            "candidate-domain-only",
            "domain: scope-work\n",
            None,
            "Domain-only deployment posture",
        ),
        (
            "candidate-invalid-scope",
            "scope_id: 'invalid scope'\n",
            "invalid scope",
            "Invalid-scope deployment posture",
        ),
        (
            "candidate-overlength-scope",
            f"scope_id: {'s' * 129}\n",
            "s" * 129,
            "Overlength-scope deployment posture",
        ),
    ):
        artifact_path = f"Agent Memory/{candidate_id}.md"
        (vault_root / artifact_path).write_text(
            "---\n"
            "artifact_type: semantic_memory\n"
            "agent_promoted: true\n"
            f"uuid: artifact-{candidate_id}\n"
            f"promoted_from_candidate_id: {candidate_id}\n"
            f"{authority_line}"
            "decided_by: companion-ui:reviewer\n"
            "decided_at: '2026-06-13T09:00:00Z'\n"
            "---\n\n"
            f"# {title}\n\nDeployment posture details.\n",
            encoding="utf-8",
        )
        records.append(
            {
                "event": "promotion.transition.applied",
                "event_id": f"receipt-{candidate_id}",
                "trace_id": f"trace-{candidate_id}",
                "timestamp": "2026-06-13T09:05:00Z",
                "payload": {
                    "receipt_id": f"receipt-{candidate_id}",
                    "transition_family": "agent_memory_materialization",
                    "target_maturity": "semantic_memory",
                    "artifact_uuid": f"artifact-{candidate_id}",
                    "artifact_path": artifact_path,
                    "authority": {"requested_by": "companion-ui:reviewer"},
                    "vault_id": "vault-a",
                    "basis": {
                        "candidate_id": candidate_id,
                        **({"scope_id": receipt_scope} if receipt_scope is not None else {}),
                    },
                    "outcome": {"status": "applied", "review_state": "accepted"},
                    "artifact_linkage": {
                        "artifact_uuid": f"artifact-{candidate_id}",
                        "artifact_path": artifact_path,
                        "candidate_id": candidate_id,
                    },
                },
            }
        )

    scoped = retrieve_relevant_promoted(
        "deployment posture",
        vault_root=vault_root,
        records=records,
        active_scope_id="scope-work",
        active_vault_id="vault-a",
    )

    assert [item.promoted.candidate.candidate_id for item in scoped] == ["candidate-work"]
    assert scoped[0].memory_scope_id == "scope-work"
    assert scoped[0].promoted.candidate.scope_id == "scope-work"
    assert scoped[0].applied_scope_id == "scope-work"

    unbound = retrieve_relevant_promoted(
        "deployment posture",
        k=10,
        vault_root=vault_root,
        records=records,
    )

    assert {item.promoted.candidate.candidate_id for item in unbound} == {
        "candidate-work",
        "candidate-private",
        "candidate-legacy",
        "candidate-domain-only",
        "candidate-invalid-scope",
        "candidate-overlength-scope",
    }
    assert {item.applied_scope_id for item in unbound} == {None}
    unbound_by_id = {
        item.promoted.candidate.candidate_id: item
        for item in unbound
    }
    for candidate_id in (
        "candidate-legacy",
        "candidate-domain-only",
        "candidate-invalid-scope",
        "candidate-overlength-scope",
    ):
        assert unbound_by_id[candidate_id].memory_scope_id is None
        assert unbound_by_id[candidate_id].promoted.candidate.scope_id is None


def test_materialized_scope_drives_bound_recall_admission(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault = _vault(vault_root)
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    _materialize(
        _candidate(
            "candidate-work-materialized",
            title="Work deployment posture",
            content="Deployment posture details.",
            scope_id="scope-work",
        ),
        vault=vault,
        store=store,
        outbox=outbox,
    )

    admitted = retrieve_relevant_promoted(
        "deployment posture",
        vault_root=vault_root,
        outbox_path=outbox,
        active_scope_id="scope-work",
        active_vault_id="vault-a",
    )
    denied = retrieve_relevant_promoted(
        "deployment posture",
        vault_root=vault_root,
        outbox_path=outbox,
        active_scope_id="scope-private",
        active_vault_id="vault-a",
    )

    assert [item.promoted.candidate.candidate_id for item in admitted] == [
        "candidate-work-materialized"
    ]
    assert admitted[0].memory_scope_id == "scope-work"
    assert denied == []


def test_bound_recall_rejects_note_scope_tampering_against_receipt(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault = _vault(vault_root)
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    artifact_path = _materialize(
        _candidate(
            "candidate-private-tamper",
            title="Private deployment posture",
            content="Deployment posture details.",
            scope_id="scope-private",
        ),
        vault=vault,
        store=store,
        outbox=outbox,
    )
    note_path = vault_root / artifact_path
    note_path.write_text(
        note_path.read_text(encoding="utf-8").replace(
            "scope_id: scope-private",
            "scope_id: scope-work",
        ),
        encoding="utf-8",
    )

    assert retrieve_relevant_promoted(
        "deployment posture",
        vault_root=vault_root,
        outbox_path=outbox,
        active_scope_id="scope-work",
        active_vault_id="vault-a",
    ) == []


def test_bound_recall_rejects_receipt_from_another_vault(tmp_path: Path) -> None:
    source_root = tmp_path / "source-vault"
    source_root.mkdir()
    source_vault = _vault(source_root)
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    artifact_path = _materialize(
        _candidate(
            "candidate-cross-vault",
            title="Work deployment posture",
            content="Deployment posture details.",
            scope_id="scope-work",
        ),
        vault=source_vault,
        store=store,
        outbox=outbox,
    )
    target_root = tmp_path / "target-vault"
    target_note = target_root / artifact_path
    target_note.parent.mkdir(parents=True)
    target_note.write_text(
        (source_root / artifact_path).read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    assert retrieve_relevant_promoted(
        "deployment posture",
        vault_root=target_root,
        outbox_path=outbox,
        active_scope_id="scope-work",
        active_vault_id="vault-b",
    ) == []


@pytest.mark.parametrize(
    ("field", "conflicting_value"),
    (
        ("artifact_uuid", "conflicting-artifact-uuid"),
        ("artifact_path", "Agent Memory/conflicting-artifact.md"),
    ),
)
def test_bound_recall_rejects_conflicting_receipt_artifact_identity(
    tmp_path: Path,
    field: str,
    conflicting_value: str,
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    vault = _vault(vault_root)
    store = ReviewDecisionStore(tmp_path / "review_decisions.sqlite3")
    outbox = tmp_path / "outbox.jsonl"
    _materialize(
        _candidate(
            "candidate-receipt-conflict",
            title="Work deployment posture",
            content="Deployment posture details.",
            scope_id="scope-work",
        ),
        vault=vault,
        store=store,
        outbox=outbox,
    )
    record = json.loads(outbox.read_text(encoding="utf-8"))
    record["payload"][field] = conflicting_value

    assert retrieve_relevant_promoted(
        "deployment posture",
        vault_root=vault_root,
        records=[record],
        active_scope_id="scope-work",
        active_vault_id="vault-a",
    ) == []


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
