"""ASK answer-synthesis activation through the Expansion Activation Gate (#2026).

First capability activated **through** the deterministic admissibility gate
(:mod:`app.activation.gate`, #2025) instead of the raw ``REASONING_ENABLE`` env
flag. ASK answer synthesis is the lowest-authority proof case
(``docs/plans/DRAFT_EXPANSION_ACTIVATION_GATE.md`` Wave 1): zero write
authority, read-only admission of the retrieved context.

This module owns two read-side concerns and nothing else:

1. Build the gate inputs (an :class:`~app.activation.gate.ActivationPosture` for
   the ASK answer-synthesis capability plus one
   :class:`~app.activation.gate.CandidateContext` per retrieved/recalled item)
   and evaluate the activation decision.
2. Emit a provenance-bearing **activation receipt** for an admitted synthesis,
   mirroring the recall-receipt jsonl pattern
   (:mod:`app.agent_memory.recall_activation`).

It introduces **no** generation code — the existing
``run_reasoning(ASK_ANSWER)`` path is reused unchanged by the ASK graph. When
the gate blocks, the ASK graph preserves its existing literal-snippet /
"No results found." fallback with a logged reason.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional
from uuid import uuid4

from app.activation.gate import (
    ActivationDecision,
    ActivationPosture,
    CandidateContext,
    ConsumingAuthority,
    evaluate_activation,
)

# Capability identifier for the activation ladder / status surface.
ASK_SYNTHESIS_CAPABILITY_ID = "ask.answer_synthesis"

# Scope token for the read-side admissibility evaluation. ASK answer synthesis
# admits only the context produced by this same query within the active vault
# sphere; the gate's sphere axis admits same-scope candidates and the read-only
# consumer ceiling caps the admitted tier at READ.
ASK_SYNTHESIS_SCOPE = "ask.retrieval_context"

ASK_SYNTHESIS_RECEIPT_EVENT = "activation.ask.synthesis"
ASK_SYNTHESIS_RECEIPT_SOURCE = "app.activation.ask_synthesis"

DEFAULT_RECEIPTS_PATH = Path("runtime/activation/ask_synthesis_receipts.jsonl")


def _receipt_path() -> Path:
    configured = os.getenv("ASK_SYNTHESIS_RECEIPTS_PATH")
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_RECEIPTS_PATH


def build_ask_synthesis_posture() -> ActivationPosture:
    """Declare the read-only activation posture for ASK answer synthesis.

    Read-only authority: zero write path, so ``reversible_write_path`` is not a
    blocker (the gate only requires it for ``governed-execution``). The loop
    precondition is the merged admissibility contract + gate function chain
    (#2023/#2024/#2025) and the proven recall read-only path; admissibility is
    declared here (this module *is* the declaration). Observable on the ASK
    response via the surfaced receipt id.
    """

    return ActivationPosture(
        capability_id=ASK_SYNTHESIS_CAPABILITY_ID,
        declared_authority=ConsumingAuthority.READ_ONLY,
        admissibility_declared=True,
        loop_precondition_green=True,
        reversible_write_path=False,
        observable=True,
        scope=ASK_SYNTHESIS_SCOPE,
    )


def build_retrieval_candidates(
    source_ids: Iterable[str],
) -> list[CandidateContext]:
    """Build read-side candidate contexts for retrieved/recalled ASK context.

    Each candidate is declared in the ASK retrieval-context scope (same-scope =>
    admissible on the sphere axis) and as non-memory context (the memory-class
    axis is not binding for retrieved vault sources). Unverified provenance caps
    the candidate at the READ tier, which matches the read-only consumer
    ceiling — exactly the lowest-authority posture for this first proof case.
    """

    candidates: list[CandidateContext] = []
    for source_id in source_ids:
        artifact_id = str(source_id or "").strip()
        if not artifact_id:
            continue
        candidates.append(
            CandidateContext(
                artifact_id=artifact_id,
                sphere=ASK_SYNTHESIS_SCOPE,
                is_memory=False,
                has_provenance=True,
            )
        )
    return candidates


def evaluate_ask_synthesis(
    source_ids: Iterable[str],
    *,
    receipt_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> ActivationDecision:
    """Evaluate the gate decision for ASK answer synthesis over retrieved context.

    Returns the deterministic :class:`ActivationDecision`. ``activatable`` is
    true only when the posture inputs are green and at least one retrieved
    source is admissible. Empty context (no candidates) leaves the no-admissible
    blocker unset so the caller can fall back to "No results found." cleanly.
    """

    posture = build_ask_synthesis_posture()
    candidates = build_retrieval_candidates(source_ids)
    return evaluate_activation(
        posture,
        candidates,
        receipt_id=receipt_id,
        now=now,
    )


def emit_ask_synthesis_receipt(
    decision: ActivationDecision,
    *,
    answer_preview: str | None = None,
    source_paths: dict[str, str] | None = None,
    llm_route: dict | None = None,
    receipt_path: Path | None = None,
) -> str:
    """Emit a provenance-bearing activation receipt for an admitted synthesis.

    Mirrors the recall-receipt jsonl emission
    (:func:`app.agent_memory.recall_activation._emit_recall_receipt`): an
    append-only line carrying what was activated, on whose authority, what
    context it admitted, and the grounded-source linkage. The receipt id is the
    gate decision receipt id, so the activation record and the gate decision
    share one identity.
    """

    path = receipt_path or _receipt_path()
    receipt = decision.receipt
    record = {
        "event": ASK_SYNTHESIS_RECEIPT_EVENT,
        "event_id": receipt.receipt_id,
        "trace_id": uuid4().hex,
        "source": ASK_SYNTHESIS_RECEIPT_SOURCE,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "payload": {
            "capability_id": decision.capability_id,
            "consuming_authority": receipt.consuming_authority.value,
            "outcome": receipt.outcome,
            "activatable": decision.activatable,
            "blocked_reasons": list(decision.blocked_reasons),
            "admitted_artifact_ids": list(decision.admitted_artifact_ids),
            "admitted_source_paths": dict(source_paths or {}),
            "answer_preview": (answer_preview or "")[:280] or None,
            "llm_route": llm_route,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    return receipt.receipt_id


__all__ = [
    "ASK_SYNTHESIS_CAPABILITY_ID",
    "ASK_SYNTHESIS_SCOPE",
    "ASK_SYNTHESIS_RECEIPT_EVENT",
    "build_ask_synthesis_posture",
    "build_retrieval_candidates",
    "evaluate_ask_synthesis",
    "emit_ask_synthesis_receipt",
]
