"""Tests for MockEmbeddings provider."""

from __future__ import annotations

import pytest

from app.components.embeddings.providers.mock import MockEmbeddings
from app.components.embeddings.schema import TaggedEmbedding


class TestMockEmbeddings:
    """Tests for MockEmbeddings provider."""

    def test_mock_provider_initialization(self) -> None:
        """Should initialize MockEmbeddings."""
        provider = MockEmbeddings()
        assert provider is not None

    def test_mock_provider_tag(self) -> None:
        """MockEmbeddings should have mock tag."""
        provider = MockEmbeddings()
        assert provider.tag.provider == "mock"
        assert provider.tag.model == "mock"

    def test_mock_embed_single_text(self) -> None:
        """Should embed single text."""
        provider = MockEmbeddings()
        emb = provider.embed("test text")
        assert isinstance(emb, TaggedEmbedding)
        assert emb.tag.provider == "mock"
        assert emb.tag.model == "mock"

    def test_mock_embed_returns_vector(self) -> None:
        """Embedded result should have vector."""
        provider = MockEmbeddings()
        emb = provider.embed("test text")
        assert emb.vector is not None
        assert isinstance(emb.vector, list)
        assert len(emb.vector) > 0
        assert all(isinstance(x, float) for x in emb.vector)

    def test_mock_embed_dimension(self) -> None:
        """Mock embedding should have consistent dimension."""
        provider = MockEmbeddings()
        emb = provider.embed("test")
        assert len(emb.vector) == 384

    def test_mock_embed_deterministic(self) -> None:
        """Same text should produce same embedding."""
        provider = MockEmbeddings()
        emb1 = provider.embed("test text")
        emb2 = provider.embed("test text")
        assert emb1.vector == emb2.vector

    def test_mock_embed_different_texts_different_vectors(self) -> None:
        """Different texts should produce different embeddings."""
        provider = MockEmbeddings()
        emb1 = provider.embed("text one")
        emb2 = provider.embed("text two")
        assert emb1.vector != emb2.vector

    def test_mock_embed_rejects_empty_text(self) -> None:
        """Should reject empty text."""
        provider = MockEmbeddings()
        with pytest.raises(ValueError):
            provider.embed("")

    def test_mock_embed_batch(self) -> None:
        """Should embed batch of texts."""
        provider = MockEmbeddings()
        texts = ["text1", "text2", "text3"]
        embeddings = provider.embed_batch(texts)
        assert len(embeddings) == 3
        assert all(isinstance(e, TaggedEmbedding) for e in embeddings)

    def test_mock_embed_batch_order(self) -> None:
        """Batch should preserve order."""
        provider = MockEmbeddings()
        texts = ["first", "second", "third"]
        embeddings = provider.embed_batch(texts)
        for i, emb in enumerate(embeddings):
            assert emb.text == texts[i]

    def test_mock_embed_batch_all_tagged(self) -> None:
        """All batch embeddings should be tagged."""
        provider = MockEmbeddings()
        embeddings = provider.embed_batch(["a", "b", "c"])
        for emb in embeddings:
            assert emb.tag.provider == "mock"
            assert emb.tag.model == "mock"

    def test_mock_embed_batch_empty(self) -> None:
        """Should handle empty batch."""
        provider = MockEmbeddings()
        embeddings = provider.embed_batch([])
        assert embeddings == []

    def test_mock_embed_batch_rejects_empty_items(self) -> None:
        """Should reject empty items in batch."""
        provider = MockEmbeddings()
        with pytest.raises(ValueError):
            provider.embed_batch(["good", "", "good"])

    def test_mock_embed_many(self) -> None:
        """Should embed many texts."""
        provider = MockEmbeddings()
        texts = [f"text{i}" for i in range(10)]
        embeddings = provider.embed_many(texts)
        assert len(embeddings) == 10

    def test_mock_embed_many_with_batching(self) -> None:
        """embed_many() should work with multiple batches."""
        provider = MockEmbeddings()
        texts = [f"text{i}" for i in range(100)]
        embeddings = provider.embed_many(texts, batch_size=10)
        assert len(embeddings) == 100

    def test_mock_hash_to_vector_deterministic(self) -> None:
        """Hash function should be deterministic."""
        vec1 = MockEmbeddings._hash_to_vector("test", 100)
        vec2 = MockEmbeddings._hash_to_vector("test", 100)
        assert vec1 == vec2

    def test_mock_hash_to_vector_different_inputs(self) -> None:
        """Different inputs should produce different vectors."""
        vec1 = MockEmbeddings._hash_to_vector("text1", 100)
        vec2 = MockEmbeddings._hash_to_vector("text2", 100)
        assert vec1 != vec2

    def test_mock_hash_to_vector_dimension(self) -> None:
        """Vector should respect dimension parameter."""
        vec = MockEmbeddings._hash_to_vector("test", 512)
        assert len(vec) == 512

    def test_mock_hash_to_vector_normalized(self) -> None:
        """Vector values should be in reasonable range."""
        vec = MockEmbeddings._hash_to_vector("test", 100)
        for val in vec:
            assert -1.0 <= val <= 1.0

    def test_mock_embed_persistence(self) -> None:
        """Vector should persist across provider calls."""
        provider = MockEmbeddings()
        emb = provider.embed("persistent")
        vec = emb.vector.copy()
        emb2 = provider.embed("persistent")
        assert emb2.vector == vec

    def test_mock_multiple_providers_independent(self) -> None:
        """Multiple MockEmbeddings instances should produce same results."""
        provider1 = MockEmbeddings()
        provider2 = MockEmbeddings()
        emb1 = provider1.embed("test")
        emb2 = provider2.embed("test")
        assert emb1.vector == emb2.vector

    def test_mock_embed_text_included(self) -> None:
        """Original text should be included in embedding."""
        provider = MockEmbeddings()
        text = "my test text"
        emb = provider.embed(text)
        assert emb.text == text

    def test_mock_batch_texts_included(self) -> None:
        """All texts should be included in batch results."""
        provider = MockEmbeddings()
        texts = ["a", "b", "c"]
        embeddings = provider.embed_batch(texts)
        for i, emb in enumerate(embeddings):
            assert emb.text == texts[i]

    def test_mock_vector_not_normalized_to_unit(self) -> None:
        """Mock vectors don't need to be unit-normalized."""
        provider = MockEmbeddings()
        emb = provider.embed("test")
        # Just verify they exist and are numeric
        assert all(isinstance(x, float) for x in emb.vector)
