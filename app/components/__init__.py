from .embeddings import (
    EmbeddingClientProtocol,
    EmbeddingIdentity,
    get_embedding_client,
    get_embedding_identity,
)
from .ocr import get_structured_ocr, get_compressive_ocr


def get_reranker(profile: str = "balanced"):
    from .rerankers import get_reranker as _get_reranker

    return _get_reranker(profile)


__all__ = [
    "EmbeddingClientProtocol",
    "EmbeddingIdentity",
    "get_embedding_client",
    "get_embedding_identity",
    "get_reranker",
    "get_structured_ocr",
    "get_compressive_ocr",
]
