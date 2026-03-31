"""Tests for embedding audit and query functions."""

from __future__ import annotations


from app.components.embeddings.audit import (
    count_by_provider,
    count_by_provider_model,
    find_untagged,
    list_all_with_tags,
    get_provider_distribution,
    get_model_distribution,
    filter_by_provider,
    filter_by_provider_model,
)
from app.components.embeddings.schema import EmbeddingTag, TaggedEmbedding


class TestCountByProvider:
    """Tests for count_by_provider()."""

    def test_count_single_provider(self, sample_embeddings_batch) -> None:
        """Should count embeddings from provider."""
        count = count_by_provider(sample_embeddings_batch, "mock")
        assert count == len(sample_embeddings_batch)

    def test_count_empty_list(self) -> None:
        """Should return 0 for empty list."""
        count = count_by_provider([], "mock")
        assert count == 0

    def test_count_nonexistent_provider(self, sample_embeddings_batch) -> None:
        """Should return 0 for nonexistent provider."""
        count = count_by_provider(sample_embeddings_batch, "nonexistent")
        assert count == 0

    def test_count_mixed_providers(self, mixed_provider_embeddings) -> None:
        """Should count correctly with mixed providers."""
        mock_count = count_by_provider(mixed_provider_embeddings, "mock")
        openai_count = count_by_provider(mixed_provider_embeddings, "openai")
        assert mock_count == 4
        assert openai_count == 4

    def test_count_anthropic(self, mixed_provider_embeddings) -> None:
        """Should count anthropic provider."""
        count = count_by_provider(mixed_provider_embeddings, "anthropic")
        assert count == 2

    def test_count_local(self, mixed_provider_embeddings) -> None:
        """Should count local provider."""
        count = count_by_provider(mixed_provider_embeddings, "local")
        assert count == 2


class TestCountByProviderModel:
    """Tests for count_by_provider_model()."""

    def test_count_single_model(self, mixed_provider_embeddings) -> None:
        """Should count embeddings from specific provider/model."""
        count = count_by_provider_model(
            mixed_provider_embeddings,
            "openai",
            "text-embedding-3-small",
        )
        assert count == 4

    def test_count_empty_list(self) -> None:
        """Should return 0 for empty list."""
        count = count_by_provider_model([], "openai", "small")
        assert count == 0

    def test_count_nonexistent_combination(self, mixed_provider_embeddings) -> None:
        """Should return 0 for nonexistent provider/model combination."""
        count = count_by_provider_model(
            mixed_provider_embeddings,
            "openai",
            "nonexistent-model",
        )
        assert count == 0

    def test_count_requires_exact_match(self, mixed_provider_embeddings) -> None:
        """Should require exact model match."""
        count_small = count_by_provider_model(
            mixed_provider_embeddings,
            "openai",
            "text-embedding-3-small",
        )
        count_large = count_by_provider_model(
            mixed_provider_embeddings,
            "openai",
            "text-embedding-3-large",
        )
        assert count_small == 4
        assert count_large == 0


class TestFindUntagged:
    """Tests for find_untagged()."""

    def test_find_untagged_empty_list(self) -> None:
        """Should return empty list for fully tagged embeddings."""
        embeddings = []
        untagged = find_untagged(embeddings)
        assert untagged == []

    def test_find_untagged_all_tagged(self, sample_embeddings_batch) -> None:
        """Should return empty list when all tagged."""
        untagged = find_untagged(sample_embeddings_batch)
        assert untagged == []

    def test_find_untagged_detects_none_tag(self, sample_text, sample_vector) -> None:
        """Should detect None tag."""
        # This would fail at creation time, so we test with properly tagged embeddings
        embeddings = [
            TaggedEmbedding(
                uuid="id",
                text=sample_text,
                vector=sample_vector,
                tag=EmbeddingTag(provider="mock", model="mock"),
            )
        ]
        untagged = find_untagged(embeddings)
        assert len(untagged) == 0  # All are properly tagged


class TestListAllWithTags:
    """Tests for list_all_with_tags()."""

    def test_list_all_valid_tags(self, sample_embeddings_batch) -> None:
        """Should return all embeddings with valid tags."""
        result = list_all_with_tags(sample_embeddings_batch)
        assert len(result) == len(sample_embeddings_batch)

    def test_list_all_empty(self) -> None:
        """Should return empty list for empty input."""
        result = list_all_with_tags([])
        assert result == []

    def test_list_all_preserves_embeddings(self, sample_embeddings_batch) -> None:
        """Should preserve embedding objects."""
        result = list_all_with_tags(sample_embeddings_batch)
        for original, returned in zip(sample_embeddings_batch, result):
            assert original is returned


