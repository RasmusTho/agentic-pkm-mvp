from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.settings import settings


@dataclass(slots=True)
class ChunkConfig:
    size: int = settings.chunk_size
    overlap: int = settings.chunk_overlap


def _tokenize(text: str) -> list[str]:
    return text.split()


def _detokenize(tokens: Iterable[str]) -> str:
    return " ".join(tokens)


def chunk_text(text: str, config: ChunkConfig | None = None) -> list[str]:
    cfg = config or ChunkConfig()
    tokens = _tokenize(text)

    if not tokens:
        return []

    size = max(cfg.size, 1)
    overlap = max(min(cfg.overlap, size - 1), 0)

    chunks: list[str] = []
    start = 0
    while start < len(tokens):
        end = min(start + size, len(tokens))
        window = tokens[start:end]
        chunks.append(_detokenize(window))
        if end == len(tokens):
            break
        start = end - overlap
    return chunks
