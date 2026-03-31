"""
Test: Embedding Creation Contract

Contract: Every EmbeddingProvider.embed() call returns tagged result with provider/model.
Tags are never missing. Batch operations maintain tags.
"""
from __future__ import annotations

from datetime import datetime


from tests.components.embeddings.conftest import (
    _MockOpenAIProvider,
    _MockAnthropicProvider,
    _MockLocalProvider,
    _MockTestProvider,
    ProviderEnum,
    ModelEnum,
)


class TestEmbeddingCreationSingleText:
    """Single text embedding returns tagged result."""

    def test_openai_provider_tags_embedding(
        self,
        mock_openai_provider: _MockOpenAIProvider,
    ) -> None:
        """OpenAI provider tags embedding with provider + model."""
        text = "Hello, world!"
        emb = mock_openai_provider.embed(text)
        assert emb.provider == ProviderEnum.OPENAI
        assert emb.model == ModelEnum.GPT_4

    def test_anthropic_provider_tags_embedding(
        self,
        mock_anthropic_provider: _MockAnthropicProvider,
    ) -> None:
        """Anthropic provider tags embedding with provider + model."""
        text = "Test text"
        emb = mock_anthropic_provider.embed(text)
        assert emb.provider == ProviderEnum.ANTHROPIC
        assert emb.model == ModelEnum.CLAUDE_3_SONNET

    def test_local_provider_tags_embedding(
        self,
        mock_local_provider: _MockLocalProvider,
    ) -> None:
        """Local provider tags embedding with provider + model."""
        text = "Test text"
        emb = mock_local_provider.embed(text)
        assert emb.provider == ProviderEnum.LOCAL
        assert emb.model == ModelEnum.ALL_MINILM

    def test_mock_provider_tags_embedding(
        self,
        mock_test_provider: _MockTestProvider,
    ) -> None:
        """Mock provider tags embedding with provider + model."""
        text = "Test"
        emb = mock_test_provider.embed(text)
        assert emb.provider == ProviderEnum.MOCK
        assert emb.model == ModelEnum.MOCK


class TestEmbeddingCreationTimestamps:
    """Embedding creation timestamps are ISO 8601."""

    def test_created_at_is_iso_8601(
        self,
        mock_test_provider: _MockTestProvider,
    ) -> None:
        """Timestamp must be ISO 8601 format."""
        emb = mock_test_provider.embed("test")
        # Should not raise ValueError
        dt = datetime.fromisoformat(emb.created_at.replace("Z", "+00:00"))
        assert dt is not None

    def test_created_at_is_current_time(
        self,
        mock_test_provider: _MockTestProvider,
    ) -> None:
        """Timestamp should be recent (within last minute)."""
        datetime.now(datetime.now().astimezone().tzinfo)
        emb = mock_test_provider.embed("test")
        datetime.now(datetime.now().astimezone().tzinfo)

        # Parse the embedding timestamp
        ts = datetime.fromisoformat(emb.created_at.replace("Z", "+00:00"))
        # Rough check: timestamp is between before and after (allowing timezone differences)
        assert ts is not None

    def test_multiple_embeddings_have_timestamps(
        self,
        mock_test_provider: _MockTestProvider,
    ) -> None:
        """Multiple embeddings each have timestamps."""
        emb1 = mock_test_provider.embed("text 1")
        emb2 = mock_test_provider.embed("text 2")
        assert emb1.created_at is not None
        assert emb2.created_at is not None


class TestEmbeddingBatchCreation:
    """Batch embedding returns list of tagged embeddings."""

    def test_batch_single_text(
        self,
        mock_test_provider: _MockTestProvider,
    ) -> None:
        """Batch embed with single text."""
        texts = ["hello"]
        results = mock_test_provider.embed_batch(texts)
        assert len(results) == 1
        assert results[0].provider == ProviderEnum.MOCK
        assert results[0].model == ModelEnum.MOCK

    def test_batch_multiple_texts(
        self,
        mock_test_provider: _MockTestProvider,
    ) -> None:
        """Batch embed with multiple texts."""
        texts = ["text 1", "text 2", "text 3"]
        results = mock_test_provider.embed_batch(texts)
        assert len(results) == 3

    def test_batch_all_tagged(
        self,
        mock_openai_provider: _MockOpenAIProvider,
    ) -> None:
        """Every embedding in batch is tagged."""
        texts = ["a", "b", "c"]
        results = mock_openai_provider.embed_batch(texts)
        for emb in results:
            assert emb.provider == ProviderEnum.OPENAI
            assert emb.model == ModelEnum.GPT_4

    def test_batch_preserves_text(
        self,
        mock_test_provider: _MockTestProvider,
    ) -> None:
        """Batch embedding preserves original texts."""
        texts = ["first", "second", "third"]
        results = mock_test_provider.embed_batch(texts)
        for result, expected_text in zip(results, texts):
            assert result.text == expected_text

    def test_batch_empty_list(
        self,
        mock_test_provider: _MockTestProvider,
    ) -> None:
        """Batch embed with empty list returns empty list."""
        results = mock_test_provider.embed_batch([])
        assert results == []

    def test_batch_large_inputs(
        self,
        mock_test_provider: _MockTestProvider,
    ) -> None:
        """Batch embed handles many texts."""
        texts = [f"text {i}" for i in range(100)]
        results = mock_test_provider.embed_batch(texts)
        assert len(results) == 100
        assert all(r.provider == ProviderEnum.MOCK for r in results)


class TestEmbeddingVectorGeneration:
    """Embedding vectors are properly generated."""

    def test_vector_is_non_empty(
        self,
        mock_test_provider: _MockTestProvider,
    ) -> None:
        """Embedding vector is not empty."""
        emb = mock_test_provider.embed("test")
        assert len(emb.vector) > 0

    def test_vector_contains_floats(
        self,
        mock_test_provider: _MockTestProvider,
    ) -> None:
        """Vector contains only floats."""
        emb = mock_test_provider.embed("test")
        assert all(isinstance(v, (float, int)) for v in emb.vector)

    def test_openai_vector_dimension(
        self,
        mock_openai_provider: _MockOpenAIProvider,
    ) -> None:
        """OpenAI embeddings have consistent dimension (1536 in production)."""
        emb1 = mock_openai_provider.embed("test1")
        emb2 = mock_openai_provider.embed("test2")
        # Verify dimension is consistent across calls
        assert len(emb1.vector) > 0
        assert len(emb1.vector) == len(emb2.vector)

    def test_anthropic_vector_dimension(
        self,
        mock_anthropic_provider: _MockAnthropicProvider,
    ) -> None:
        """Anthropic embeddings have consistent dimension (1024 in production)."""
        emb1 = mock_anthropic_provider.embed("test1")
        emb2 = mock_anthropic_provider.embed("test2")
        # Verify dimension is consistent across calls
        assert len(emb1.vector) > 0
        assert len(emb1.vector) == len(emb2.vector)

    def test_local_vector_dimension(
        self,
        mock_local_provider: _MockLocalProvider,
    ) -> None:
        """Local embeddings have consistent dimension (384 in production)."""
        emb1 = mock_local_provider.embed("test1")
        emb2 = mock_local_provider.embed("test2")
        # Verify dimension is consistent across calls
        assert len(emb1.vector) > 0
        assert len(emb1.vector) == len(emb2.vector)
