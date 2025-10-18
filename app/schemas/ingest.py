from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl


class SourceType(str, Enum):
    file = "file"
    url = "url"
    text = "text"


class SourcePayload(BaseModel):
    type: SourceType
    path: Optional[str] = Field(None, description="Filesystem path when type=file")
    url: Optional[HttpUrl] = Field(None, description="External URL when type=url")
    text: Optional[str] = Field(None, description="Inline text when type=text")


class IngestRequest(BaseModel):
    source: SourcePayload
    tags: list[str] = Field(default_factory=list)
    notes: Optional[str] = None


class ChunkResult(BaseModel):
    id: str
    text: str
    size: int


class IngestResponse(BaseModel):
    ok: bool
    title: str
    path: str
    tags: list[str]
    chunks: list[ChunkResult]