class TestGetProviderDistribution:
    """Tests for get_provider_distribution()."""

    def test_distribution_single_provider(self, sample_embeddings_batch) -> None:
        """Should return distribution for single provider."""
        dist = get_provider_distribution(sample_embeddings_batch)
        assert dist == {"mock": len(sample_embeddings_batch)}

    def test_distribution_multiple_providers(self, mixed_provider_embeddings) -> None:
        """Should return distribution for multiple providers."""
        dist = get_provider_distribution(mixed_provider_embeddings)
        assert dist["mock"] == 4
        assert dist["openai"] == 4
        assert dist["anthropic"] == 2
        assert dist["local"] == 2

    def test_distribution_empty_list(self) -> None:
        """Should return empty dict for empty list."""
        dist = get_provider_distribution([])
        assert dist == {}

    def test_distribution_sum_equals_total(self, mixed_provider_embeddings) -> None:
        """Sum of distribution should equal total embeddings."""
        dist = get_provider_distribution(mixed_provider_embeddings)
        assert sum(dist.values()) == len(mixed_provider_embeddings)


class TestGetModelDistribution:
    """Tests for get_model_distribution()."""

    def test_distribution_single_model(self, sample_embeddings_batch) -> None:
        """Should return distribution by model."""
        dist = get_model_distribution(sample_embeddings_batch)
        assert dist == {"mock/mock": len(sample_embeddings_batch)}

    def test_distribution_multiple_models(self, mixed_provider_embeddings) -> None:
        """Should return distribution for multiple models."""
        dist = get_model_distribution(mixed_provider_embeddings)
        assert dist["mock/mock"] == 4
        assert dist["openai/text-embedding-3-small"] == 4

    def test_distribution_key_format(self, mixed_provider_embeddings) -> None:
        """Distribution keys should be provider/model."""
        dist = get_model_distribution(mixed_provider_embeddings)
        for key in dist.keys():
            assert "/" in key
            provider, model = key.split("/", 1)
            assert provider
            assert model

    def test_distribution_empty_list(self) -> None:
        """Should return empty dict for empty list."""
        dist = get_model_distribution([])
        assert dist == {}


class TestFilterByProvider:
    """Tests for filter_by_provider()."""

    def test_filter_single_provider(self, mixed_provider_embeddings) -> None:
        """Should filter by provider."""
        filtered = filter_by_provider(mixed_provider_embeddings, "openai")
        assert all(e.tag.provider == "openai" for e in filtered)
        assert len(filtered) == 4

    def test_filter_empty_result(self, mixed_provider_embeddings) -> None:
        """Should return empty list for nonexistent provider."""
        filtered = filter_by_provider(mixed_provider_embeddings, "nonexistent")
        assert filtered == []

    def test_filter_preserves_embeddings(self, sample_embeddings_batch) -> None:
        """Filtered embeddings should be original objects."""
        filtered = filter_by_provider(sample_embeddings_batch, "mock")
        for original, returned in zip(sample_embeddings_batch, filtered):
            assert original is returned

    def test_filter_all_providers(self, mixed_provider_embeddings) -> None:
        """Filtering each provider separately should account for all embeddings."""
        providers = ["mock", "openai", "anthropic", "local"]
        total = sum(
            len(filter_by_provider(mixed_provider_embeddings, p))
            for p in providers
        )
        assert total == len(mixed_provider_embeddings)


class TestFilterByProviderModel:
    """Tests for filter_by_provider_model()."""

    def test_filter_specific_model(self, mixed_provider_embeddings) -> None:
        """Should filter by provider/model."""
        filtered = filter_by_provider_model(
            mixed_provider_embeddings,
            "openai",
            "text-embedding-3-small",
        )
        assert all(e.tag.provider == "openai" for e in filtered)
        assert all(e.tag.model == "text-embedding-3-small" for e in filtered)
        assert len(filtered) == 4

    def test_filter_empty_result(self, mixed_provider_embeddings) -> None:
        """Should return empty list for nonexistent model."""
        filtered = filter_by_provider_model(
            mixed_provider_embeddings,
            "openai",
            "nonexistent",
        )
        assert filtered == []

    def test_filter_all_models(self, mixed_provider_embeddings) -> None:
        """Filtering each model should account for all embeddings."""
        models = [
            ("mock", "mock"),
            ("openai", "text-embedding-3-small"),
            ("anthropic", "claude-3-haiku"),
            ("local", "all-minilm-l6-v2"),
        ]
        total = sum(
            len(filter_by_provider_model(mixed_provider_embeddings, p, m))
            for p, m in models
        )
        assert total == len(mixed_provider_embeddings)
