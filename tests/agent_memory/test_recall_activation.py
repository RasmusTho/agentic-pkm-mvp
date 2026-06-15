"""Action-authorizing recall receipt-reference tests (#2014, AC#3).

The valid ``action_authorizing`` recall path must supply a ``receipt_reference``
to ``build_recall_explanation``; otherwise that builder raises ``ValueError``
because action-authorizing explanations require a non-null receipt reference.
The recall receipt id is pre-minted and used both as the explanation's
receipt_reference and as the emitted receipt id (one record, no orphan ref).

Source authority:
- app/agent_memory/recall_activation.py (PR #1915 thread PRRT_kwDOQEip6s6JT5Bl)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.agent_memory.candidate import MemoryCandidate, MemoryType, ReviewState
from app.agent_memory.promotion import PromotedMemory
from app.agent_memory.recall_activation import activate_guarded_recall
from app.agent_memory.recall_explanation import ActivationReason, RecallUseRight


def _action_authorizing_promoted() -> PromotedMemory:
    candidate = MemoryCandidate(
        title="Accepted preference policy",
        # preference_memory is in the action-authorizing memory-type set.
        memory_type=MemoryType.PREFERENCE_MEMORY,
        review_state=ReviewState.ACCEPTED,
        inferred=False,
        content="Always confirm before destructive writes.",
        source_refs=["vault://notes/preferences.md"],
        derived_from="receipt://review-100",
        generated_by="agent://planner",
    )
    return PromotedMemory(
        outcome=ReviewState.ACCEPTED,
        candidate=candidate,
        decided_by="human://reviewer",
        decided_at=datetime.now(timezone.utc),
    )


def test_action_authorizing_supplies_receipt_reference(tmp_path: Path) -> None:
    receipt_path = tmp_path / "recall_receipts.jsonl"
    promoted = _action_authorizing_promoted()

    # Before the fix this raised ValueError("action_authorizing recall requires
    # ... receipt_reference") because receipt_reference was None.
    result = activate_guarded_recall(
        promoted,
        use_right=RecallUseRight.ACTION_AUTHORIZING,
        activation_reason=ActivationReason.AUTHORITY_SIGNAL,
        why_now="A governed write path asked whether memory can authorize mutation.",
        requested_action_scope="active_note_body_update",
        behavioral_claim="Confirm before destructive writes.",
        authority_source="review_receipt",
        receipt_path=receipt_path,
    )

    assert result.may_write is True
    assert result.explanation.use_right is RecallUseRight.ACTION_AUTHORIZING
    assert result.receipt_id
    # The explanation's receipt_reference is the emitted receipt id.
    assert result.explanation.receipt_reference == result.receipt_id

    records = [json.loads(line) for line in receipt_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["event_id"] == result.receipt_id
    assert records[0]["payload"]["may_write"] is True
