from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.agent_memory import recall_activation
from app.agent_memory.candidate import MemoryCandidate, MemoryType, ReviewState
from app.agent_memory.promotion import PromotedMemory
from app.agent_memory.recall_activation import (
    RECALL_RECEIPT_EVENT,
    activate_guarded_recall,
)
from app.agent_memory.recall_explanation import ActivationReason, RecallUseRight


def _candidate(
    *,
    review_state: ReviewState = ReviewState.ACCEPTED,
    inferred: bool = False,
) -> MemoryCandidate:
    return MemoryCandidate(
        title="Design preference memory",
        memory_type=MemoryType.PREFERENCE_MEMORY,
        review_state=review_state,
        inferred=inferred,
        content="Prefer concise implementation summaries.",
        source_refs=["vault://notes/preferences.md"],
        derived_from="receipt://review-001",
        generated_by="agent://planner",
    )


def _promoted(
    *,
    review_state: ReviewState = ReviewState.ACCEPTED,
    inferred: bool = False,
) -> PromotedMemory:
    return PromotedMemory(
        outcome=ReviewState.ACCEPTED,
        candidate=_candidate(review_state=review_state, inferred=inferred),
        decided_by="human://reviewer",
        decided_at=datetime.now(timezone.utc),
    )


def _receipt_records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_recall_runs_authority_guard_and_emits_receipt(
    tmp_path: Path, monkeypatch
) -> None:
    calls = []
    original = recall_activation.evaluate_memory_authority

    def spy(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(recall_activation, "evaluate_memory_authority", spy)
    receipt_path = tmp_path / "recall_receipts.jsonl"
    promoted = _promoted()

    result = activate_guarded_recall(
        promoted,
        use_right=RecallUseRight.INSTRUCTIONAL,
        activation_reason=ActivationReason.CONTEXTUAL_RELEVANCE,
        why_now="Current task asks for implementation-summary preferences.",
        behavioral_claim="Keep implementation summaries concise.",
        receipt_path=receipt_path,
    )

    assert calls
    assert result.may_answer is True
    assert result.may_propose is True
    assert result.receipt_id
    records = _receipt_records(receipt_path)
    assert records[0]["event"] == RECALL_RECEIPT_EVENT
    assert records[0]["payload"]["memory_id"] == promoted.candidate.candidate_id
    assert records[0]["payload"]["may_write"] is False


def test_unreviewed_recall_cannot_authorize_writeback(tmp_path: Path) -> None:
    result = activate_guarded_recall(
        _promoted(review_state=ReviewState.UNREVIEWED, inferred=True),
        use_right=RecallUseRight.ACTION_AUTHORIZING,
        activation_reason=ActivationReason.AUTHORITY_SIGNAL,
        why_now="A write path asked whether memory can authorize mutation.",
        requested_action_scope="active_note_body_update",
        behavioral_claim="Prefer concise implementation summaries.",
        authority_source="review_receipt",
        receipt_path=tmp_path / "recall_receipts.jsonl",
    )

    assert result.may_answer is True
    assert result.may_propose is True
    assert result.may_write is False
    assert "review_state_not_accepted" in result.authority_decision.blocked_reasons
    assert "inferred_memory_not_mutation_authoritative" in result.authority_decision.blocked_reasons
    assert result.explanation.use_right is RecallUseRight.ACTIVATABLE


def test_activation_not_persisted_as_authority(tmp_path: Path) -> None:
    artifact = tmp_path / "memory.md"
    original_body = "---\nreview_state: accepted\n---\n\nMemory body.\n"
    artifact.write_text(original_body, encoding="utf-8")
    receipt_path = tmp_path / "receipts" / "recall.jsonl"

    result = activate_guarded_recall(
        _promoted(),
        use_right=RecallUseRight.ACTIVATABLE,
        activation_reason=ActivationReason.EXPLICIT_REFERENCE,
        why_now="The caller explicitly referenced this memory.",
        receipt_path=receipt_path,
        source_artifact_path=artifact,
    )

    assert result.receipt_id
    assert artifact.read_text(encoding="utf-8") == original_body
    receipt = _receipt_records(receipt_path)[0]
    assert receipt["payload"]["activation"]["reason"] == "explicit_reference"
    assert "activation" not in artifact.read_text(encoding="utf-8")
