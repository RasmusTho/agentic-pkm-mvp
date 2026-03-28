"""Tests for EmbeddingProvider ABC and base behavior."""

from __future__ import annotations

from typing import Sequence

import pytest

from app.components.embeddings.base import EmbeddingProvider
from app.components.embeddings.schema import EmbeddingTag, TaggedEmbedding


class ConcreteEmbeddingProvider(EmbeddingProvider):
    """Concrete test implementation of EmbeddingProvider."""

    def __init__(self, provider: str = "test", model: str = "test-model"):
        self._tag = EmbeddingTag(provider=provider, model=model)

    @property
    def tag(self) -> EmbeddingTag:
        return self._tag

    def embed(self, text: str) -> TaggedEmbedding:
        if not text:
            raise ValueError("text cannot be empty")
        return TaggedEmbedding(
            uuid="test-uuid",
            text=text,
            vector=[0.0] * 10,
            tag=self._tag,
        )

    def embed_batch(self, texts: Sequence[str]) -> list[TaggedEmbedding]:
        if not texts:
            return []
        embeddings = []
        for text in texts:
            if not text:
                raise ValueError("text cannot be empty")
            embeddings.append(
                TaggedEmbedding(
                    uuid="test-uuid",
                    text=text,
                    vector=[0.0] * 10,
                    tag=self._tag,
                )
            )
        return embeddings


