from __future__ import annotations

from typing import Iterable, List, Sequence
from uuid import UUID

from app.reasoning.provider import run_reasoning_claims_for_object
from app.reasoning.schema import Claim, Evidence, Inference, ReasoningOutcome, ReasoningOutput
from app.stores import get_object_store


def _load_texts(object_ids: Iterable[str]) -> List[tuple[str, str]]:
    store = get_object_store()
    texts: List[tuple[str, str]] = []
    for raw_id in object_ids:
        try:
            obj = store.get(UUID(str(raw_id)))
        except Exception:
            obj = None
        payload = obj.get("payload") if obj else {}
        text = ""
        if isinstance(payload, dict):
            text = payload.get("text") or payload.get("content") or ""
        if not text:
            continue
        texts.append((str(raw_id), str(text)))
    return texts


def _build_synthesis_inference(claims: Sequence[Claim], object_ids: Sequence[str]) -> Inference | None:
    if len(object_ids) < 2 or len(claims) < 2:
        return None
    first_claim = claims[0]
    second_claim = claims[1]
    rationale = f"Synthesizes insights from {object_ids[0]} and {object_ids[1]}."
    return Inference(
        id=f"synthesis-{object_ids[0]}-{object_ids[1]}",
        premises=[first_claim.id, second_claim.id],
        conclusion_id=first_claim.id,
        type="synthesis",
        rationale=rationale,
    )


def run_multi_note_reasoning(object_ids: Sequence[str], *, trace_id: str | None = None) -> ReasoningOutput:
    """
    Run reasoning across multiple notes and merge the results.
    Falls back gracefully if any note is missing.
    """
    if not object_ids:
        return ReasoningOutput(
            outcome="missing_input", degraded_reason="missing_input"
        )

    texts = _load_texts(object_ids)
    all_claims: List[Claim] = []
    all_evidence: List[Evidence] = []
    all_inferences: List[Inference] = []
    outcomes: list[ReasoningOutcome] = []
    if len(texts) < len(object_ids):
        outcomes.append("missing_input")
    for object_id, text in texts:
        try:
            result = run_reasoning_claims_for_object(object_id, trace_id=trace_id)
        except Exception:
            result = ReasoningOutput(
                outcome="provider_failure", degraded_reason="provider_failure"
            )
        if result.outcome == "success" and not (
            result.claims or result.evidence or result.inferences
        ):
            result = result.model_copy(
                update={
                    "outcome": "empty_output",
                    "degraded_reason": "empty_provider_output",
                }
            )
        outcomes.append(result.outcome)
        all_claims.extend(result.claims)
        all_inferences.extend(result.inferences)
        all_evidence.extend(result.evidence)

    outcome: ReasoningOutcome = "success"
    degraded_reason: str | None = None
    if "provider_failure" in outcomes:
        outcome = "provider_failure"
        degraded_reason = "provider_failure"
    elif "empty_output" in outcomes:
        outcome = "empty_output"
        degraded_reason = "empty_provider_output"
    elif "missing_input" in outcomes:
        outcome = "missing_input"
        degraded_reason = "missing_input"

    synthesis = None
    if not {"provider_failure", "empty_output"}.intersection(outcomes):
        synthesis = _build_synthesis_inference(all_claims, [oid for oid, _ in texts])
    if synthesis:
        all_inferences.append(synthesis)
    return ReasoningOutput(
        claims=all_claims,
        evidence=all_evidence,
        inferences=all_inferences,
        outcome=outcome,
        degraded_reason=degraded_reason,
    )


__all__ = ["run_multi_note_reasoning"]
