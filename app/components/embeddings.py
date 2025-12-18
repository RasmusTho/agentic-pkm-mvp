from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Iterator, Protocol, Sequence

from app.embedding_config import get_embed_dim
from app.index import embeddings as _index_embeddings
from app.llm.embeddings import EMBED_MODEL, get_embedding_provider


class EmbeddingClientProtocol(Protocol):
    """Minimal embedding client interface for text and batch embeddings."""

    def embed_text(self, text: str) -> list[float]:
        ...

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        ...

    def embed_batches(self, texts: Iterable[str], batch_size: int = 32) -> Iterator[list[list[float]]]:
        ...


@dataclass(frozen=True)
class EmbeddingIdentity:
    provider: str
    model: str
    dim: int



@lru_cache(maxsize=1)
def _deterministic_embeddings_module():
    from app.search import embeddings as deterministic_embeddings
    return deterministic_embeddings

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
        module = _deterministic_embeddings_module()
        return module.embed_text(text, dimensions=get_embed_dim())

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        dim = get_embed_dim()
        module = _deterministic_embeddings_module()
        return module.embed_many(list(texts), dimensions=dim)

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
    """Return the embedding client for the given profile."""

    spec = (profile or "default").strip().lower()
    if spec in {"deterministic", "test", "offline"}:
        return _DeterministicEmbeddingClient()
    return _DefaultEmbeddingClient()


def get_embedding_identity(
    client: EmbeddingClientProtocol | None = None,
    *,
    profile: str = "default",
) -> EmbeddingIdentity:
    """Describe the configured embedding stack for persistence/validation."""

    spec = (profile or "default").strip().lower()
    if client is None:
        client = get_embedding_client(profile)
    dim = get_embed_dim()
    if isinstance(client, _DeterministicEmbeddingClient) or spec in {"deterministic", "test", "offline"}:
        return EmbeddingIdentity(provider="deterministic", model="deterministic-hash", dim=dim)
    return EmbeddingIdentity(provider=get_embedding_provider(), model=EMBED_MODEL, dim=dim)


def describe_embedding(text: str, *, profile: str = "default") -> tuple[EmbeddingIdentity, list[float]]:
    client = get_embedding_client(profile)
    vector = client.embed_text(text)
    identity = get_embedding_identity(client=client, profile=profile)
    return identity, vector


__all__ = [
    "EmbeddingClientProtocol",
    "EmbeddingIdentity",
    "get_embedding_client",
    "get_embedding_identity",
    "describe_embedding",
    "EMBED_MODEL",
]
