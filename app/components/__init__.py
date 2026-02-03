"""Component entrypoints.

Keep this module import-light.

Historically we re-exported a few helpers from submodules here. Importing those
submodules eagerly can create circular imports during runtime settings bootstrap
(e.g. settings -> panel actions -> components -> embeddings -> settings).

Use module-level __getattr__ (PEP 562) for lazy re-exports.
"""

from __future__ import annotations

from typing import Any


_EMBEDDINGS_EXPORTS = {
    "EmbeddingClientProtocol",
    "EmbeddingIdentity",
    "get_embedding_client",
    "get_embedding_identity",
    "resolve_embedding_identity",
}

_OCR_EXPORTS = {"get_structured_ocr", "get_compressive_ocr"}


def __getattr__(name: str) -> Any:  # pragma: no cover
    if name in _EMBEDDINGS_EXPORTS:
        from . import embeddings as _embeddings

        return getattr(_embeddings, name)

    if name in _OCR_EXPORTS:
        from . import ocr as _ocr

        return getattr(_ocr, name)

    raise AttributeError(name)


def get_reranker(profile: str = "balanced"):
    from .rerankers import get_reranker as _get_reranker

    return _get_reranker(profile)


__all__ = [
    *_EMBEDDINGS_EXPORTS,
    *_OCR_EXPORTS,
    "get_reranker",
]
