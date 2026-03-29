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
    "ollama",
    "deepseek",
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


def assert_compatible_tags(a: TaggedEmbedding, b: TaggedEmbedding) -> None:
    """Assert that two embeddings come from the same provider and model.

    Embeddings from different providers/models live in incompatible vector
    spaces and must never be compared directly.  Call this guard before any
    cosine-similarity or dot-product comparison to catch cross-provider
    contamination early.

    Args:
        a: First TaggedEmbedding
        b: Second TaggedEmbedding

    Raises:
        TypeError: if either argument is not a TaggedEmbedding
        ValueError: if the provider or model of the two embeddings differ
    """
    if not isinstance(a, TaggedEmbedding):
        raise TypeError(f"Expected TaggedEmbedding, got {type(a).__name__}")
    if not isinstance(b, TaggedEmbedding):
        raise TypeError(f"Expected TaggedEmbedding, got {type(b).__name__}")

    if a.tag.provider != b.tag.provider:
        raise ValueError(
            f"Cross-provider embedding comparison rejected: "
            f"a={a.tag.provider!r} vs b={b.tag.provider!r}. "
            "Embeddings from different providers live in incompatible vector spaces. "
            "Re-embed both texts with the same provider before comparing."
        )
    if a.tag.model != b.tag.model:
        raise ValueError(
            f"Cross-model embedding comparison rejected: "
            f"a={a.tag.provider}/{a.tag.model!r} vs b={b.tag.provider}/{b.tag.model!r}. "
            "Embeddings from different models live in incompatible vector spaces. "
            "Re-embed both texts with the same model before comparing."
        )


def assert_compatible_tag_with_index(
    embedding: TaggedEmbedding,
    index_provider: str,
    index_model: str,
) -> None:
    """Assert that an embedding is compatible with a stored index identity.

    Use this when inserting or querying a vector index that was built with a
    specific provider/model, to prevent silent cross-provider contamination.

    Args:
        embedding: The TaggedEmbedding to check
        index_provider: Provider string stored in the index
        index_model: Model string stored in the index

    Raises:
        TypeError: if embedding is not a TaggedEmbedding
        ValueError: if provider or model do not match the index identity
    """
    if not isinstance(embedding, TaggedEmbedding):
        raise TypeError(f"Expected TaggedEmbedding, got {type(embedding).__name__}")

    if embedding.tag.provider != index_provider:
        raise ValueError(
            f"Embedding provider {embedding.tag.provider!r} does not match "
            f"index provider {index_provider!r}. "
            "Run index rebuild to realign, or use a provider-matched embedding."
        )
    if embedding.tag.model != index_model:
        raise ValueError(
            f"Embedding model {embedding.tag.model!r} does not match "
            f"index model {index_model!r}. "
            "Run index rebuild to realign, or use a model-matched embedding."
        )
