from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl

from app.ingest.staging import PendingDocument


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


class PendingDocumentModel(BaseModel):
    doc_path: str
    trust: str
    chunk_count: int
    first_seen: datetime

    @classmethod
    def from_dataclass(cls, doc: PendingDocument) -> PendingDocumentModel:
        return cls(
            doc_path=doc.doc_path,
            trust=doc.trust,
            chunk_count=doc.chunk_count,
            first_seen=doc.first_seen,
        )


class ReviewRequest(BaseModel):
    doc_path: str = Field(..., description="Relative path to the document in the vault")
    new_trust: str = Field("reviewed", description="New trust value, e.g. reviewed or indexed")
