"""Tests for LocalEmbeddings provider."""

from __future__ import annotations

import pytest

from app.components.embeddings.providers.local import LocalEmbeddings
from app.components.embeddings.schema import EmbeddingTag, TaggedEmbedding


class TestLocalEmbeddings:
    """Tests for LocalEmbeddings provider."""

    def test_local_initialization_default(self) -> None:
        """Should initialize with default model."""
        provider = LocalEmbeddings()
        assert provider is not None

    def test_local_initialization_custom(self) -> None:
        """Should initialize with custom model."""
        provider = LocalEmbeddings(model="bert-base-uncased")
        assert provider is not None

    def test_local_initialization_rejects_empty_model(self) -> None:
        """Should reject empty model name."""
        with pytest.raises(ValueError, match="model"):
            LocalEmbeddings(model="")  # type: ignore

    def test_local_tag_provider(self) -> None:
        """LocalEmbeddings should have local provider."""
        provider = LocalEmbeddings()
        assert provider.tag.provider == "local"

    def test_local_tag_model(self) -> None:
        """LocalEmbeddings should preserve model name in tag."""
        provider = LocalEmbeddings(model="bert-base")
        assert provider.tag.model == "bert-base"

    def test_local_tag_default_model(self) -> None:
        """LocalEmbeddings should use default model in tag."""
        provider = LocalEmbeddings()
        assert provider.tag.model == "all-minilm-l6-v2"

    def test_local_embed_single_text(self) -> None:
        """Should embed single text."""
        provider = LocalEmbeddings()
        emb = provider.embed("test text")
        assert isinstance(emb, TaggedEmbedding)
        assert emb.tag.provider == "local"

    def test_local_embed_text_included(self) -> None:
        """Embedded result should include original text."""
        provider = LocalEmbeddings()
        text = "my test text"
        emb = provider.embed(text)
        assert emb.text == text

    def test_local_embed_has_vector(self) -> None:
        """Embedded result should have vector."""
        provider = LocalEmbeddings()
        emb = provider.embed("test")
        assert emb.vector is not None
        assert isinstance(emb.vector, list)
        assert len(emb.vector) > 0

    def test_local_embed_rejects_empty_text(self) -> None:
        """Should reject empty text."""
        provider = LocalEmbeddings()
        with pytest.raises(ValueError):
            provider.embed("")

    def test_local_embed_batch(self) -> None:
        """Should embed batch of texts."""
        provider = LocalEmbeddings()
        texts = ["text1", "text2", "text3"]
        embeddings = provider.embed_batch(texts)
        assert len(embeddings) == 3
        assert all(isinstance(e, TaggedEmbedding) for e in embeddings)

    def test_local_embed_batch_order(self) -> None:
        """Batch should preserve order."""
        provider = LocalEmbeddings()
        texts = ["first", "second", "third"]
        embeddings = provider.embed_batch(texts)
        for i, emb in enumerate(embeddings):
            assert emb.text == texts[i]

    def test_local_embed_batch_all_tagged(self) -> None:
        """All batch embeddings should be tagged."""
        provider = LocalEmbeddings()
        embeddings = provider.embed_batch(["a", "b", "c"])
        for emb in embeddings:
            assert emb.tag.provider == "local"

    def test_local_embed_batch_empty(self) -> None:
        """Should handle empty batch."""
        provider = LocalEmbeddings()
        embeddings = provider.embed_batch([])
        assert embeddings == []

    def test_local_embed_batch_rejects_empty_items(self) -> None:
        """Should reject empty items in batch."""
        provider = LocalEmbeddings()
        with pytest.raises(ValueError):
            provider.embed_batch(["good", "", "good"])

    def test_local_embed_many(self) -> None:
        """Should embed many texts."""
        provider = LocalEmbeddings()
        texts = [f"text{i}" for i in range(10)]
        embeddings = provider.embed_many(texts)
        assert len(embeddings) == 10

    def test_local_embed_many_with_batching(self) -> None:
        """embed_many() should work with multiple batches."""
        provider = LocalEmbeddings()
        texts = [f"text{i}" for i in range(100)]
        embeddings = provider.embed_many(texts, batch_size=10)
        assert len(embeddings) == 100

    def test_local_multiple_providers_independent(self) -> None:
        """Multiple LocalEmbeddings instances should be independent."""
        provider1 = LocalEmbeddings(model="model1")
        provider2 = LocalEmbeddings(model="model2")
        assert provider1.tag.model == "model1"
        assert provider2.tag.model == "model2"

    def test_local_embed_consistent_uuid(self) -> None:
        """Same text should produce same UUID."""
        provider = LocalEmbeddings()
        emb1 = provider.embed("consistent text")
        emb2 = provider.embed("consistent text")
        assert emb1.uuid == emb2.uuid

    def test_local_embed_different_uuids(self) -> None:
        """Different texts should produce different UUIDs."""
        provider = LocalEmbeddings()
        emb1 = provider.embed("text1")
        emb2 = provider.embed("text2")
        assert emb1.uuid != emb2.uuid

    def test_local_tag_consistency(self) -> None:
        """Tag should be consistent across calls."""
        provider = LocalEmbeddings(model="custom")
        tag1 = provider.tag
        tag2 = provider.tag
        assert tag1 == tag2
        assert tag1 is tag2

    def test_local_provider_identity_readable(self) -> None:
        """Provider tag should be human-readable."""
        provider = LocalEmbeddings(model="test-model")
        tag_str = str(provider.tag)
        assert "local" in tag_str
        assert "test-model" in tag_str

    def test_local_different_models_have_different_tags(self) -> None:
        """Different models should have different tags."""
        provider1 = LocalEmbeddings(model="bert")
        provider2 = LocalEmbeddings(model="gpt2")
        assert provider1.tag != provider2.tag
