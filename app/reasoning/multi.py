from __future__ import annotations

from typing import Iterable, List, Sequence
from uuid import UUID

from app.reasoning.provider import get_reasoner
from app.reasoning.schema import Claim, Evidence, Inference, ReasoningInput, ReasoningOutput
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


def run_multi_note_reasoning(object_ids: Sequence[str]) -> ReasoningOutput:
    """
    Run reasoning across multiple notes and merge the results.
    Falls back gracefully if any note is missing.
    """
    reasoner = get_reasoner()
    texts = _load_texts(object_ids)
    all_claims: List[Claim] = []
    all_evidence: List[Evidence] = []
    all_inferences: List[Inference] = []
    for object_id, text in texts:
        reasoning_input = ReasoningInput(
            object_uuid=object_id,
            text=text,
            metadata={},
            relations=[],
        )
        try:
            result = reasoner.reason(reasoning_input)
        except Exception:
            result = ReasoningOutput()
        all_claims.extend(result.claims)
        all_inferences.extend(result.inferences)
        all_evidence.extend(result.evidence)
    if not all_claims and texts:
        for idx, (object_id, text) in enumerate(texts, start=1):
            snippet = text.strip().splitlines()[0] if text else ""
            all_claims.append(
                Claim(
                    id=f"multi-claim-{idx}",
                    object_uuid=object_id,
                    text=snippet or f"Synthesized claim for {object_id}",
                    modality="assertion",
                    confidence=0.5,
                )
            )
    synthesis = _build_synthesis_inference(all_claims, [oid for oid, _ in texts])
    if synthesis:
        all_inferences.append(synthesis)
    return ReasoningOutput(
        claims=all_claims,
        evidence=all_evidence,
        inferences=all_inferences,
    )


__all__ = ["run_multi_note_reasoning"]
