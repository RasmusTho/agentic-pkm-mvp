"""
Test: Provider Abstraction Contract

Contract: EmbeddingProvider base class has embed(text) -> TaggedEmbedding signature.
Each provider tags with provider/model identity.
Provider changes: new embeddings tagged differently, old kept original tags.
"""
from __future__ import annotations


from tests.components.embeddings.conftest import (
    _MockOpenAIProvider,
    _MockAnthropicProvider,
    _MockLocalProvider,
    _MockTestProvider,
    ProviderEnum,
    ModelEnum,
)


class TestProviderSignature:
    """Provider has expected signature."""

    def test_openai_provider_has_embed_method(
        self,
        mock_openai_provider: _MockOpenAIProvider,
    ) -> None:
        """OpenAI provider has embed() method."""
        assert hasattr(mock_openai_provider, "embed")
        assert callable(mock_openai_provider.embed)

    def test_anthropic_provider_has_embed_method(
        self,
        mock_anthropic_provider: _MockAnthropicProvider,
    ) -> None:
        """Anthropic provider has embed() method."""
        assert hasattr(mock_anthropic_provider, "embed")
        assert callable(mock_anthropic_provider.embed)

    def test_local_provider_has_embed_method(
        self,
        mock_local_provider: _MockLocalProvider,
    ) -> None:
        """Local provider has embed() method."""
        assert hasattr(mock_local_provider, "embed")
        assert callable(mock_local_provider.embed)

    def test_provider_has_embed_batch_method(
        self,
        mock_test_provider: _MockTestProvider,
    ) -> None:
        """Provider has embed_batch() for batch operations."""
        assert hasattr(mock_test_provider, "embed_batch")
        assert callable(mock_test_provider.embed_batch)


class TestOpenAIProviderTags:
    """OpenAI provider tags with provider=openai."""

    def test_openai_tags_provider(
        self,
        mock_openai_provider: _MockOpenAIProvider,
    ) -> None:
        """OpenAI embeds tag provider as 'openai'."""
        emb = mock_openai_provider.embed("test")
        assert emb.provider == ProviderEnum.OPENAI

    def test_openai_tags_model(
        self,
        mock_openai_provider: _MockOpenAIProvider,
    ) -> None:
        """OpenAI tags model."""
        emb = mock_openai_provider.embed("test")
        assert emb.model == ModelEnum.GPT_4

    def test_openai_batch_all_tagged(
        self,
        mock_openai_provider: _MockOpenAIProvider,
    ) -> None:
        """OpenAI batch tags every embedding."""
        embeddings = mock_openai_provider.embed_batch(["a", "b", "c"])
        assert all(e.provider == ProviderEnum.OPENAI for e in embeddings)
        assert all(e.model == ModelEnum.GPT_4 for e in embeddings)


class TestAnthropicProviderTags:
    """Anthropic provider tags with provider=anthropic."""

    def test_anthropic_tags_provider(
        self,
        mock_anthropic_provider: _MockAnthropicProvider,
    ) -> None:
        """Anthropic embeds tag provider as 'anthropic'."""
        emb = mock_anthropic_provider.embed("test")
        assert emb.provider == ProviderEnum.ANTHROPIC

    def test_anthropic_tags_model(
        self,
        mock_anthropic_provider: _MockAnthropicProvider,
    ) -> None:
        """Anthropic tags model as 'claude-3-sonnet'."""
        emb = mock_anthropic_provider.embed("test")
        assert emb.model == ModelEnum.CLAUDE_3_SONNET

    def test_anthropic_batch_all_tagged(
        self,
        mock_anthropic_provider: _MockAnthropicProvider,
    ) -> None:
        """Anthropic batch tags every embedding."""
        embeddings = mock_anthropic_provider.embed_batch(["a", "b"])
        assert all(e.provider == ProviderEnum.ANTHROPIC for e in embeddings)
        assert all(e.model == ModelEnum.CLAUDE_3_SONNET for e in embeddings)


class TestLocalProviderTags:
    """Local provider tags with provider=local."""

    def test_local_tags_provider(
        self,
        mock_local_provider: _MockLocalProvider,
    ) -> None:
        """Local provider tags provider as 'local'."""
        emb = mock_local_provider.embed("test")
        assert emb.provider == ProviderEnum.LOCAL

    def test_local_tags_model(
        self,
        mock_local_provider: _MockLocalProvider,
    ) -> None:
        """Local provider tags model as 'all-minilm-l6-v2'."""
        emb = mock_local_provider.embed("test")
        assert emb.model == ModelEnum.ALL_MINILM

    def test_local_batch_all_tagged(
        self,
        mock_local_provider: _MockLocalProvider,
    ) -> None:
        """Local batch tags every embedding."""
        embeddings = mock_local_provider.embed_batch(["a", "b", "c"])
        assert all(e.provider == ProviderEnum.LOCAL for e in embeddings)
        assert all(e.model == ModelEnum.ALL_MINILM for e in embeddings)


