from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid1

from app.activation.gate import AdmissionTier, ConsumingAuthority
from app.agent_memory.candidate import MemoryType, ReviewState
from app.agent_memory.provisional_memory import ProvisionalSensitivity
from app.agent_memory.provisional_recall import (
    PROVISIONAL_RECALL_RECEIPT_EVENT,
    ProvisionalRecallCandidate,
    activate_provisional_recall,
    retrieve_relevant_provisional,
)
from app.agent_memory.provisional_write import (
    ProvisionalReceiptStore,
    ProvisionalWriteRequest,
    write_provisional_memory,
)
from app.agent_memory.recall_explanation import ActivationReason, RecallUseRight
from app.write_guard import WriteGuard


def _candidate(tmp_path: Path) -> tuple[Path, ProvisionalReceiptStore, ProvisionalRecallCandidate]:
    vault = tmp_path / "vault"
    vault.mkdir()
    store = ProvisionalReceiptStore(tmp_path / "provisional.jsonl")
    write_provisional_memory(
        ProvisionalWriteRequest(
            scope_id="scope-personal",
            principal_id="principal-1",
            memory_type=MemoryType.PREFERENCE_MEMORY,
            sensitivity=ProvisionalSensitivity.PRIVATE,
            content="Prefer deterministic bilingual retrieval evaluation.",
            provenance_event_ids=("event-1",),
        ),
        vault_root=vault,
        receipt_store=store,
        write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}),
    )
    search = retrieve_relevant_provisional(
        "Which retrieval evaluation is preferred?",
        vault_root=vault,
        receipt_store=store,
        active_scope_id="scope-personal",
    )
    assert len(search.candidates) == 1
    return vault, store, search.candidates[0]


def _write_provisional(
    tmp_path: Path,
    *,
    content: str,
) -> tuple[Path, ProvisionalReceiptStore]:
    vault = tmp_path / "vault"
    vault.mkdir()
    store = ProvisionalReceiptStore(tmp_path / "provisional.jsonl")
    write_provisional_memory(
        ProvisionalWriteRequest(
            scope_id="scope-personal",
            principal_id="principal-1",
            memory_type=MemoryType.PREFERENCE_MEMORY,
            sensitivity=ProvisionalSensitivity.PRIVATE,
            content=content,
            provenance_event_ids=("event-1",),
        ),
        vault_root=vault,
        receipt_store=store,
        write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}),
    )
    return vault, store


def test_read_context_preserves_low_trust_posture(tmp_path: Path) -> None:
    _, _, candidate = _candidate(tmp_path)
    result = activate_provisional_recall(
        candidate,
        consuming_authority=ConsumingAuthority.READ_ONLY,
        active_scope_id="scope-personal",
        use_right=RecallUseRight.ACTIVATABLE,
        activation_reason=ActivationReason.CONTEXTUAL_RELEVANCE,
        receipt_path=tmp_path / "recall.jsonl",
    )

    assert result.admitted is True
    assert result.may_answer is True
    assert result.may_propose is False
    assert result.may_write is False
    assert result.admissibility_decision.admitted_tier is AdmissionTier.READ
    assert result.explanation is not None
    assert result.explanation.trust_state == "provisional_low_trust_noncanonical"
    assert result.explanation.review_state is ReviewState.UNREVIEWED
    assert "event-1" in result.explanation.source_provenance.source_refs
    assert "never_apply_or_tool_use" in result.explanation.authority_limits


def test_stopwords_do_not_create_provisional_recall_match(tmp_path: Path) -> None:
    vault, store = _write_provisional(
        tmp_path,
        content="The and of to in with for.",
    )

    search = retrieve_relevant_provisional(
        "the and of",
        vault_root=vault,
        receipt_store=store,
        active_scope_id="scope-personal",
    )

    assert search.candidates == ()


def test_meaningful_terms_survive_stopword_filtering(tmp_path: Path) -> None:
    vault, store = _write_provisional(
        tmp_path,
        content="Prefer deterministic bilingual retrieval evaluation.",
    )

    search = retrieve_relevant_provisional(
        "Which retrieval evaluation is preferred?",
        vault_root=vault,
        receipt_store=store,
        active_scope_id="scope-personal",
    )

    assert len(search.candidates) == 1
    assert search.candidates[0].score > 0


