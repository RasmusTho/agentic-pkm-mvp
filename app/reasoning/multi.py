from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

from app.reasoning.provider import run_reasoning_claims_for_object
from app.reasoning.schema import Claim, Evidence, Inference, ReasoningOutcome, ReasoningOutput
from app.stores import get_object_store


@dataclass(frozen=True)
class ReasoningSourceInput:
    """One cited text projected into the UUID-addressable reasoning store."""

    source_id: str
    text: str


@dataclass(frozen=True)
class MaterializedReasoningInput:
    source_id: str
    object_id: str
    text: str


def materialize_reasoning_inputs(
    sources: Sequence[ReasoningSourceInput], *, namespace_key: str
) -> tuple[MaterializedReasoningInput, ...]:
    """Persist rebuildable, non-knowledge inputs for ``run_multi_note_reasoning``.

    The current reasoning substrate is UUID/object-store addressed. This
    adapter keeps that contract explicit for callers whose durable sources are
    vault transcript/context references rather than object UUIDs. The payload
    is an unbound machine mirror, never canonical knowledge or retrieval rank.
    """

    store = get_object_store()
    materialized: list[MaterializedReasoningInput] = []
    for source in sources:
        text = source.text.strip()
        if not source.source_id.strip() or not text:
            continue
        object_id = uuid5(NAMESPACE_URL, f"{namespace_key}:{source.source_id}")
        payload = {
            "text": text,
            "content": text,
            "episode_ref": "unbound",
            "authority_state": "proposal_input",
        }
        store.put(
            object_id,
            kind="reasoning_input",
            source_ref=source.source_id,
            payload=payload,
        )
        resolved = store.get(object_id)
        resolved_payload = resolved.get("payload") if resolved else None
        if not isinstance(resolved_payload, dict) or not str(
            resolved_payload.get("text") or ""
        ).strip():
            raise RuntimeError(
                f"reasoning input {source.source_id!r} did not resolve after materialization"
            )
        materialized.append(
            MaterializedReasoningInput(
                source_id=source.source_id,
                object_id=str(object_id),
                text=text,
            )
        )
    return tuple(materialized)


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
    if outcome == "success":
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


__all__ = [
    "MaterializedReasoningInput",
    "ReasoningSourceInput",
    "materialize_reasoning_inputs",
    "run_multi_note_reasoning",
]