class TestMockProviderTags:
    """Mock provider tags with provider=mock."""

    def test_mock_tags_provider(
        self,
        mock_test_provider: _MockTestProvider,
    ) -> None:
        """Mock provider tags provider as 'mock'."""
        emb = mock_test_provider.embed("test")
        assert emb.provider == ProviderEnum.MOCK

    def test_mock_tags_model(
        self,
        mock_test_provider: _MockTestProvider,
    ) -> None:
        """Mock provider tags model as 'mock'."""
        emb = mock_test_provider.embed("test")
        assert emb.model == ModelEnum.MOCK

    def test_mock_batch_all_tagged(
        self,
        mock_test_provider: _MockTestProvider,
    ) -> None:
        """Mock batch tags every embedding."""
        embeddings = mock_test_provider.embed_batch(["a", "b"])
        assert all(e.provider == ProviderEnum.MOCK for e in embeddings)


class TestProviderConsistency:
    """Tags are consistent across calls to same provider."""

    def test_openai_tags_consistent(
        self,
        mock_openai_provider: _MockOpenAIProvider,
    ) -> None:
        """OpenAI always tags same way."""
        emb1 = mock_openai_provider.embed("test1")
        emb2 = mock_openai_provider.embed("test2")
        assert emb1.provider == emb2.provider
        assert emb1.model == emb2.model

    def test_anthropic_tags_consistent(
        self,
        mock_anthropic_provider: _MockAnthropicProvider,
    ) -> None:
        """Anthropic always tags same way."""
        emb1 = mock_anthropic_provider.embed("text1")
        emb2 = mock_anthropic_provider.embed("text2")
        assert emb1.provider == emb2.provider
        assert emb1.model == emb2.model

    def test_local_tags_consistent(
        self,
        mock_local_provider: _MockLocalProvider,
    ) -> None:
        """Local always tags same way."""
        emb1 = mock_local_provider.embed("a")
        emb2 = mock_local_provider.embed("b")
        assert emb1.provider == emb2.provider
        assert emb1.model == emb2.model


class TestProviderDifferentiation:
    """Different providers produce distinguishable tags."""

    def test_providers_have_different_tags(
        self,
        mock_openai_provider: _MockOpenAIProvider,
        mock_anthropic_provider: _MockAnthropicProvider,
        mock_local_provider: _MockLocalProvider,
    ) -> None:
        """Different providers use different tags."""
        openai = mock_openai_provider.embed("test")
        anthropic = mock_anthropic_provider.embed("test")
        local = mock_local_provider.embed("test")

        assert openai.provider != anthropic.provider
        assert anthropic.provider != local.provider
        assert openai.provider != local.provider

    def test_provider_tags_enable_routing(
        self,
        mock_openai_provider: _MockOpenAIProvider,
        mock_anthropic_provider: _MockAnthropicProvider,
    ) -> None:
        """Can route based on provider tag."""
        openai = mock_openai_provider.embed("test")
        anthropic = mock_anthropic_provider.embed("test")

        openai_embeddings = [openai]
        anthropic_embeddings = [anthropic]

        openai_count = sum(1 for e in openai_embeddings if e.provider == ProviderEnum.OPENAI)
        anthropic_count = sum(1 for e in anthropic_embeddings if e.provider == ProviderEnum.ANTHROPIC)

        assert openai_count == 1
        assert anthropic_count == 1


class TestProviderAttributes:
    """Provider objects expose identity attributes."""

    def test_openai_has_provider_attribute(
        self,
        mock_openai_provider: _MockOpenAIProvider,
    ) -> None:
        """OpenAI provider object has provider attribute."""
        assert hasattr(mock_openai_provider, "provider")
        assert mock_openai_provider.provider == ProviderEnum.OPENAI

    def test_openai_has_model_attribute(
        self,
        mock_openai_provider: _MockOpenAIProvider,
    ) -> None:
        """OpenAI provider object has model attribute."""
        assert hasattr(mock_openai_provider, "model")
        assert mock_openai_provider.model == ModelEnum.GPT_4

    def test_anthropic_has_provider_attribute(
        self,
        mock_anthropic_provider: _MockAnthropicProvider,
    ) -> None:
        """Anthropic provider object has provider attribute."""
        assert hasattr(mock_anthropic_provider, "provider")
        assert mock_anthropic_provider.provider == ProviderEnum.ANTHROPIC

    def test_local_has_provider_attribute(
        self,
        mock_local_provider: _MockLocalProvider,
    ) -> None:
        """Local provider object has provider attribute."""
        assert hasattr(mock_local_provider, "provider")
        assert mock_local_provider.provider == ProviderEnum.LOCAL
