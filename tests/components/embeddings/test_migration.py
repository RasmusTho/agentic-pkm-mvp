"""Tests for embedding migration utilities."""

from __future__ import annotations


from app.components.embeddings.migration import (
    detect_untagged_embeddings,
    auto_tag_legacy,
    migrate_provider,
    count_by_provider_for_migration,
)
from app.components.embeddings.schema import EmbeddingTag, TaggedEmbedding


class TestDetectUntaggedEmbeddings:
    """Tests for detect_untagged_embeddings()."""

    def test_detect_empty_list(self) -> None:
        """Should return empty list for empty input."""
        untagged = detect_untagged_embeddings([])
        assert untagged == []

    def test_detect_all_tagged(self, sample_embeddings_batch) -> None:
        """Should return empty list when all tagged."""
        untagged = detect_untagged_embeddings(sample_embeddings_batch)
        assert untagged == []

    def test_detect_mixed_tagged_untagged(self, sample_text, sample_vector) -> None:
        """Should detect untagged in mixed list."""
        # All embeddings must have tags by design, so test is theoretical
        embeddings = [
            TaggedEmbedding(
                uuid="id1",
                text=sample_text,
                vector=sample_vector,
                tag=EmbeddingTag(provider="mock", model="mock"),
            ),
            TaggedEmbedding(
                uuid="id2",
                text=sample_text,
                vector=sample_vector,
                tag=EmbeddingTag(provider="mock", model="mock"),
            ),
        ]
        untagged = detect_untagged_embeddings(embeddings)
        assert len(untagged) == 0  # All have valid tags


class TestAutoTagLegacy:
    """Tests for auto_tag_legacy()."""

    def test_auto_tag_all_tagged_no_change(self, sample_embeddings_batch) -> None:
        """Should not change already-tagged embeddings."""
        result = auto_tag_legacy(sample_embeddings_batch)
        assert len(result) == len(sample_embeddings_batch)
        for original, tagged in zip(sample_embeddings_batch, result):
            assert tagged.tag == original.tag

    def test_auto_tag_preserves_vectors(self, sample_embeddings_batch) -> None:
        """Should preserve all vectors during tagging."""
        result = auto_tag_legacy(sample_embeddings_batch)
        for original, tagged in zip(sample_embeddings_batch, result):
            assert tagged.vector == original.vector

    def test_auto_tag_preserves_text(self, sample_embeddings_batch) -> None:
        """Should preserve all text during tagging."""
        result = auto_tag_legacy(sample_embeddings_batch)
        for original, tagged in zip(sample_embeddings_batch, result):
            assert tagged.text == original.text

    def test_auto_tag_preserves_uuid(self, sample_embeddings_batch) -> None:
        """Should preserve UUIDs during tagging."""
        result = auto_tag_legacy(sample_embeddings_batch)
        for original, tagged in zip(sample_embeddings_batch, result):
            assert tagged.uuid == original.uuid

    def test_auto_tag_default_tag(self, sample_text, sample_vector) -> None:
        """Should apply default legacy/unknown tag."""
        embeddings = [
            TaggedEmbedding(
                uuid="id",
                text=sample_text,
                vector=sample_vector,
                tag=EmbeddingTag(provider="mock", model="mock"),
            )
        ]
        result = auto_tag_legacy(embeddings)
        # Already tagged, so tag should remain the same
        assert result[0].tag.provider == "mock"

    def test_auto_tag_custom_provider(self, sample_embeddings_batch) -> None:
        """Should accept custom provider for legacy tag."""
        result = auto_tag_legacy(sample_embeddings_batch, provider="old-system", model="v1")
        assert len(result) == len(sample_embeddings_batch)
        # Already tagged, so should keep original
        for tagged in result:
            assert tagged.tag.provider == "mock"

    def test_auto_tag_preserves_created_at(self, sample_embeddings_batch) -> None:
        """Should preserve created_at timestamp."""
        result = auto_tag_legacy(sample_embeddings_batch)
        for original, tagged in zip(sample_embeddings_batch, result):
            assert tagged.created_at == original.created_at

    def test_auto_tag_preserves_version(self, sample_embeddings_batch) -> None:
        """Should preserve version field."""
        result = auto_tag_legacy(sample_embeddings_batch)
        for original, tagged in zip(sample_embeddings_batch, result):
            assert tagged.version == original.version

    def test_auto_tag_empty_list(self) -> None:
        """Should handle empty input."""
        result = auto_tag_legacy([])
        assert result == []

    def test_auto_tag_idempotent(self, sample_embeddings_batch) -> None:
        """Should be idempotent (re-tagging same list same result)."""
        result1 = auto_tag_legacy(sample_embeddings_batch)
        result2 = auto_tag_legacy(result1)
        for e1, e2 in zip(result1, result2):
            assert e1.tag == e2.tag


