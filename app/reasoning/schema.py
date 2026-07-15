from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypeAlias

from pydantic import BaseModel, Field, ValidationError


class RelationSnapshot(BaseModel):
    source: str
    target: str
    type: str = Field(pattern="^(supports|extends|contradicts|derived_from)$")


class ReasoningInput(BaseModel):
    object_uuid: str
    text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    relations: List[RelationSnapshot] = Field(default_factory=list)


class Claim(BaseModel):
    id: str
    object_uuid: str
    text: str
    modality: str = Field(pattern="^(assertion|question|hypothesis)$")
    confidence: float = Field(ge=0.0, le=1.0)


class Evidence(BaseModel):
    id: str
    object_uuid: str
    source_ref: str
    kind: str
    strength: float = Field(ge=0.0, le=1.0)


class Inference(BaseModel):
    id: str
    premises: List[str]
    conclusion_id: str
    type: str
    rationale: str


ReasoningOutcome: TypeAlias = Literal[
    "success",
    "empty_output",
    "provider_failure",
    "missing_input",
]


class ReasoningOutput(BaseModel):
    claims: List[Claim] = Field(default_factory=list)
    evidence: List[Evidence] = Field(default_factory=list)
    inferences: List[Inference] = Field(default_factory=list)
    outcome: ReasoningOutcome = "success"
    degraded_reason: str | None = None

    @property
    def degraded(self) -> bool:
        """Return degradation truth derived from the execution outcome."""

        return self.outcome != "success"


class ReasoningValidationError(RuntimeError):
    pass


def validate_output(payload: Any) -> ReasoningOutput:
    if isinstance(payload, dict):
        # Provider JSON owns cognition content only. Execution outcome is
        # derived by the runtime boundary after the provider call completes;
        # accepting these fields from model output would let an LLM declare
        # its own success or failure posture.
        payload = {
            "claims": payload.get("claims", []),
            "evidence": payload.get("evidence", []),
            "inferences": payload.get("inferences", []),
        }
    try:
        return ReasoningOutput.model_validate(payload or {})
    except ValidationError as exc:
        raise ReasoningValidationError(str(exc)) from exc


__all__ = [
    "ReasoningInput",
    "ReasoningOutput",
    "RelationSnapshot",
    "Claim",
    "Evidence",
    "Inference",
    "ReasoningOutcome",
    "ReasoningValidationError",
    "validate_output",
]
