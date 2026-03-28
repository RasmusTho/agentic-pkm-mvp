"""Validation utilities for tagged embeddings."""

from __future__ import annotations

from typing import Any

from app.components.embeddings.schema import EmbeddingTag, TaggedEmbedding


# Known provider identifiers (used for validation)
KNOWN_PROVIDERS = {
    "openai",
    "anthropic",
    "local",
    "mock",
    "legacy",  # Used for auto-tagged legacy embeddings
    "deterministic",  # Used for deterministic/offline embeddings
}


def validate_embedding_tags(embeddings: list[TaggedEmbedding]) -> bool:
    """Validate a list of tagged embeddings.

    Checks:
    1. All embeddings have non-null tags
    2. All tags have valid provider/model strings
    3. Provider is in known list
    4. No embeddings are None

    Args:
        embeddings: List of TaggedEmbedding objects

    Returns:
        True if all embeddings are valid

    Raises:
        ValueError: if any embedding fails validation
    """
    if not isinstance(embeddings, list):
        raise ValueError(f"embeddings must be a list, got {type(embeddings)}")

    for i, emb in enumerate(embeddings):
        try:
            validate_single_embedding(emb)
        except ValueError as e:
            raise ValueError(f"Embedding {i} failed validation: {e}") from e

    return True


def validate_single_embedding(embedding: Any) -> None:
    """Validate a single TaggedEmbedding object.

    Args:
        embedding: Object to validate

    Raises:
        ValueError: if validation fails
    """
    if embedding is None:
        raise ValueError("Embedding cannot be None")

    if not isinstance(embedding, TaggedEmbedding):
        raise ValueError(
            f"Expected TaggedEmbedding, got {type(embedding).__name__}"
        )

    # Validate required fields
    if not embedding.id or not isinstance(embedding.id, str):
        raise ValueError(f"id must be a non-empty string, got {embedding.id!r}")

    if not embedding.uuid or not isinstance(embedding.uuid, str):
        raise ValueError(f"uuid must be a non-empty string, got {embedding.uuid!r}")

    if not embedding.text or not isinstance(embedding.text, str):
        raise ValueError(f"text must be a non-empty string, got {embedding.text!r}")

    if not isinstance(embedding.vector, list):
        raise ValueError(f"vector must be a list, got {type(embedding.vector)}")

    if not embedding.vector:
        raise ValueError("vector cannot be empty")

    # Validate tag
    if embedding.tag is None:
        raise ValueError("tag cannot be None")

    if not isinstance(embedding.tag, EmbeddingTag):
        raise ValueError(
            f"tag must be EmbeddingTag, got {type(embedding.tag).__name__}"
        )

    # Validate tag structure
    if not embedding.tag.provider or not isinstance(embedding.tag.provider, str):
        raise ValueError(f"provider must be a non-empty string, got {embedding.tag.provider!r}")

    if not embedding.tag.model or not isinstance(embedding.tag.model, str):
        raise ValueError(f"model must be a non-empty string, got {embedding.tag.model!r}")

    # Validate provider is recognized
    if embedding.tag.provider not in KNOWN_PROVIDERS:
        raise ValueError(
            f"provider {embedding.tag.provider!r} is not in known providers: {sorted(KNOWN_PROVIDERS)}"
        )


def validate_tag_structure(tag: Any) -> None:
    """Validate an EmbeddingTag structure.

    Args:
        tag: Object to validate as EmbeddingTag

    Raises:
        ValueError: if validation fails
    """
    if tag is None:
        raise ValueError("tag cannot be None")

    if not isinstance(tag, EmbeddingTag):
        raise ValueError(f"Expected EmbeddingTag, got {type(tag).__name__}")

    if not tag.provider or not isinstance(tag.provider, str):
        raise ValueError(f"provider must be a non-empty string, got {tag.provider!r}")

    if not tag.model or not isinstance(tag.model, str):
        raise ValueError(f"model must be a non-empty string, got {tag.model!r}")

    if tag.provider not in KNOWN_PROVIDERS:
        raise ValueError(
            f"provider {tag.provider!r} is not in known providers: {sorted(KNOWN_PROVIDERS)}"
        )