def test_proposal_use_requires_explicit_citation(tmp_path: Path) -> None:
    _, _, candidate = _candidate(tmp_path)
    denied = activate_provisional_recall(
        candidate,
        consuming_authority=ConsumingAuthority.PROPOSAL,
        active_scope_id="scope-personal",
        use_right=RecallUseRight.CITED_PROPOSAL,
        activation_reason=ActivationReason.EXPLICIT_REFERENCE,
        receipt_path=tmp_path / "recall.jsonl",
    )
    admitted = activate_provisional_recall(
        candidate,
        consuming_authority=ConsumingAuthority.PROPOSAL,
        active_scope_id="scope-personal",
        use_right=RecallUseRight.CITED_PROPOSAL,
        activation_reason=ActivationReason.EXPLICIT_REFERENCE,
        citation_reference="proposal://draft-1#citation-1",
        receipt_path=tmp_path / "recall.jsonl",
    )
    mismatched_right = activate_provisional_recall(
        candidate,
        consuming_authority=ConsumingAuthority.PROPOSAL,
        active_scope_id="scope-personal",
        use_right=RecallUseRight.ACTIVATABLE,
        activation_reason=ActivationReason.EXPLICIT_REFERENCE,
        citation_reference="proposal://draft-1#citation-1",
        receipt_path=tmp_path / "recall.jsonl",
    )

    assert denied.admitted is False
    assert denied.explanation is None
    assert admitted.admitted is True
    assert admitted.may_propose is True
    assert admitted.may_write is False
    assert admitted.explanation is not None
    assert "proposal://draft-1#citation-1" in admitted.explanation.source_provenance.source_refs
    assert mismatched_right.admitted is False


def test_recall_receipt_does_not_persist_activation_authority(tmp_path: Path) -> None:
    vault, _, candidate = _candidate(tmp_path)
    artifact = vault / candidate.record.artifact_ref.removeprefix("vault://")
    before = artifact.read_bytes()
    receipt_path = tmp_path / "recall.jsonl"

    result = activate_provisional_recall(
        candidate,
        consuming_authority=ConsumingAuthority.READ_ONLY,
        active_scope_id="scope-personal",
        use_right=RecallUseRight.ACTIVATABLE,
        activation_reason=ActivationReason.CONTEXTUAL_RELEVANCE,
        receipt_path=receipt_path,
    )

    assert artifact.read_bytes() == before
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["event"] == PROVISIONAL_RECALL_RECEIPT_EVENT
    assert receipt["event_id"] == result.receipt_id
    assert receipt["payload"]["may_write"] is False
    assert "deterministic bilingual" not in receipt_path.read_text(encoding="utf-8")


def test_incomplete_lifecycle_pair_is_excluded_before_ranking(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    store = ProvisionalReceiptStore(tmp_path / "provisional.jsonl")
    result = write_provisional_memory(
        ProvisionalWriteRequest(
            scope_id="scope-personal",
            principal_id="principal-1",
            memory_type=MemoryType.SEMANTIC_MEMORY,
            sensitivity=ProvisionalSensitivity.PRIVATE,
            content="This artifact will lose its terminal receipt.",
            provenance_event_ids=("event-2",),
        ),
        vault_root=vault,
        receipt_store=store,
        write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}),
    )
    lines = store.path.read_text(encoding="utf-8").splitlines()
    store.path.write_text(lines[0] + "\n", encoding="utf-8")

    search = retrieve_relevant_provisional(
        "terminal receipt",
        vault_root=vault,
        receipt_store=store,
        active_scope_id="scope-personal",
    )

    assert search.candidates == ()
    assert search.excluded[0].memory_id == str(result.lifecycle_receipt.memory_id)
    assert search.excluded[0].reason_code == "artifact_without_terminal_success_receipt"


def test_missing_provenance_is_excluded_with_content_free_diagnostic(tmp_path: Path) -> None:
    vault, store, candidate = _candidate(tmp_path)
    artifact = vault / candidate.record.artifact_ref.removeprefix("vault://")
    raw = artifact.read_text(encoding="utf-8")
    artifact.write_text(
        raw.replace("provenance_event_ids:\n- event-1\n", ""),
        encoding="utf-8",
    )

    search = retrieve_relevant_provisional(
        "deterministic bilingual retrieval",
        vault_root=vault,
        receipt_store=store,
        active_scope_id="scope-personal",
    )

    assert search.candidates == ()
    assert search.excluded[0].reason_code == "artifact_invalid"
    assert "deterministic bilingual" not in repr(search.excluded)


def test_non_uuid4_filename_is_excluded_without_crashing_recall(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    directory = vault / "Memory" / "Provisional"
    directory.mkdir(parents=True)
    memory_id = uuid1()
    (directory / f"{memory_id}.md").write_text(
        "---\nartifact_type: provisional_memory\n---\n",
        encoding="utf-8",
    )

    search = retrieve_relevant_provisional(
        "anything",
        vault_root=vault,
        receipt_store=ProvisionalReceiptStore(tmp_path / "empty.jsonl"),
        active_scope_id="scope-personal",
    )

    assert search.candidates == ()
    assert search.excluded[0].memory_id == str(memory_id)
    assert search.excluded[0].reason_code == "artifact_identity_invalid"
    assert "artifact_type" not in repr(search.excluded)
