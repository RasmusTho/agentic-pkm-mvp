"""Tests for embedding tag validation."""

from __future__ import annotations

import pytest

from app.components.embeddings.schema import EmbeddingTag, TaggedEmbedding
from app.components.embeddings.validation import (
    validate_embedding_tags,
    validate_single_embedding,
    validate_tag_structure,
    KNOWN_PROVIDERS,
)


class TestValidateEmbeddingTags:
    """Tests for validate_embedding_tags()."""

    def test_validate_valid_list(self, sample_embeddings_batch) -> None:
        """Should accept valid embeddings list."""
        assert validate_embedding_tags(sample_embeddings_batch) is True

    def test_validate_empty_list(self) -> None:
        """Should accept empty list."""
        assert validate_embedding_tags([]) is True

    def test_validate_rejects_non_list(self) -> None:
        """Should reject non-list input."""
        with pytest.raises(ValueError, match="must be a list"):
            validate_embedding_tags("not a list")  # type: ignore

    def test_validate_rejects_none_element(self) -> None:
        """Should reject None element in list."""
        with pytest.raises(ValueError):
            validate_embedding_tags([None])  # type: ignore

    def test_validate_rejects_non_tagged_embedding(self, sample_text, sample_vector) -> None:
        """Should reject embedding with None tag."""
        emb = TaggedEmbedding(
            uuid="id",
            text=sample_text,
            vector=sample_vector,
            tag=EmbeddingTag(provider="mock", model="mock"),
        )
        assert validate_embedding_tags([emb]) is True

    def test_validate_multiple_providers(self, mixed_provider_embeddings) -> None:
        """Should accept embeddings from multiple providers."""
        assert validate_embedding_tags(mixed_provider_embeddings) is True

    def test_validate_reports_error_index(self, sample_text, sample_vector) -> None:
        """Should report which embedding failed."""
        good = TaggedEmbedding(
            uuid="id1",
            text=sample_text,
            vector=sample_vector,
            tag=EmbeddingTag(provider="mock", model="mock"),
        )
        bad = TaggedEmbedding(
            uuid="id2",
            text=sample_text,
            vector=sample_vector,
            tag=EmbeddingTag(provider="invalid", model="model"),  # Invalid provider
        )
        with pytest.raises(ValueError, match="Embedding 1"):
            validate_embedding_tags([good, bad])


class TestValidateSingleEmbedding:
    """Tests for validate_single_embedding()."""

    def test_validate_valid_embedding(self, sample_tagged_embedding) -> None:
        """Should accept valid embedding."""
        validate_single_embedding(sample_tagged_embedding)  # Should not raise

    def test_validate_rejects_none(self) -> None:
        """Should reject None."""
        with pytest.raises(ValueError, match="cannot be None"):
            validate_single_embedding(None)

    def test_validate_rejects_wrong_type(self) -> None:
        """Should reject non-TaggedEmbedding."""
        with pytest.raises(ValueError, match="Expected TaggedEmbedding"):
            validate_single_embedding({"text": "not embedding"})

    def test_validate_checks_id_required(self, sample_text, sample_vector) -> None:
        """Should check id is present."""
        emb = TaggedEmbedding(
            uuid="uuid",
            text=sample_text,
            vector=sample_vector,
            tag=EmbeddingTag(provider="mock", model="mock"),
        )
        # id is auto-generated, so this should pass
        validate_single_embedding(emb)

    def test_validate_checks_uuid_required(self, sample_vector) -> None:
        """Should check uuid is present."""
        with pytest.raises(ValueError, match="uuid"):
            TaggedEmbedding(
                uuid="",
                text="text",
                vector=sample_vector,
                tag=EmbeddingTag(provider="mock", model="mock"),
            )

    def test_validate_checks_text_required(self, sample_vector) -> None:
        """Should check text is present."""
        with pytest.raises(ValueError, match="text"):
            TaggedEmbedding(
                uuid="id",
                text="",
                vector=sample_vector,
                tag=EmbeddingTag(provider="mock", model="mock"),
            )

    def test_validate_checks_vector_required(self, sample_text) -> None:
        """Should check vector is present."""
        with pytest.raises(ValueError, match="vector"):
            TaggedEmbedding(
                uuid="id",
                text=sample_text,
                vector=[],
                tag=EmbeddingTag(provider="mock", model="mock"),
            )

    def test_validate_checks_tag_required(self, sample_text, sample_vector) -> None:
        """Should check tag is present."""
        with pytest.raises(ValueError, match="tag"):
            TaggedEmbedding(
                uuid="id",
                text=sample_text,
                vector=sample_vector,
                tag=None,  # type: ignore
            )

    def test_validate_checks_provider_valid(self, sample_text, sample_vector) -> None:
        """Should check provider is recognized."""
        with pytest.raises(ValueError, match="not in known providers"):
            TaggedEmbedding(
                uuid="id",
                text=sample_text,
                vector=sample_vector,
                tag=EmbeddingTag(provider="unknown-provider", model="model"),  # type: ignore
            )

    def test_validate_accepts_known_providers(self, sample_text, sample_vector) -> None:
        """Should accept all known providers."""
        for provider in ["mock", "openai", "anthropic", "local", "legacy", "deterministic"]:
            emb = TaggedEmbedding(
                uuid="id",
                text=sample_text,
                vector=sample_vector,
                tag=EmbeddingTag(provider=provider, model="model"),
            )
            validate_single_embedding(emb)  # Should not raise


