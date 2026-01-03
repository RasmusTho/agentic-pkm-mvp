from __future__ import annotations

from typing import Any, Iterable, Sequence

from app.components.embeddings import EmbeddingIdentity, get_embedding_client


def embed_query(text: str, *, profile: str = "default") -> tuple[list[float], EmbeddingIdentity]:
    client = get_embedding_client(profile=profile)
    return client.embed_text(text), client.identity


def embed_docs(texts: Iterable[str], *, profile: str = "default") -> tuple[list[list[float]], EmbeddingIdentity]:
    client = get_embedding_client(profile=profile)
    vectors: list[list[float]] = []
    for batch in client.embed_batches(list(texts)):
        vectors.extend(batch)
    return vectors, client.identity


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
