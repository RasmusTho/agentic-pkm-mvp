from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.agent_memory.authority_guard import (
    MemoryAuthorityDecision,
    evaluate_memory_authority,
)
from app.agent_memory.promotion import PromotedMemory
from app.agent_memory.recall_explanation import (
    ActivationReason,
    RecallExplanation,
    RecallUseRight,
    build_recall_explanation,
)

RECALL_RECEIPT_EVENT = "agent_memory.recall.activated"
RECALL_RECEIPT_SOURCE = "agent_memory.recall_activation"


@dataclass(frozen=True)
class GuardedRecall:
    memory_id: str
    may_answer: bool
    may_propose: bool
    may_write: bool
    authority_decision: MemoryAuthorityDecision
    explanation: RecallExplanation
    receipt_id: str


def activate_guarded_recall(
    promoted: PromotedMemory,
    *,
    use_right: RecallUseRight,
    activation_reason: ActivationReason,
    why_now: str,
    receipt_path: Path,
    requested_action_scope: str | None = None,
    behavioral_claim: str | None = None,
    authority_source: str | None = None,
    source_artifact_path: Path | None = None,
) -> GuardedRecall:
    decision = evaluate_memory_authority(
        promoted,
        use_right=use_right,
        requested_action_scope=requested_action_scope,
    )
    explanation_use_right = use_right
    if use_right is RecallUseRight.ACTION_AUTHORIZING and not decision.allow_mutation:
        explanation_use_right = RecallUseRight.ACTIVATABLE
    explanation = build_recall_explanation(
        promoted,
        use_right=explanation_use_right,
        activation_reason=activation_reason,
        why_now=why_now,
        behavioral_claim=behavioral_claim if explanation_use_right is not RecallUseRight.ACTIVATABLE else None,
        action_scope=requested_action_scope if decision.allow_mutation else None,
        authority_source=authority_source if decision.allow_mutation else None,
        receipt_reference=None,
    )
    receipt_id = _emit_recall_receipt(
        receipt_path,
        promoted=promoted,
        decision=decision,
        explanation=explanation,
        requested_use_right=use_right,
        source_artifact_path=source_artifact_path,
    )
    return GuardedRecall(
        memory_id=promoted.candidate.candidate_id,
        may_answer=decision.allow_suggestion,
        may_propose=decision.allow_suggestion,
        may_write=decision.allow_mutation,
        authority_decision=decision,
        explanation=explanation.model_copy(update={"receipt_reference": receipt_id}),
        receipt_id=receipt_id,
    )


def _emit_recall_receipt(
    receipt_path: Path,
    *,
    promoted: PromotedMemory,
    decision: MemoryAuthorityDecision,
    explanation: RecallExplanation,
    requested_use_right: RecallUseRight,
    source_artifact_path: Path | None,
) -> str:
    receipt_id = uuid4().hex
    record = {
        "event": RECALL_RECEIPT_EVENT,
        "event_id": receipt_id,
        "trace_id": uuid4().hex,
        "source": RECALL_RECEIPT_SOURCE,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "payload": {
            "memory_id": promoted.candidate.candidate_id,
            "promotion_id": promoted.promotion_id,
            "requested_use_right": requested_use_right.value,
            "granted_authority_level": decision.authority_level.value,
            "may_answer": decision.allow_suggestion,
            "may_propose": decision.allow_suggestion,
            "may_write": decision.allow_mutation,
            "blocked_reasons": list(decision.blocked_reasons),
            "posture_markers": list(decision.posture_markers),
            "activation": {
                "reason": explanation.activation_reason.value,
                "why_now": explanation.why_now,
            },
            "source_provenance": explanation.source_provenance.model_dump(),
            "authority_limits": list(explanation.authority_limits),
            "source_artifact_path": str(source_artifact_path) if source_artifact_path else None,
        },
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    with receipt_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    return receipt_id


__all__ = [
    "GuardedRecall",
    "RECALL_RECEIPT_EVENT",
    "activate_guarded_recall",
]