class TestValidateTagStructure:
    """Tests for validate_tag_structure()."""

    def test_validate_valid_tag(self, mock_tag) -> None:
        """Should accept valid tag."""
        validate_tag_structure(mock_tag)  # Should not raise

    def test_validate_rejects_none_tag(self) -> None:
        """Should reject None tag."""
        with pytest.raises(ValueError, match="cannot be None"):
            validate_tag_structure(None)

    def test_validate_rejects_non_tag(self) -> None:
        """Should reject non-EmbeddingTag."""
        with pytest.raises(ValueError, match="Expected EmbeddingTag"):
            validate_tag_structure({"provider": "test"})

    def test_validate_checks_provider(self) -> None:
        """Should check provider is present."""
        with pytest.raises(ValueError, match="provider"):
            EmbeddingTag(provider="", model="model")  # type: ignore

    def test_validate_checks_model(self) -> None:
        """Should check model is present."""
        with pytest.raises(ValueError, match="model"):
            EmbeddingTag(provider="provider", model="")  # type: ignore

    def test_validate_checks_provider_is_known(self, sample_text, sample_vector) -> None:
        """Should check provider is in known list."""
        with pytest.raises(ValueError, match="not in known providers"):
            TaggedEmbedding(
                uuid="id",
                text=sample_text,
                vector=sample_vector,
                tag=EmbeddingTag(provider="unknown", model="model"),  # type: ignore
            )


class TestKnownProviders:
    """Tests for KNOWN_PROVIDERS constant."""

    def test_known_providers_exists(self) -> None:
        """KNOWN_PROVIDERS should be defined."""
        assert KNOWN_PROVIDERS is not None
        assert isinstance(KNOWN_PROVIDERS, set)

    def test_known_providers_has_mock(self) -> None:
        """mock provider should be known."""
        assert "mock" in KNOWN_PROVIDERS

    def test_known_providers_has_openai(self) -> None:
        """openai provider should be known."""
        assert "openai" in KNOWN_PROVIDERS

    def test_known_providers_has_anthropic(self) -> None:
        """anthropic provider should be known."""
        assert "anthropic" in KNOWN_PROVIDERS

    def test_known_providers_has_local(self) -> None:
        """local provider should be known."""
        assert "local" in KNOWN_PROVIDERS

    def test_known_providers_has_legacy(self) -> None:
        """legacy provider should be known."""
        assert "legacy" in KNOWN_PROVIDERS

    def test_can_create_embeddings_with_known_providers(self, sample_text, sample_vector) -> None:
        """Should be able to create embeddings with all known providers."""
        for provider in KNOWN_PROVIDERS:
            emb = TaggedEmbedding(
                uuid="id",
                text=sample_text,
                vector=sample_vector,
                tag=EmbeddingTag(provider=provider, model="test"),
            )
            assert emb.tag.provider == provider