class TestEmbeddingProviderABC:
    """Tests for EmbeddingProvider abstract base class."""

    def test_provider_has_tag_property(self) -> None:
        """Provider should expose tag property."""
        provider = ConcreteEmbeddingProvider()
        assert provider.tag is not None
        assert isinstance(provider.tag, EmbeddingTag)

    def test_provider_embed_returns_tagged_embedding(self) -> None:
        """Provider.embed() should return TaggedEmbedding."""
        provider = ConcreteEmbeddingProvider()
        result = provider.embed("test text")
        assert isinstance(result, TaggedEmbedding)
        assert result.tag == provider.tag

    def test_provider_embed_rejects_empty_text(self) -> None:
        """Provider.embed() should reject empty text."""
        provider = ConcreteEmbeddingProvider()
        with pytest.raises(ValueError):
            provider.embed("")

    def test_provider_embed_batch_returns_list(self) -> None:
        """Provider.embed_batch() should return list."""
        provider = ConcreteEmbeddingProvider()
        result = provider.embed_batch(["text1", "text2"])
        assert isinstance(result, list)
        assert len(result) == 2

    def test_provider_embed_batch_empty_input(self) -> None:
        """Provider.embed_batch() should handle empty input."""
        provider = ConcreteEmbeddingProvider()
        result = provider.embed_batch([])
        assert result == []

    def test_provider_embed_batch_all_tagged(self) -> None:
        """All batch embeddings should be tagged."""
        provider = ConcreteEmbeddingProvider("custom", "custom-model")
        result = provider.embed_batch(["text1", "text2", "text3"])
        for emb in result:
            assert emb.tag.provider == "custom"
            assert emb.tag.model == "custom-model"

    def test_provider_embed_many_single_batch(self) -> None:
        """embed_many() should handle single batch."""
        provider = ConcreteEmbeddingProvider()
        texts = ["text1", "text2", "text3"]
        result = provider.embed_many(texts, batch_size=10)
        assert len(result) == 3
        assert all(isinstance(e, TaggedEmbedding) for e in result)

    def test_provider_embed_many_multiple_batches(self) -> None:
        """embed_many() should chunk into multiple batches."""
        provider = ConcreteEmbeddingProvider()
        texts = [f"text{i}" for i in range(10)]
        result = provider.embed_many(texts, batch_size=3)
        assert len(result) == 10
        assert all(isinstance(e, TaggedEmbedding) for e in result)

    def test_provider_embed_many_empty_input(self) -> None:
        """embed_many() should handle empty input."""
        provider = ConcreteEmbeddingProvider()
        result = provider.embed_many([], batch_size=10)
        assert result == []

    def test_provider_embed_many_preserves_order(self) -> None:
        """embed_many() should preserve input order."""
        provider = ConcreteEmbeddingProvider()
        texts = ["a", "b", "c", "d", "e"]
        result = provider.embed_many(texts, batch_size=2)
        for i, emb in enumerate(result):
            assert emb.text == texts[i]

    def test_provider_tag_consistency_across_calls(self) -> None:
        """Tag should be consistent across multiple calls."""
        provider = ConcreteEmbeddingProvider("openai", "text-embedding-3-small")
        tag1 = provider.tag
        tag2 = provider.tag
        assert tag1 == tag2
        assert tag1 is tag2  # Should be same object

    def test_provider_different_instances_same_tag_config(self) -> None:
        """Different provider instances with same config should have equal tags."""
        provider1 = ConcreteEmbeddingProvider("openai", "small")
        provider2 = ConcreteEmbeddingProvider("openai", "small")
        assert provider1.tag == provider2.tag

    def test_provider_different_instances_different_tags(self) -> None:
        """Different provider instances with different config should differ."""
        provider1 = ConcreteEmbeddingProvider("openai", "small")
        provider2 = ConcreteEmbeddingProvider("anthropic", "haiku")
        assert provider1.tag != provider2.tag

    def test_provider_embed_batch_preserves_order(self) -> None:
        """embed_batch() should preserve input text order."""
        provider = ConcreteEmbeddingProvider()
        texts = ["first", "second", "third"]
        result = provider.embed_batch(texts)
        assert len(result) == 3
        assert result[0].text == "first"
        assert result[1].text == "second"
        assert result[2].text == "third"

    def test_provider_embed_batch_rejects_empty_items(self) -> None:
        """embed_batch() should reject empty text items."""
        provider = ConcreteEmbeddingProvider()
        with pytest.raises(ValueError):
            provider.embed_batch(["text1", "", "text3"])

    def test_provider_batch_size_parameter(self) -> None:
        """embed_many() should respect batch_size parameter."""
        provider = ConcreteEmbeddingProvider()
        texts = [f"text{i}" for i in range(7)]
        # With batch_size=3, should make 3 batch calls
        result = provider.embed_many(texts, batch_size=3)
        assert len(result) == 7

    def test_provider_batch_size_one(self) -> None:
        """embed_many() should handle batch_size=1."""
        provider = ConcreteEmbeddingProvider()
        texts = ["a", "b", "c"]
        result = provider.embed_many(texts, batch_size=1)
        assert len(result) == 3

    def test_provider_tags_never_stripped(self) -> None:
        """Embeddings returned from provider should never have stripped tags."""
        provider = ConcreteEmbeddingProvider("test-provider", "test-model")
        emb = provider.embed("text")
        assert emb.tag is not None
        assert emb.tag.provider == "test-provider"
        assert emb.tag.model == "test-model"


class TestEmbeddingProviderTelemetry:
    """Tests for provider telemetry and observability."""

    def test_provider_identity_readable(self) -> None:
        """Provider tag should be human-readable."""
        provider = ConcreteEmbeddingProvider("openai", "text-embedding-3-small")
        tag_str = str(provider.tag)
        assert "openai" in tag_str
        assert "text-embedding-3-small" in tag_str

    def test_provider_can_be_identified_from_embedding(self) -> None:
        """Provider should be identifiable from its embeddings."""
        provider1 = ConcreteEmbeddingProvider("openai", "small")
        provider2 = ConcreteEmbeddingProvider("anthropic", "haiku")

        emb1 = provider1.embed("text")
        emb2 = provider2.embed("text")

        assert emb1.tag.provider == "openai"
        assert emb2.tag.provider == "anthropic"
        assert emb1.tag != emb2.tag