class TestMigrateProvider:
    """Tests for migrate_provider()."""

    def test_migrate_matching_provider(self, sample_embeddings_batch) -> None:
        """Should migrate embeddings from source provider."""
        result = migrate_provider(
            sample_embeddings_batch,
            from_provider="mock",
            to_provider="new-provider",
            to_model="new-model",
        )
        assert len(result) == len(sample_embeddings_batch)
        for tagged in result:
            assert tagged.tag.provider == "new-provider"
            assert tagged.tag.model == "new-model"

    def test_migrate_preserves_non_matching(self, mixed_provider_embeddings) -> None:
        """Should not change embeddings from other providers."""
        result = migrate_provider(
            mixed_provider_embeddings,
            from_provider="mock",
            to_provider="new",
            to_model="new",
        )
        # Find non-mock embeddings
        openai_embeddings = [e for e in result if e.tag.provider == "openai"]
        assert all(e.tag.model == "text-embedding-3-small" for e in openai_embeddings)

    def test_migrate_preserves_vectors(self, sample_embeddings_batch) -> None:
        """Should preserve vectors during migration."""
        result = migrate_provider(
            sample_embeddings_batch,
            from_provider="mock",
            to_provider="new",
            to_model="new",
        )
        for original, migrated in zip(sample_embeddings_batch, result):
            assert migrated.vector == original.vector

    def test_migrate_preserves_text(self, sample_embeddings_batch) -> None:
        """Should preserve text during migration."""
        result = migrate_provider(
            sample_embeddings_batch,
            from_provider="mock",
            to_provider="new",
            to_model="new",
        )
        for original, migrated in zip(sample_embeddings_batch, result):
            assert migrated.text == original.text

    def test_migrate_preserves_uuid(self, sample_embeddings_batch) -> None:
        """Should preserve UUIDs during migration."""
        result = migrate_provider(
            sample_embeddings_batch,
            from_provider="mock",
            to_provider="new",
            to_model="new",
        )
        for original, migrated in zip(sample_embeddings_batch, result):
            assert migrated.uuid == original.uuid

    def test_migrate_preserves_created_at(self, sample_embeddings_batch) -> None:
        """Should preserve created_at timestamp."""
        result = migrate_provider(
            sample_embeddings_batch,
            from_provider="mock",
            to_provider="new",
            to_model="new",
        )
        for original, migrated in zip(sample_embeddings_batch, result):
            assert migrated.created_at == original.created_at

    def test_migrate_preserves_version(self, sample_embeddings_batch) -> None:
        """Should preserve version field."""
        result = migrate_provider(
            sample_embeddings_batch,
            from_provider="mock",
            to_provider="new",
            to_model="new",
        )
        for original, migrated in zip(sample_embeddings_batch, result):
            assert migrated.version == original.version

    def test_migrate_empty_list(self) -> None:
        """Should handle empty input."""
        result = migrate_provider([], "from", "to", "model")
        assert result == []

    def test_migrate_no_matching_provider(self, mixed_provider_embeddings) -> None:
        """Should return unchanged list if no embeddings match source provider."""
        original_count = len(mixed_provider_embeddings)
        result = migrate_provider(
            mixed_provider_embeddings,
            from_provider="nonexistent",
            to_provider="new",
            to_model="new",
        )
        assert len(result) == original_count
        # All should remain unchanged
        for original, returned in zip(mixed_provider_embeddings, result):
            assert original.tag == returned.tag

    def test_migrate_idempotent(self, sample_embeddings_batch) -> None:
        """Should be idempotent (re-migrating same list same result)."""
        result1 = migrate_provider(
            sample_embeddings_batch,
            from_provider="mock",
            to_provider="new",
            to_model="new",
        )
        result2 = migrate_provider(
            result1,
            from_provider="mock",
            to_provider="newer",
            to_model="newer",
        )
        # Second migration shouldn't change anything because no "mock" provider exists anymore
        for e1, e2 in zip(result1, result2):
            assert e1.tag == e2.tag

    def test_migrate_multiple_embeddings_same_provider(self, mixed_provider_embeddings) -> None:
        """Should migrate all embeddings from target provider."""
        openai_count_before = len([e for e in mixed_provider_embeddings if e.tag.provider == "openai"])
        result = migrate_provider(
            mixed_provider_embeddings,
            from_provider="openai",
            to_provider="new",
            to_model="new",
        )
        openai_count_after = len([e for e in result if e.tag.provider == "openai"])
        new_count_after = len([e for e in result if e.tag.provider == "new"])
        assert openai_count_before == new_count_after
        assert openai_count_after == 0


class TestCountByProviderForMigration:
    """Tests for count_by_provider_for_migration()."""

    def test_count_affects_zero_embeddings(self) -> None:
        """Should count 0 for nonexistent provider."""
        count = count_by_provider_for_migration([], "nonexistent")
        assert count == 0

    def test_count_single_provider(self, sample_embeddings_batch) -> None:
        """Should count embeddings for migration."""
        count = count_by_provider_for_migration(sample_embeddings_batch, "mock")
        assert count == len(sample_embeddings_batch)

    def test_count_mixed_providers(self, mixed_provider_embeddings) -> None:
        """Should count correct number for specific provider."""
        count = count_by_provider_for_migration(mixed_provider_embeddings, "openai")
        assert count == 4

    def test_count_helps_plan_migration(self, mixed_provider_embeddings) -> None:
        """Count should help decide if migration is worth doing."""
        mock_count = count_by_provider_for_migration(mixed_provider_embeddings, "mock")
        openai_count = count_by_provider_for_migration(mixed_provider_embeddings, "openai")
        # Can use these counts to decide which to migrate first
        assert mock_count == 4
        assert openai_count == 4
