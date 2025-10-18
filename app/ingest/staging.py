from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.ingest.chunker import ChunkConfig


@dataclass(slots=True)
class PendingChunk:
    id: str
    text: str
    size: int
    doc_path: str
    trust: str = "provisional"


def stage_chunks(chunks: Iterable[PendingChunk], config: ChunkConfig | None = None) -> None:
    """Placeholder for staging chunk persistence.

    In the MVP we keep chunks in memory or log them. A future step will
    persist to DuckDB (chunks_pending) until the document is reviewed.
    The optional config arg allows auditing which chunk settings were applied.
    """
    # TODO: write to DuckDB / external store.
    return None
