"""Embedding provider tagging and management module.

This package provides:
- Tagging: TaggedEmbedding, EmbeddingTag, EmbeddingProvider ABC
- Validation: tag structure and completeness checking
- Audit: counting and querying by provider/model
- Migration: legacy embedding tagging and provider migration
- Legacy: EmbeddingIdentity, EmbeddingClientProtocol, get_embedding_client
  (for backward compatibility with existing code)
"""

from __future__ import annotations

# New tagging system (no heavy dependencies)
from app.components.embeddings.schema import (
    EmbeddingTag,
    TaggedEmbedding,
)
from app.components.embeddings.base import EmbeddingProvider
from app.components.embeddings.validation import (
    validate_embedding_tags,
    validate_single_embedding,
)
from app.components.embeddings.audit import (
    count_by_provider,
    count_by_provider_model,
    find_untagged,
    list_all_with_tags,
)
from app.components.embeddings.migration import (
    detect_untagged_embeddings,
    auto_tag_legacy,
    migrate_provider,
)

# Legacy re-exports (lazy-loaded to avoid circular imports)
def __getattr__(name: str):
    """Lazy-load legacy module on demand."""
    if name in {
        "EmbeddingClientProtocol",
        "EmbeddingIdentity",
        "get_embedding_client",
        "get_embedding_identity",
        "describe_embedding",
        "resolve_embedding_identity",
        "EMBED_MODEL",
    }:
        from app.components.embeddings.legacy import (
            EmbeddingClientProtocol,
            EmbeddingIdentity,
            get_embedding_client,
            get_embedding_identity,
            describe_embedding,
            resolve_embedding_identity,
            EMBED_MODEL,
        )
        locals()[name] = locals()[name]
        return locals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # New tagging system
    "EmbeddingTag",
    "TaggedEmbedding",
    "EmbeddingProvider",
    "validate_embedding_tags",
    "validate_single_embedding",
    "count_by_provider",
    "count_by_provider_model",
    "find_untagged",
    "list_all_with_tags",
    "detect_untagged_embeddings",
    "auto_tag_legacy",
    "migrate_provider",
    # Legacy (backward compatibility)
    "EmbeddingClientProtocol",
    "EmbeddingIdentity",
    "get_embedding_client",
    "get_embedding_identity",
    "describe_embedding",
    "resolve_embedding_identity",
    "EMBED_MODEL",
]
