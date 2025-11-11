from __future__ import annotations

from typing import Iterable, Iterator, List, Sequence

from app.llm import embeddings as _emb


def embed_text(text: str) -> List[float]:
    return _emb.embed_text(text)


def embed_texts(texts: Sequence[str]) -> List[List[float]]:
    return _emb.embed_texts(list(texts))


def embed_batches(texts: Iterable[str], batch_size: int = 64) -> Iterator[List[List[float]]]:
    batch: List[str] = []
    for text in texts:
        batch.append(text)
        if len(batch) >= batch_size:
            yield embed_texts(batch)
            batch = []
    if batch:
        yield embed_texts(batch)


__all__ = ["embed_text", "embed_texts", "embed_batches"]
