"""Pytest fixtures for embedding tests."""

from __future__ import annotations

from datetime import datetime
import sys

# Prevent conftest.py from being loaded to avoid dependency issues
# We only need the embeddings submodules which have minimal dependencies
import pytest

from app.components.embeddings.schema import EmbeddingTag, TaggedEmbedding
from app.components.embeddings.providers.mock import MockEmbeddings


@pytest.fixture
def mock_tag() -> EmbeddingTag:
    """Fixture: EmbeddingTag for mock provider."""
    return EmbeddingTag(provider="mock", model="mock")


@pytest.fixture
def openai_tag() -> EmbeddingTag:
    """Fixture: EmbeddingTag for OpenAI provider."""
    return EmbeddingTag(provider="openai", model="text-embedding-3-small")


@pytest.fixture
def anthropic_tag() -> EmbeddingTag:
    """Fixture: EmbeddingTag for Anthropic provider."""
    return EmbeddingTag(provider="anthropic", model="claude-3-haiku")


@pytest.fixture
def local_tag() -> EmbeddingTag:
    """Fixture: EmbeddingTag for local provider."""
    return EmbeddingTag(provider="local", model="all-minilm-l6-v2")


@pytest.fixture
def legacy_tag() -> EmbeddingTag:
    """Fixture: EmbeddingTag for legacy provider."""
    return EmbeddingTag(provider="legacy", model="unknown")


@pytest.fixture
def sample_vector() -> list[float]:
    """Fixture: Sample embedding vector (384 dimensions)."""
    return [0.1 * (i % 10) for i in range(384)]


@pytest.fixture
def sample_text() -> str:
    """Fixture: Sample text for embedding."""
    return "This is a sample text to embed."


@pytest.fixture
def sample_tagged_embedding(sample_text, sample_vector, mock_tag) -> TaggedEmbedding:
    """Fixture: Sample TaggedEmbedding object."""
    return TaggedEmbedding(
        uuid="test-uuid-1",
        text=sample_text,
        vector=sample_vector,
        tag=mock_tag,
    )


@pytest.fixture
def mock_embeddings_provider() -> MockEmbeddings:
    """Fixture: MockEmbeddings provider instance."""
    return MockEmbeddings()


@pytest.fixture
def sample_embeddings_batch(mock_embeddings_provider) -> list[TaggedEmbedding]:
    """Fixture: Batch of 10 sample TaggedEmbedding objects."""
    texts = [
        "First sample text",
        "Second sample text",
        "Third sample text",
        "Fourth sample text",
        "Fifth sample text",
        "Sixth sample text",
        "Seventh sample text",
        "Eighth sample text",
        "Ninth sample text",
        "Tenth sample text",
    ]
    embeddings = mock_embeddings_provider.embed_batch(texts)
    # Assign UUIDs
    for i, emb in enumerate(embeddings):
        object.__setattr__(emb, "uuid", f"uuid-{i}")
    return embeddings


@pytest.fixture
def mixed_provider_embeddings(
    sample_embeddings_batch,
    openai_tag,
    anthropic_tag,
    local_tag,
) -> list[TaggedEmbedding]:
    """Fixture: Embeddings from multiple providers.

    Returns 12 embeddings:
    - 4 from mock provider
    - 4 from openai
    - 2 from anthropic
    - 2 from local
    """
    embeddings = []

    # Use first 4 from sample batch (already mock-tagged)
    embeddings.extend(sample_embeddings_batch[:4])

    # Create 4 openai-tagged embeddings
    for i in range(4):
        text = f"OpenAI text {i}"
        vector = [0.1 * (i % 10) for _ in range(384)]
        emb = TaggedEmbedding(
            uuid=f"openai-uuid-{i}",
            text=text,
            vector=vector,
            tag=openai_tag,
        )
        embeddings.append(emb)

    # Create 2 anthropic-tagged embeddings
    for i in range(2):
        text = f"Anthropic text {i}"
        vector = [0.2 * (i % 10) for _ in range(384)]
        emb = TaggedEmbedding(
            uuid=f"anthropic-uuid-{i}",
            text=text,
            vector=vector,
            tag=anthropic_tag,
        )
        embeddings.append(emb)

    # Create 2 local-tagged embeddings
    for i in range(2):
        text = f"Local text {i}"
        vector = [0.3 * (i % 10) for _ in range(384)]
        emb = TaggedEmbedding(
            uuid=f"local-uuid-{i}",
            text=text,
            vector=vector,
            tag=local_tag,
        )
        embeddings.append(emb)

    return embeddings
