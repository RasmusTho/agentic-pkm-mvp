"""
Test: VectorIndex Storage Contract

Contract: VectorIndex stores and retrieves embeddings WITH tags.
Tags are never stripped. Untagged embeddings are rejected.
"""
from __future__ import annotations

import pytest

from tests.components.embeddings.conftest import (
    TaggedEmbedding,
    InMemoryVectorIndex,
    EmbeddingFactory,
    ProviderEnum,
    ModelEnum,
)


class TestVectorIndexAddTaggedEmbeddings:
    """VectorIndex accepts and stores tagged embeddings."""

    def test_add_single_embedding(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """VectorIndex stores single embedding."""
        emb = embedding_factory.create(provider=ProviderEnum.OPENAI)
        vector_index.add([emb])
        assert vector_index.count() == 1

    def test_add_multiple_embeddings(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """VectorIndex stores multiple embeddings."""
        embeddings = embedding_factory.create_batch(
            ["text1", "text2", "text3"],
            provider=ProviderEnum.OPENAI,
        )
        vector_index.add(embeddings)
        assert vector_index.count() == 3

    def test_add_empty_list(
        self,
        vector_index: InMemoryVectorIndex,
    ) -> None:
        """VectorIndex accepts empty list."""
        vector_index.add([])
        assert vector_index.count() == 0

    def test_store_preserves_provider_tag(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Stored embedding preserves provider tag."""
        emb = embedding_factory.create(provider=ProviderEnum.ANTHROPIC)
        vector_index.add([emb])
        retrieved = vector_index.get(emb.uuid)
        assert retrieved is not None
        assert retrieved.provider == ProviderEnum.ANTHROPIC

    def test_store_preserves_model_tag(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Stored embedding preserves model tag."""
        emb = embedding_factory.create(model=ModelEnum.GPT_4)
        vector_index.add([emb])
        retrieved = vector_index.get(emb.uuid)
        assert retrieved is not None
        assert retrieved.model == ModelEnum.GPT_4


class TestVectorIndexRetrieval:
    """VectorIndex retrieval returns embeddings WITH tags."""

    def test_get_by_uuid(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Retrieve embedding by UUID."""
        emb = embedding_factory.create()
        vector_index.add([emb])
        retrieved = vector_index.get(emb.uuid)
        assert retrieved is not None
        assert retrieved.uuid == emb.uuid

    def test_get_nonexistent_returns_none(
        self,
        vector_index: InMemoryVectorIndex,
    ) -> None:
        """Getting nonexistent UUID returns None."""
        result = vector_index.get("nonexistent-uuid")
        assert result is None

    def test_search_returns_embeddings_with_tags(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Search results include provider/model tags."""
        embeddings = embedding_factory.create_batch(
            ["text1", "text2"],
            provider=ProviderEnum.LOCAL,
            model=ModelEnum.ALL_MINILM,
        )
        vector_index.add(embeddings)
        query_vector = [0.1] * 128
        results = vector_index.search(query_vector, k=10)
        assert len(results) > 0
        for result in results:
            assert result.provider == ProviderEnum.LOCAL
            assert result.model == ModelEnum.ALL_MINILM

    def test_search_empty_index_returns_empty(
        self,
        vector_index: InMemoryVectorIndex,
    ) -> None:
        """Search on empty index returns empty list."""
        results = vector_index.search([0.1] * 128)
        assert results == []

    def test_search_with_empty_query_vector(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Search with empty query vector returns empty."""
        emb = embedding_factory.create()
        vector_index.add([emb])
        results = vector_index.search([], k=5)
        assert results == []

    def test_search_respects_k_limit(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Search respects k parameter limit."""
        embeddings = embedding_factory.create_batch(
            [f"text {i}" for i in range(20)],
        )
        vector_index.add(embeddings)
        results = vector_index.search([0.1] * 128, k=5)
        assert len(results) <= 5


class TestVectorIndexTagPersistence:
    """Tags are never stripped during storage/retrieval."""

    def test_tags_survive_storage(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Provider/model tags survive storage cycle."""
        original = embedding_factory.create(
            text="test",
            provider=ProviderEnum.OPENAI,
            model=ModelEnum.GPT_4,
        )
        vector_index.add([original])
        retrieved = vector_index.get(original.uuid)
        assert retrieved is not None
        assert retrieved.provider == original.provider
        assert retrieved.model == original.model

    def test_tags_survive_search(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Tags appear in search results."""
        embeddings = embedding_factory.create_batch(
            ["a", "b"],
            provider=ProviderEnum.ANTHROPIC,
            model=ModelEnum.CLAUDE_3_SONNET,
        )
        vector_index.add(embeddings)
        results = vector_index.search([0.1] * 128, k=10)
        for result in results:
            assert result.provider == ProviderEnum.ANTHROPIC

    def test_text_preserved_in_storage(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Original text preserved through storage."""
        text = "original input text"
        emb = embedding_factory.create(text=text)
        vector_index.add([emb])
        retrieved = vector_index.get(emb.uuid)
        assert retrieved is not None
        assert retrieved.text == text

    def test_vector_preserved_in_storage(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Vector values preserved through storage."""
        emb = embedding_factory.create()
        vector_index.add([emb])
        retrieved = vector_index.get(emb.uuid)
        assert retrieved is not None
        assert retrieved.vector == emb.vector

    def test_timestamp_preserved_in_storage(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Timestamp preserved through storage."""
        emb = embedding_factory.create()
        vector_index.add([emb])
        retrieved = vector_index.get(emb.uuid)
        assert retrieved is not None
        assert retrieved.created_at == emb.created_at
