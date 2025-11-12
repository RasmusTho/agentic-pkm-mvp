from __future__ import annotations

from typing import Dict, List
from uuid import uuid4

from app.reasoning.schema import Claim, Evidence, Inference, ReasoningOutput


class ReasoningStore:
    def __init__(self) -> None:
        self._claims: Dict[str, Claim] = {}
        self._evidence: Dict[str, Evidence] = {}
        self._inferences: Dict[str, Inference] = {}

    def upsert(self, object_uuid: str, output: ReasoningOutput) -> Dict[str, int]:
        added_claims = 0
        added_evidence = 0
        added_inferences = 0

        for claim in output.claims:
            key = claim.id or f"claim-{uuid4()}"
            claim = Claim(id=key, **claim.model_dump(exclude={"id"}))
            self._claims[key] = claim
            added_claims += 1

        for evidence in output.evidence:
            key = evidence.id or f"evidence-{uuid4()}"
            evidence = Evidence(id=key, **evidence.model_dump(exclude={"id"}))
            self._evidence[key] = evidence
            added_evidence += 1

        for inference in output.inferences:
            key = inference.id or f"inference-{uuid4()}"
            inference = Inference(id=key, **inference.model_dump(exclude={"id"}))
            self._inferences[key] = inference
            added_inferences += 1

        return {
            "claims": added_claims,
            "evidence": added_evidence,
            "inferences": added_inferences,
        }

    def claims(self) -> List[Claim]:
        return list(self._claims.values())

    def inferences(self) -> List[Inference]:
        return list(self._inferences.values())


_STORE = ReasoningStore()


def get_reasoning_store() -> ReasoningStore:
    return _STORE


def reset_reasoning_store() -> None:
    global _STORE
    _STORE = ReasoningStore()


__all__ = ["ReasoningStore", "get_reasoning_store"]
