from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    id: UUID | None = Field(
        None,
        description="Stable identifier for the object; generated if omitted.",
    )
    kind: str | None = Field(
        None,
        description="Arbitrary classifier for the object.",
    )
    source_ref: str | None = Field(
        None,
        description="Provenance reference for the object.",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Metadata stored as JSONB.",
    )
    text: str = Field(
        ...,
        description="Primary textual content used for embeddings and search.",
    )


class IngestResponse(BaseModel):
    ok: bool = True
    object_id: UUID
    dimensions: int
    model: str
