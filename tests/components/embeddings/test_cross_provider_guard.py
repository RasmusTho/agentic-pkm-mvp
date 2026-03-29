"""Tests for cross-provider comparison guards.

These tests enforce that embeddings from different providers or models
are never silently compared against each other.
"""

from __future__ import annotations

import pytest

from app.components.embeddings.schema import EmbeddingTag, TaggedEmbedding
from app.components.embeddings.validation import (
    assert_compatible_tags,
    assert_compatible_tag_with_index,
)


def _make_embedding(provider: str, model: str, uuid: str = "id") -> TaggedEmbedding:
    return TaggedEmbedding(
        uuid=uuid,
        text="some text",
        vector=[0.1, 0.2, 0.3],
        tag=EmbeddingTag(provider=provider, model=model),
    )


class TestAssertCompatibleTags:
    """Tests for assert_compatible_tags()."""

    def test_same_provider_and_model_passes(self) -> None:
        """Should accept embeddings from the same provider/model."""
        a = _make_embedding("mock", "mock", "a")
        b = _make_embedding("mock", "mock", "b")
        assert_compatible_tags(a, b)  # must not raise

    def test_different_providers_raises(self) -> None:
        """Should reject embeddings from different providers."""
        a = _make_embedding("openai", "text-embedding-3-small", "a")
        b = _make_embedding("local", "all-minilm-l6-v2", "b")
        with pytest.raises(ValueError, match="Cross-provider embedding comparison rejected"):
            assert_compatible_tags(a, b)

    def test_error_message_names_both_providers(self) -> None:
        """Error message should identify both providers for easy debugging."""
        a = _make_embedding("openai", "text-embedding-3-small", "a")
        b = _make_embedding("anthropic", "claude-3-haiku", "b")
        with pytest.raises(ValueError) as exc_info:
            assert_compatible_tags(a, b)
        msg = str(exc_info.value)
        assert "openai" in msg
        assert "anthropic" in msg

    def test_same_provider_different_model_raises(self) -> None:
        """Should reject embeddings from same provider but different model."""
        a = _make_embedding("openai", "text-embedding-3-small", "a")
        b = _make_embedding("openai", "text-embedding-3-large", "b")
        with pytest.raises(ValueError, match="Cross-model embedding comparison rejected"):
            assert_compatible_tags(a, b)

    def test_cross_model_error_names_both_models(self) -> None:
        """Cross-model error should include both model names."""
        a = _make_embedding("openai", "text-embedding-3-small", "a")
        b = _make_embedding("openai", "text-embedding-3-large", "b")
        with pytest.raises(ValueError) as exc_info:
            assert_compatible_tags(a, b)
        msg = str(exc_info.value)
        assert "text-embedding-3-small" in msg
        assert "text-embedding-3-large" in msg

    def test_rejects_non_tagged_embedding_first_arg(self) -> None:
        """Should raise TypeError if first argument is not a TaggedEmbedding."""
        b = _make_embedding("mock", "mock", "b")
        with pytest.raises(TypeError, match="Expected TaggedEmbedding"):
            assert_compatible_tags({"vector": [1.0]}, b)  # type: ignore

    def test_rejects_non_tagged_embedding_second_arg(self) -> None:
        """Should raise TypeError if second argument is not a TaggedEmbedding."""
        a = _make_embedding("mock", "mock", "a")
        with pytest.raises(TypeError, match="Expected TaggedEmbedding"):
            assert_compatible_tags(a, None)  # type: ignore

    def test_legacy_provider_compatible_with_itself(self) -> None:
        """Legacy embeddings are comparable only with other legacy embeddings."""
        a = _make_embedding("legacy", "unknown", "a")
        b = _make_embedding("legacy", "unknown", "b")
        assert_compatible_tags(a, b)  # must not raise

    def test_legacy_not_compatible_with_openai(self) -> None:
        """Legacy provider must not silently compare with modern provider."""
        a = _make_embedding("legacy", "unknown", "a")
        b = _make_embedding("openai", "text-embedding-3-small", "b")
        with pytest.raises(ValueError, match="Cross-provider"):
            assert_compatible_tags(a, b)

    def test_deterministic_compatible_with_itself(self) -> None:
        """Deterministic embeddings are compatible with themselves."""
        a = _make_embedding("deterministic", "deterministic-hash", "a")
        b = _make_embedding("deterministic", "deterministic-hash", "b")
        assert_compatible_tags(a, b)  # must not raise

    def test_symmetric_rejection(self) -> None:
        """Cross-provider rejection is symmetric: order of arguments does not matter."""
        a = _make_embedding("openai", "text-embedding-3-small", "a")
        b = _make_embedding("local", "all-minilm-l6-v2", "b")
        with pytest.raises(ValueError):
            assert_compatible_tags(a, b)
        with pytest.raises(ValueError):
            assert_compatible_tags(b, a)


class TestAssertCompatibleTagWithIndex:
    """Tests for assert_compatible_tag_with_index()."""

    def test_matching_provider_and_model_passes(self) -> None:
        """Should accept when embedding matches index identity."""
        emb = _make_embedding("openai", "text-embedding-3-small")
        assert_compatible_tag_with_index(emb, "openai", "text-embedding-3-small")

    def test_mismatched_provider_raises(self) -> None:
        """Should reject if embedding provider differs from index provider."""
        emb = _make_embedding("openai", "text-embedding-3-small")
        with pytest.raises(ValueError, match="provider"):
            assert_compatible_tag_with_index(emb, "local", "all-minilm-l6-v2")

    def test_mismatched_model_raises(self) -> None:
        """Should reject if embedding model differs from index model."""
        emb = _make_embedding("openai", "text-embedding-3-small")
        with pytest.raises(ValueError, match="model"):
            assert_compatible_tag_with_index(emb, "openai", "text-embedding-3-large")

    def test_error_identifies_mismatched_provider(self) -> None:
        """Error message should identify both the embedding and index providers."""
        emb = _make_embedding("mock", "mock")
        with pytest.raises(ValueError) as exc_info:
            assert_compatible_tag_with_index(emb, "openai", "text-embedding-3-small")
        msg = str(exc_info.value)
        assert "mock" in msg
        assert "openai" in msg

    def test_error_identifies_mismatched_model(self) -> None:
        """Error message should identify both the embedding and index models."""
        emb = _make_embedding("openai", "text-embedding-3-small")
        with pytest.raises(ValueError) as exc_info:
            assert_compatible_tag_with_index(emb, "openai", "text-embedding-3-large")
        msg = str(exc_info.value)
        assert "text-embedding-3-small" in msg
        assert "text-embedding-3-large" in msg

    def test_rejects_non_tagged_embedding(self) -> None:
        """Should raise TypeError if argument is not a TaggedEmbedding."""
        with pytest.raises(TypeError, match="Expected TaggedEmbedding"):
            assert_compatible_tag_with_index(
                {"vector": [1.0]}, "openai", "text-embedding-3-small"  # type: ignore
            )

    def test_legacy_matches_legacy_index(self) -> None:
        """Legacy embedding should match a legacy index."""
        emb = _make_embedding("legacy", "unknown")
        assert_compatible_tag_with_index(emb, "legacy", "unknown")

    def test_legacy_rejected_by_openai_index(self) -> None:
        """Legacy embedding should be rejected by a non-legacy index."""
        emb = _make_embedding("legacy", "unknown")
        with pytest.raises(ValueError, match="provider"):
            assert_compatible_tag_with_index(emb, "openai", "text-embedding-3-small")
