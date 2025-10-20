from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class InterestingItem(BaseModel):
    object_id: UUID
    score: float
    novelty: float
    anomaly: float
    uncertainty: float
    value: float
    reason: str
    payload: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class InterestingResponse(BaseModel):
    items: list[InterestingItem] = Field(default_factory=list)


class InterestingSummary(BaseModel):
    total: int = 0
    system_intent: dict[str, int] = Field(default_factory=dict)
    emergent_tags: dict[str, int] = Field(default_factory=dict)
