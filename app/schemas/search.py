from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query_text: str | None = Field(None, description="Full-text query string.")
    query_embedding: list[float] | None = Field(
        None, description="Pre-computed embedding vector matching pgvector dimension."
    )
    k: int = Field(10, ge=1, le=100, description="Maximum number of search results.")


class SearchHit(BaseModel):
    object_id: UUID
    score: float
    payload: dict[str, Any]


class SearchResponse(BaseModel):
    hits: list[SearchHit]
