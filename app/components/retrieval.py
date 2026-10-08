from __future__ import annotations

from typing import Any, Iterable, Sequence

from app.components.embeddings import EmbeddingClientProtocol, EmbeddingIdentity
from app.components.llm.fabric import (
    get_product_embedding_client,
)
from app.index.embedding_identity import ensure_index_primary_identity
from app.stores import get_vector_index


def _embedding_client_for_profile(profile: str) -> EmbeddingClientProtocol:
    return get_product_embedding_client(profile=profile)


def embed_query(text: str, *, profile: str = "default") -> tuple[list[float], EmbeddingIdentity]:
    client = _embedding_client_for_profile(profile)
    try:
        # Query embeddings must share the persisted index's complete identity;
        # equal vector dimensions alone do not imply compatible embedding spaces.
        ensure_index_primary_identity(get_vector_index(), client.identity)
        vector, identity = client.embed_text(text), client.identity
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    return vector, identity


def embed_docs(texts: Iterable[str], *, profile: str = "default") -> tuple[list[list[float]], EmbeddingIdentity]:
    client = _embedding_client_for_profile(profile)
    try:
        vectors: list[list[float]] = []
        for batch in client.embed_batches(list(texts)):
            vectors.extend(batch)
        identity = client.identity
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    return vectors, identity


def search(
    query: str,
    *,
    k: int = 8,
    filters: dict[str, Any] | None = None,
    profile: str = "default",
) -> dict[str, Any]:
    vector, identity = embed_query(query, profile=profile)
    from app.retrieval.hybrid import hybrid_search

    results = hybrid_search(query, k=k, query_vector=vector)
    provenance = {
        "profile": profile,
        "provider": identity.provider,
        "model": identity.model,
        "dim": identity.dim,
        "normalize": identity.normalize,
        "filters": filters or {},
    }
    return {"results": results, "identity": identity, "provenance": provenance}


__all__ = ["embed_query", "embed_docs", "search"]
