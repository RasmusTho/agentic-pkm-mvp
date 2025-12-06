from .embeddings import get_embedding_client, EmbeddingClientProtocol
from .ocr import get_structured_ocr, get_compressive_ocr


def get_reranker(profile: str = "balanced"):
    from .rerankers import get_reranker as _get_reranker

    return _get_reranker(profile)


__all__ = [
    "EmbeddingClientProtocol",
    "get_embedding_client",
    "get_reranker",
    "get_structured_ocr",
    "get_compressive_ocr",
]
