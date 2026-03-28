"""Audit and query utilities for tagged embeddings.

Provides counting, querying, and migration detection functions.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.components.embeddings.schema import TaggedEmbedding


def count_by_provider(embeddings: list[TaggedEmbedding], provider: str) -> int:
    """Count embeddings from a specific provider.

    Args:
        embeddings: List of TaggedEmbedding objects
        provider: Provider name to filter by (e.g., 'openai', 'anthropic')

    Returns:
        Count of embeddings with matching provider
    """
    return sum(1 for emb in embeddings if emb.tag.provider == provider)


def count_by_provider_model(
    embeddings: list[TaggedEmbedding],
    provider: str,
    model: str,
) -> int:
    """Count embeddings from a specific provider/model pair.

    Args:
        embeddings: List of TaggedEmbedding objects
        provider: Provider name (e.g., 'openai')
        model: Model identifier (e.g., 'text-embedding-3-small')

    Returns:
        Count of embeddings with exact provider/model match
    """
    return sum(
        1 for emb in embeddings
        if emb.tag.provider == provider and emb.tag.model == model
    )


def find_untagged(embeddings: list[TaggedEmbedding]) -> list[TaggedEmbedding]:
    """Find embeddings with None or invalid tags (for migration).

    Note: In a production system, this would query the storage backend
    to find embeddings that exist but don't have tags. For now, we
    filter the given list.

    Args:
        embeddings: List of TaggedEmbedding objects

    Returns:
        List of embeddings with invalid/missing tags
    """
    untagged = []
    for emb in embeddings:
        if emb.tag is None:
            untagged.append(emb)
        elif not emb.tag.provider or not emb.tag.model:
            untagged.append(emb)
    return untagged


def list_all_with_tags(embeddings: list[TaggedEmbedding]) -> list[TaggedEmbedding]:
    """Return all embeddings that have valid tags.

    Args:
        embeddings: List of TaggedEmbedding objects

    Returns:
        Filtered list of embeddings with valid tags only
    """
    return [
        emb for emb in embeddings
        if emb.tag is not None
        and emb.tag.provider
        and emb.tag.model
    ]


def get_provider_distribution(embeddings: list[TaggedEmbedding]) -> dict[str, int]:
    """Get count of embeddings by provider.

    Args:
        embeddings: List of TaggedEmbedding objects

    Returns:
        Dictionary mapping provider -> count
    """
    counter: Counter[str] = Counter()
    for emb in embeddings:
        counter[emb.tag.provider] += 1
    return dict(counter)


def get_model_distribution(embeddings: list[TaggedEmbedding]) -> dict[str, int]:
    """Get count of embeddings by provider/model.

    Args:
        embeddings: List of TaggedEmbedding objects

    Returns:
        Dictionary mapping "provider/model" -> count
    """
    counter: Counter[str] = Counter()
    for emb in embeddings:
        key = f"{emb.tag.provider}/{emb.tag.model}"
        counter[key] += 1
    return dict(counter)


def filter_by_provider(
    embeddings: list[TaggedEmbedding],
    provider: str,
) -> list[TaggedEmbedding]:
    """Filter embeddings by provider.

    Args:
        embeddings: List of TaggedEmbedding objects
        provider: Provider to filter by

    Returns:
        Embeddings from the specified provider
    """
    return [emb for emb in embeddings if emb.tag.provider == provider]


def filter_by_provider_model(
    embeddings: list[TaggedEmbedding],
    provider: str,
    model: str,
) -> list[TaggedEmbedding]:
    """Filter embeddings by provider/model.

    Args:
        embeddings: List of TaggedEmbedding objects
        provider: Provider to filter by
        model: Model to filter by

    Returns:
        Embeddings from the specified provider/model
    """
    return [
        emb for emb in embeddings
        if emb.tag.provider == provider and emb.tag.model == model
    ]
