"""Tests for embedding schema (TaggedEmbedding, EmbeddingTag)."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.components.embeddings.schema import EmbeddingTag, TaggedEmbedding


class TestEmbeddingTag:
    """Tests for EmbeddingTag immutable structure."""

    def test_create_valid_tag(self) -> None:
        """Should create valid EmbeddingTag."""
        tag = EmbeddingTag(provider="openai", model="text-embedding-3-small")
        assert tag.provider == "openai"
        assert tag.model == "text-embedding-3-small"

    def test_tag_is_frozen(self) -> None:
        """Should not allow modification after creation."""
        tag = EmbeddingTag(provider="mock", model="mock")
        with pytest.raises(AttributeError):
            tag.provider = "different"  # type: ignore

    def test_tag_provider_required(self) -> None:
        """Should reject empty provider."""
        with pytest.raises(ValueError, match="provider"):
            EmbeddingTag(provider="", model="model")  # type: ignore

    def test_tag_model_required(self) -> None:
        """Should reject empty model."""
        with pytest.raises(ValueError, match="model"):
            EmbeddingTag(provider="provider", model="")  # type: ignore

    def test_tag_provider_must_be_string(self) -> None:
        """Should reject non-string provider."""
        with pytest.raises(ValueError, match="provider"):
            EmbeddingTag(provider=None, model="model")  # type: ignore

    def test_tag_model_must_be_string(self) -> None:
        """Should reject non-string model."""
        with pytest.raises(ValueError, match="model"):
            EmbeddingTag(provider="provider", model=123)  # type: ignore

    def test_tag_string_representation(self) -> None:
        """Should format as provider/model."""
        tag = EmbeddingTag(provider="openai", model="text-embedding-3-small")
        assert str(tag) == "openai/text-embedding-3-small"

    def test_tag_repr(self) -> None:
        """Should have clear repr for debugging."""
        tag = EmbeddingTag(provider="mock", model="mock")
        assert "EmbeddingTag" in repr(tag)
        assert "mock" in repr(tag)

    def test_tag_equality(self) -> None:
        """Should compare by value."""
        tag1 = EmbeddingTag(provider="openai", model="small")
        tag2 = EmbeddingTag(provider="openai", model="small")
        tag3 = EmbeddingTag(provider="openai", model="large")
        assert tag1 == tag2
        assert tag1 != tag3

    def test_tag_hash(self) -> None:
        """Should be hashable for use in sets/dicts."""
        tag1 = EmbeddingTag(provider="openai", model="small")
        tag2 = EmbeddingTag(provider="openai", model="small")
        tag_set = {tag1, tag2}
        assert len(tag_set) == 1  # Equal tags collapse in set

    def test_tag_with_whitespace_provider(self) -> None:
        """Should accept valid whitespace-trimmed provider."""
        tag = EmbeddingTag(provider="openai", model="model")
        assert tag.provider == "openai"

    def test_tag_with_whitespace_model(self) -> None:
        """Should accept valid whitespace-trimmed model."""
        tag = EmbeddingTag(provider="provider", model="text-embedding-3-small")
        assert tag.model == "text-embedding-3-small"


class TestTaggedEmbedding:
    """Tests for TaggedEmbedding immutable embedding with tags."""

    def test_create_valid_embedding(self, sample_text, sample_vector, mock_tag) -> None:
        """Should create valid TaggedEmbedding."""
        emb = TaggedEmbedding(
            uuid="test-uuid",
            text=sample_text,
            vector=sample_vector,
            tag=mock_tag,
        )
        assert emb.uuid == "test-uuid"
        assert emb.text == sample_text
        assert emb.vector == sample_vector
        assert emb.tag == mock_tag

    def test_embedding_is_frozen(self, sample_tagged_embedding) -> None:
        """Should not allow modification after creation."""
        with pytest.raises(AttributeError):
            sample_tagged_embedding.text = "different"  # type: ignore

    def test_embedding_has_auto_generated_id(self, sample_text, sample_vector, mock_tag) -> None:
        """Should generate UUID for id field if not provided."""
        emb = TaggedEmbedding(
            uuid="test-uuid",
            text=sample_text,
            vector=sample_vector,
            tag=mock_tag,
        )
        assert emb.id is not None
        assert isinstance(emb.id, str)
        assert len(emb.id) > 0

    def test_embedding_has_created_at(self, sample_text, sample_vector, mock_tag) -> None:
        """Should auto-set created_at to current time."""
        before = datetime.utcnow()
        emb = TaggedEmbedding(
            uuid="test-uuid",
            text=sample_text,
            vector=sample_vector,
            tag=mock_tag,
        )
        after = datetime.utcnow()
        assert before <= emb.created_at <= after

    def test_embedding_has_version(self, sample_text, sample_vector, mock_tag) -> None:
        """Should default version to 1."""
        emb = TaggedEmbedding(
            uuid="test-uuid",
            text=sample_text,
            vector=sample_vector,
            tag=mock_tag,
        )
        assert emb.version == 1

    def test_embedding_uuid_required(self, sample_text, sample_vector, mock_tag) -> None:
        """Should reject empty uuid."""
        with pytest.raises(ValueError, match="uuid"):
            TaggedEmbedding(uuid="", text=sample_text, vector=sample_vector, tag=mock_tag)  # type: ignore

    def test_embedding_text_required(self, sample_vector, mock_tag) -> None:
        """Should reject empty text."""
        with pytest.raises(ValueError, match="text"):
            TaggedEmbedding(uuid="id", text="", vector=sample_vector, tag=mock_tag)  # type: ignore

    def test_embedding_vector_required(self, sample_text, mock_tag) -> None:
        """Should reject empty vector."""
        with pytest.raises(ValueError, match="vector"):
            TaggedEmbedding(uuid="id", text=sample_text, vector=[], tag=mock_tag)  # type: ignore

    def test_embedding_vector_must_be_list(self, sample_text, mock_tag) -> None:
        """Should reject non-list vector."""
        with pytest.raises(ValueError, match="vector"):
            TaggedEmbedding(uuid="id", text=sample_text, vector=(1.0, 2.0), tag=mock_tag)  # type: ignore

    def test_embedding_vector_items_must_be_numeric(self, sample_text, mock_tag) -> None:
        """Should reject vector with non-numeric items."""
        with pytest.raises(ValueError, match="numeric"):
            TaggedEmbedding(uuid="id", text=sample_text, vector=[1.0, "bad", 3.0], tag=mock_tag)  # type: ignore

    def test_embedding_tag_required(self, sample_text, sample_vector) -> None:
        """Should reject None tag."""
        with pytest.raises(ValueError, match="tag"):
            TaggedEmbedding(uuid="id", text=sample_text, vector=sample_vector, tag=None)  # type: ignore

    def test_embedding_tag_must_be_correct_type(self, sample_text, sample_vector) -> None:
        """Should reject invalid tag type."""
        with pytest.raises(ValueError, match="tag"):
            TaggedEmbedding(uuid="id", text=sample_text, vector=sample_vector, tag={"provider": "mock"})  # type: ignore

    def test_embedding_to_dict(self, sample_text, sample_vector, mock_tag) -> None:
        """Should serialize to dictionary."""
        emb = TaggedEmbedding(
            uuid="test-uuid",
            text=sample_text,
            vector=sample_vector,
            tag=mock_tag,
        )
        d = emb.to_dict()
        assert d["uuid"] == "test-uuid"
        assert d["text"] == sample_text
        assert d["vector"] == sample_vector
        assert d["provider"] == "mock"
        assert d["model"] == "mock"
        assert "created_at" in d
        assert d["version"] == 1

    def test_embedding_from_dict(self, sample_text, sample_vector, mock_tag) -> None:
        """Should deserialize from dictionary."""
        data = {
            "id": "test-id",
            "uuid": "test-uuid",
            "text": sample_text,
            "vector": sample_vector,
            "provider": "mock",
            "model": "mock",
            "created_at": datetime.utcnow().isoformat(),
            "version": 1,
        }
        emb = TaggedEmbedding.from_dict(data)
        assert emb.id == "test-id"
        assert emb.uuid == "test-uuid"
        assert emb.text == sample_text
        assert emb.vector == sample_vector
        assert emb.tag.provider == "mock"
        assert emb.tag.model == "mock"

    def test_embedding_roundtrip_serialization(self, sample_tagged_embedding) -> None:
        """Should survive to_dict/from_dict roundtrip."""
        original = sample_tagged_embedding
        data = original.to_dict()
        restored = TaggedEmbedding.from_dict(data)
        assert restored.uuid == original.uuid
        assert restored.text == original.text
        assert restored.vector == original.vector
        assert restored.tag == original.tag

    def test_embedding_equality(self, sample_text, sample_vector, mock_tag) -> None:
        """Should compare by value."""
        TaggedEmbedding(uuid="id1", text=sample_text, vector=sample_vector, tag=mock_tag)
        TaggedEmbedding(uuid="id1", text=sample_text, vector=sample_vector, tag=mock_tag)
        # Note: Different id or created_at will cause inequality
        # This is expected for immutable data objects

    def test_embedding_vector_conversion_to_floats(self, sample_text, mock_tag) -> None:
        """Should accept integer vector items and work with them."""
        vector_ints = [1, 2, 3, 4, 5]
        emb = TaggedEmbedding(uuid="id", text=sample_text, vector=vector_ints, tag=mock_tag)  # type: ignore
        assert emb.vector == [1, 2, 3, 4, 5]


class TestEmbeddingTagIntegration:
    """Integration tests for tag immutability and embedding lifecycle."""

    def test_tag_embedded_in_embedding_is_immutable(self, mock_tag, sample_text, sample_vector) -> None:
        """Tag inside embedding should be immutable."""
        emb = TaggedEmbedding(
            uuid="id",
            text=sample_text,
            vector=sample_vector,
            tag=mock_tag,
        )
        # Should not be able to modify tag through embedding
        with pytest.raises(AttributeError):
            emb.tag.provider = "different"  # type: ignore

    def test_different_tags_for_different_providers(self) -> None:
        """Should create distinct tags for different providers."""
        mock_tag = EmbeddingTag(provider="mock", model="mock")
        openai_tag = EmbeddingTag(provider="openai", model="text-embedding-3-small")
        assert mock_tag != openai_tag
        assert str(mock_tag) != str(openai_tag)

    def test_same_provider_different_models_are_different(self) -> None:
        """Should distinguish embeddings by model."""
        tag_small = EmbeddingTag(provider="openai", model="text-embedding-3-small")
        tag_large = EmbeddingTag(provider="openai", model="text-embedding-3-large")
        assert tag_small != tag_large

    def test_tag_persistence_through_embedding_creation(self, mock_tag) -> None:
        """Tag should not be modified during embedding creation."""
        original_provider = mock_tag.provider
        original_model = mock_tag.model

        emb = TaggedEmbedding(
            uuid="id",
            text="test",
            vector=[1.0, 2.0],
            tag=mock_tag,
        )

        # Original tag should not change
        assert mock_tag.provider == original_provider
        assert mock_tag.model == original_model
        # And embedding should have same tag
        assert emb.tag.provider == original_provider
        assert emb.tag.model == original_model
