from __future__ import annotations

from typing import Any, Dict, List, Optional

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


class ReasoningOutput(BaseModel):
    claims: List[Claim] = Field(default_factory=list)
    evidence: List[Evidence] = Field(default_factory=list)
    inferences: List[Inference] = Field(default_factory=list)


class ReasoningValidationError(RuntimeError):
    pass


def validate_output(payload: Any) -> ReasoningOutput:
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
    "ReasoningValidationError",
    "validate_output",
]
