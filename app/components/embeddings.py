from __future__ import annotations

from typing import Iterable, Iterator, Protocol, Sequence

from app.index import embeddings as _index_embeddings
from app.search import embeddings as _deterministic_embeddings


class EmbeddingClientProtocol(Protocol):
    """Minimal embedding client interface for text and batch embeddings."""

    def embed_text(self, text: str) -> list[float]:
        ...

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        ...

    def embed_batches(self, texts: Iterable[str], batch_size: int = 32) -> Iterator[list[list[float]]]:
        ...


class _DefaultEmbeddingClient:
    def embed_text(self, text: str) -> list[float]:
        return _index_embeddings.embed_text(text)

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            return _index_embeddings.embed_texts(list(texts))
        except Exception:
            return [_index_embeddings.embed_text(t) for t in texts]

    def embed_batches(self, texts: Iterable[str], batch_size: int = 32) -> Iterator[list[list[float]]]:
        yield from _index_embeddings.embed_batches(texts, batch_size=batch_size)


class _DeterministicEmbeddingClient:
    """Deterministic embedding client used for tests and legacy heuristics."""

    def embed_text(self, text: str) -> list[float]:
        return _deterministic_embeddings.embed_text(text)

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        return _deterministic_embeddings.embed_many(list(texts))

    def embed_batches(self, texts: Iterable[str], batch_size: int = 32) -> Iterator[list[list[float]]]:
        batch: list[str] = []
        for text in texts:
            batch.append(text)
            if len(batch) >= batch_size:
                yield self.embed_texts(batch)
                batch = []
        if batch:
            yield self.embed_texts(batch)


def get_embedding_client(profile: str = "default") -> EmbeddingClientProtocol:
    """
    Return the embedding client for the given profile.
    - default: current index embeddings stack (speaker-aware text enrichment + LLM embeddings)
    - deterministic/test: hashing-based deterministic embeddings used in tests
    """
    spec = (profile or "default").strip().lower()
    if spec in {"deterministic", "test", "offline"}:
        return _DeterministicEmbeddingClient()
    return _DefaultEmbeddingClient()


__all__ = ["EmbeddingClientProtocol", "get_embedding_client"]
