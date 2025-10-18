from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, HttpUrl


class SourceType(str, Enum):
    file = "file"
    url = "url"
    text = "text"


class SourcePayload(BaseModel):
    type: SourceType
    path: str | None = Field(None, description="Filesystem path when type=file")
    url: HttpUrl | None = Field(None, description="External URL when type=url")
    text: str | None = Field(None, description="Inline text when type=text")


class IngestRequest(BaseModel):
    source: SourcePayload
    tags: list[str] = Field(default_factory=list)
    notes: str | None = None


class ChunkResult(BaseModel):
    id: str
    text: str
    size: int


class IngestResponse(BaseModel):
    ok: bool
    title: str
    path: str
    tags: list[str]
    trust: str
    chunks: list[ChunkResult]
