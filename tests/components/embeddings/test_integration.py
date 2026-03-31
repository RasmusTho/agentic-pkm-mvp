"""Integration tests for embedding tagging system."""

from __future__ import annotations


from app.components.embeddings.schema import EmbeddingTag, TaggedEmbedding
from app.components.embeddings.providers.mock import MockEmbeddings
from app.components.embeddings.providers.local import LocalEmbeddings
from app.components.embeddings.validation import validate_embedding_tags
from app.components.embeddings.audit import (
    count_by_provider,
    get_provider_distribution,
    get_model_distribution,
    filter_by_provider,
    filter_by_provider_model,
)
from app.components.embeddings.migration import (
    auto_tag_legacy,
    migrate_provider,
    count_by_provider_for_migration,
)


class TestProviderIntegration:
    """Integration tests with multiple providers."""

    def test_multiple_providers_same_text(self) -> None:
        """Same text from different providers should have different vectors."""
        mock_provider = MockEmbeddings()
        local_provider = LocalEmbeddings()

        mock_emb = mock_provider.embed("test text")
        local_emb = local_provider.embed("test text")

        # Different providers should produce different embeddings
        assert mock_emb.tag != local_emb.tag
        assert mock_emb.vector != local_emb.vector

    def test_provider_tags_distinct(self) -> None:
        """Different providers should have distinct tags."""
        mock_provider = MockEmbeddings()
        local_provider = LocalEmbeddings()

        assert mock_provider.tag.provider != local_provider.tag.provider
        assert mock_provider.tag.model != local_provider.tag.model

    def test_mixed_provider_embeddings(self) -> None:
        """Should handle embeddings from different providers together."""
        mock_provider = MockEmbeddings()
        local_provider = LocalEmbeddings(model="test-model")

        embeddings = [
            mock_provider.embed("text1"),
            mock_provider.embed("text2"),
            local_provider.embed("text3"),
            local_provider.embed("text4"),
        ]

        # Should be able to validate all
        assert validate_embedding_tags(embeddings) is True

        # Should count correctly by provider
        assert count_by_provider(embeddings, "mock") == 2
        assert count_by_provider(embeddings, "local") == 2

    def test_filter_by_provider_works(self) -> None:
        """Should be able to filter embeddings by provider."""
        mock_provider = MockEmbeddings()
        local_provider = LocalEmbeddings()

        embeddings = [
            mock_provider.embed("a"),
            mock_provider.embed("b"),
            local_provider.embed("c"),
        ]

        mock_only = filter_by_provider(embeddings, "mock")
        assert len(mock_only) == 2
        assert all(e.tag.provider == "mock" for e in mock_only)

        local_only = filter_by_provider(embeddings, "local")
        assert len(local_only) == 1
        assert all(e.tag.provider == "local" for e in local_only)

    def test_get_provider_distribution(self) -> None:
        """Should get distribution of providers."""
        mock_provider = MockEmbeddings()
        local_provider = LocalEmbeddings()

        embeddings = [
            mock_provider.embed("a"),
            mock_provider.embed("b"),
            mock_provider.embed("c"),
            local_provider.embed("d"),
        ]

        dist = get_provider_distribution(embeddings)
        assert dist["mock"] == 3
        assert dist["local"] == 1

    def test_get_model_distribution(self) -> None:
        """Should get distribution by model."""
        mock_provider = MockEmbeddings()
        local_p1 = LocalEmbeddings(model="model1")
        local_p2 = LocalEmbeddings(model="model2")

        embeddings = [
            mock_provider.embed("a"),
            local_p1.embed("b"),
            local_p1.embed("c"),
            local_p2.embed("d"),
        ]

        dist = get_model_distribution(embeddings)
        assert dist["mock/mock"] == 1
        assert dist["local/model1"] == 2
        assert dist["local/model2"] == 1


class TestMigrationIntegration:
    """Integration tests for migration workflows."""

    def test_migrate_legacy_to_new_provider(self) -> None:
        """Should migrate embeddings from legacy to new provider."""
        # Create some embeddings with legacy tag
        legacy_tag = EmbeddingTag(provider="legacy", model="unknown")
        old_embeddings = [
            TaggedEmbedding(uuid="1", text="a", vector=[0.1], tag=legacy_tag),
            TaggedEmbedding(uuid="2", text="b", vector=[0.2], tag=legacy_tag),
        ]

        # Migrate to new provider
        new_provider = MockEmbeddings()
        new_embeddings = migrate_provider(
            old_embeddings,
            from_provider="legacy",
            to_provider=new_provider.tag.provider,
            to_model=new_provider.tag.model,
        )

        # Check migration
        assert all(e.tag.provider == "mock" for e in new_embeddings)
        assert all(e.vector == orig.vector for e, orig in zip(new_embeddings, old_embeddings))

    def test_count_for_migration_planning(self) -> None:
        """Should help plan migration by counting."""
        mock_provider = MockEmbeddings()
        local_provider = LocalEmbeddings()

        embeddings = [
            mock_provider.embed(f"text{i}") for i in range(5)
        ] + [
            local_provider.embed(f"text{i}") for i in range(3)
        ]

        mock_count = count_by_provider_for_migration(embeddings, "mock")
        local_count = count_by_provider_for_migration(embeddings, "local")

        assert mock_count == 5
        assert local_count == 3

    def test_auto_tag_preserves_data(self) -> None:
        """auto_tag_legacy should preserve all data."""
        provider = MockEmbeddings()
        original_embeddings = [provider.embed(f"text{i}") for i in range(5)]

        # Auto-tag (should be no-op for already-tagged)
        tagged = auto_tag_legacy(original_embeddings)

        # Check preservation
        assert len(tagged) == len(original_embeddings)
        for orig, new in zip(original_embeddings, tagged):
            assert new.uuid == orig.uuid
            assert new.text == orig.text
            assert new.vector == orig.vector


class TestSerializationIntegration:
    """Integration tests for serialization workflows."""

    def test_roundtrip_single_embedding(self) -> None:
        """Should survive serialization roundtrip."""
        provider = MockEmbeddings()
        original = provider.embed("test text")

        serialized = original.to_dict()
        restored = TaggedEmbedding.from_dict(serialized)

        assert restored.uuid == original.uuid
        assert restored.text == original.text
        assert restored.vector == original.vector
        assert restored.tag == original.tag

    def test_roundtrip_batch_embeddings(self) -> None:
        """Should roundtrip batch of embeddings."""
        provider = MockEmbeddings()
        texts = ["text1", "text2", "text3"]
        originals = provider.embed_batch(texts)

        # Serialize and restore
        serialized_list = [e.to_dict() for e in originals]
        restored_list = [TaggedEmbedding.from_dict(d) for d in serialized_list]

        for orig, restored in zip(originals, restored_list):
            assert restored.uuid == orig.uuid
            assert restored.text == orig.text
            assert restored.tag == orig.tag

    def test_dict_contains_provider_model(self) -> None:
        """Serialized dict should have provider/model fields."""
        provider = LocalEmbeddings(model="bert")
        emb = provider.embed("test")

        d = emb.to_dict()
        assert "provider" in d
        assert "model" in d
        assert d["provider"] == "local"
        assert d["model"] == "bert"


class TestQueryAndAudit:
    """Integration tests for audit/query operations."""

    def test_complex_filtering(self) -> None:
        """Should handle complex filtering scenarios."""
        mock = MockEmbeddings()
        local1 = LocalEmbeddings(model="small")
        local2 = LocalEmbeddings(model="large")

        embeddings = [
            mock.embed("a"), mock.embed("b"),
            local1.embed("c"), local1.embed("d"),
            local2.embed("e"),
        ]

        # Filter by provider
        mock_embeddings = filter_by_provider(embeddings, "mock")
        assert len(mock_embeddings) == 2

        # Filter by provider/model
        small_local = filter_by_provider_model(embeddings, "local", "small")
        assert len(small_local) == 2
        assert all(e.tag.model == "small" for e in small_local)

        # Distribution
        dist = get_model_distribution(embeddings)
        assert len(dist) == 3  # mock, local/small, local/large

    def test_audit_consistency(self) -> None:
        """Audit operations should be consistent."""
        mock = MockEmbeddings()
        local = LocalEmbeddings()

        embeddings = [
            mock.embed(f"m{i}") for i in range(5)
        ] + [
            local.embed(f"l{i}") for i in range(3)
        ]

        # Check consistency
        total = len(embeddings)
        by_provider_total = sum(get_provider_distribution(embeddings).values())
        assert total == by_provider_total

        # Check filtered counts
        mock_count = len(filter_by_provider(embeddings, "mock"))
        local_count = len(filter_by_provider(embeddings, "local"))
        assert mock_count + local_count == total


class TestTagPreservation:
    """Integration tests ensuring tags are never stripped."""

    def test_tag_preserved_through_serialization(self) -> None:
        """Tags should survive serialization."""
        provider = MockEmbeddings()
        emb = provider.embed("test")
        original_tag = emb.tag

        serialized = emb.to_dict()
        restored = TaggedEmbedding.from_dict(serialized)

        assert restored.tag == original_tag
        assert restored.tag.provider == original_tag.provider
        assert restored.tag.model == original_tag.model

    def test_tag_preserved_through_migration(self) -> None:
        """Tags should be set correctly after migration."""
        old_tag = EmbeddingTag(provider="old", model="v1")
        emb = TaggedEmbedding(uuid="1", text="test", vector=[0.1], tag=old_tag)

        migrated_list = migrate_provider([emb], "old", "new", "v2")
        migrated = migrated_list[0]

        assert migrated.tag.provider == "new"
        assert migrated.tag.model == "v2"

    def test_tag_in_batch_operations(self) -> None:
        """Tags should be correct in batch operations."""
        provider = MockEmbeddings()
        embeddings = provider.embed_batch(["a", "b", "c"])

        for emb in embeddings:
            assert emb.tag is not None
            assert emb.tag == provider.tag
            assert emb.tag.provider == "mock"
            assert emb.tag.model == "mock"
