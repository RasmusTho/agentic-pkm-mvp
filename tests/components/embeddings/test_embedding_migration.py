"""
Test: Migration & Backwards Compat Contract

Contract: Detect existing untagged embeddings.
Auto-tag during migration (provider=legacy, model=unknown).
Re-embed or retag when switching providers.
Zero data loss: all embeddings remain searchable.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from tests.components.embeddings.conftest import (
    TaggedEmbedding,
    InMemoryVectorIndex,
    EmbeddingFactory,
    ProviderEnum,
    ModelEnum,
)


class MigrationHelper:
    """Helper for embedding migration operations."""

    @staticmethod
    def detect_untagged(embeddings: list[TaggedEmbedding]) -> list[TaggedEmbedding]:
        """Find embeddings missing provider/model tags."""
        return [e for e in embeddings if not e.provider or not e.model]

    @staticmethod
    def auto_tag_legacy(embeddings: list[TaggedEmbedding]) -> list[TaggedEmbedding]:
        """Auto-tag untagged embeddings as legacy."""
        result = []
        for emb in embeddings:
            if not emb.provider or not emb.model:
                # Auto-tag as legacy with unknown provider/model
                tagged = replace(
                    emb,
                    provider="legacy",
                    model="unknown",
                )
                result.append(tagged)
            else:
                result.append(emb)
        return result

    @staticmethod
    def migrate_provider(
        embeddings: list[TaggedEmbedding],
        from_provider: str,
        to_provider: str,
    ) -> list[TaggedEmbedding]:
        """Retag embeddings when switching providers."""
        result = []
        for emb in embeddings:
            if emb.provider == from_provider:
                # Keep original, just update provider tag
                retagged = replace(emb, provider=to_provider)
                result.append(retagged)
            else:
                result.append(emb)
        return result


class TestDetectUntaggedEmbeddings:
    """Detect embeddings without tags (pre-tagging era)."""

    def test_detect_no_untagged_in_empty_list(self) -> None:
        """Empty list has no untagged embeddings."""
        untagged = MigrationHelper.detect_untagged([])
        assert untagged == []

    def test_detect_no_untagged_when_all_tagged(
        self,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Properly tagged embeddings not detected."""
        embeddings = embedding_factory.create_batch(
            ["a", "b"],
            provider=ProviderEnum.OPENAI,
        )
        untagged = MigrationHelper.detect_untagged(embeddings)
        assert untagged == []

    def test_find_single_untagged_missing_provider(self) -> None:
        """Detect embedding missing provider."""
        untagged_emb = TaggedEmbedding(
            id="test",
            uuid="uuid",
            text="text",
            vector=[0.1],
            provider="",  # Empty provider
            model=ModelEnum.GPT_4,
            created_at="2026-03-27T00:00:00+00:00",
        )
        untagged = MigrationHelper.detect_untagged([untagged_emb])
        assert len(untagged) == 1

    def test_find_single_untagged_missing_model(self) -> None:
        """Detect embedding missing model."""
        untagged_emb = TaggedEmbedding(
            id="test",
            uuid="uuid",
            text="text",
            vector=[0.1],
            provider=ProviderEnum.OPENAI,
            model="",  # Empty model
            created_at="2026-03-27T00:00:00+00:00",
        )
        untagged = MigrationHelper.detect_untagged([untagged_emb])
        assert len(untagged) == 1


class TestAutoTagLegacyEmbeddings:
    """Auto-tag untagged embeddings as legacy."""

    def test_auto_tag_empty_list(self) -> None:
        """Auto-tag empty list returns empty."""
        result = MigrationHelper.auto_tag_legacy([])
        assert result == []

    def test_auto_tag_keeps_tagged_embeddings(
        self,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Auto-tag preserves already-tagged embeddings."""
        tagged = embedding_factory.create(provider=ProviderEnum.OPENAI)
        result = MigrationHelper.auto_tag_legacy([tagged])
        assert result[0].provider == ProviderEnum.OPENAI

    def test_auto_tag_legacy_provider(self) -> None:
        """Auto-tag untagged embedding with legacy provider."""
        untagged = TaggedEmbedding(
            id="test",
            uuid="uuid",
            text="text",
            vector=[0.1],
            provider="",
            model="",
            created_at="2026-03-27T00:00:00+00:00",
        )
        result = MigrationHelper.auto_tag_legacy([untagged])
        assert result[0].provider == "legacy"

    def test_auto_tag_legacy_model(self) -> None:
        """Auto-tag untagged embedding with unknown model."""
        untagged = TaggedEmbedding(
            id="test",
            uuid="uuid",
            text="text",
            vector=[0.1],
            provider="",
            model="",
            created_at="2026-03-27T00:00:00+00:00",
        )
        result = MigrationHelper.auto_tag_legacy([untagged])
        assert result[0].model == "unknown"

    def test_auto_tag_preserves_uuid(self) -> None:
        """Auto-tag preserves UUID (for re-indexing)."""
        untagged = TaggedEmbedding(
            id="test-id",
            uuid="test-uuid",
            text="text",
            vector=[0.1],
            provider="",
            model="",
            created_at="2026-03-27T00:00:00+00:00",
        )
        result = MigrationHelper.auto_tag_legacy([untagged])
        assert result[0].uuid == "test-uuid"


class TestProviderMigration:
    """Migrate embeddings when switching providers."""

    def test_migrate_provider_empty_list(self) -> None:
        """Migrate empty list returns empty."""
        result = MigrationHelper.migrate_provider([], ProviderEnum.OPENAI, ProviderEnum.ANTHROPIC)
        assert result == []

    def test_migrate_provider_single_embedding(
        self,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Migrate single embedding."""
        emb = embedding_factory.create(provider=ProviderEnum.OPENAI)
        result = MigrationHelper.migrate_provider(
            [emb],
            ProviderEnum.OPENAI,
            ProviderEnum.ANTHROPIC,
        )
        assert result[0].provider == ProviderEnum.ANTHROPIC

    def test_migrate_keeps_other_providers(
        self,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Migration keeps embeddings from other providers."""
        openai = embedding_factory.create(provider=ProviderEnum.OPENAI)
        local = embedding_factory.create(provider=ProviderEnum.LOCAL)
        result = MigrationHelper.migrate_provider(
            [openai, local],
            ProviderEnum.OPENAI,
            ProviderEnum.ANTHROPIC,
        )
        migrated = [e for e in result if e.uuid == openai.uuid][0]
        kept = [e for e in result if e.uuid == local.uuid][0]
        assert migrated.provider == ProviderEnum.ANTHROPIC
        assert kept.provider == ProviderEnum.LOCAL

    def test_migrate_preserves_vector(
        self,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Migration preserves vector (searchability maintained)."""
        emb = embedding_factory.create(provider=ProviderEnum.OPENAI)
        original_vector = emb.vector.copy()
        result = MigrationHelper.migrate_provider(
            [emb],
            ProviderEnum.OPENAI,
            ProviderEnum.ANTHROPIC,
        )
        assert result[0].vector == original_vector

    def test_migrate_preserves_text(
        self,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Migration preserves source text."""
        text = "important content"
        emb = embedding_factory.create(text=text, provider=ProviderEnum.OPENAI)
        result = MigrationHelper.migrate_provider(
            [emb],
            ProviderEnum.OPENAI,
            ProviderEnum.ANTHROPIC,
        )
        assert result[0].text == text


class TestMigrationZeroDataLoss:
    """Migration maintains searchability and data integrity."""

    def test_migrated_embeddings_remain_indexed(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Migrated embeddings can be stored and retrieved."""
        original = embedding_factory.create(provider=ProviderEnum.OPENAI)
        migrated = MigrationHelper.migrate_provider(
            [original],
            ProviderEnum.OPENAI,
            ProviderEnum.ANTHROPIC,
        )
        vector_index.add(migrated)
        retrieved = vector_index.get(original.uuid)
        assert retrieved is not None

    def test_migrated_embeddings_searchable(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Migrated embeddings can be found by similarity."""
        original = embedding_factory.create(provider=ProviderEnum.OPENAI)
        migrated = MigrationHelper.migrate_provider(
            [original],
            ProviderEnum.OPENAI,
            ProviderEnum.ANTHROPIC,
        )
        vector_index.add(migrated)
        results = vector_index.search([0.1] * 128, k=5)
        assert len(results) > 0

    def test_legacy_auto_tagging_maintains_count(
        self,
        vector_index: InMemoryVectorIndex,
    ) -> None:
        """Auto-tagging doesn't lose any embeddings."""
        untagged = TaggedEmbedding(
            id="test",
            uuid="uuid",
            text="text",
            vector=[0.1] * 128,
            provider="",
            model="",
            created_at="2026-03-27T00:00:00+00:00",
        )
        auto_tagged = MigrationHelper.auto_tag_legacy([untagged])
        vector_index.add(auto_tagged)
        assert vector_index.count() == 1

    def test_batch_migration_no_loss(
        self,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Batch migration doesn't lose embeddings."""
        embeddings = embedding_factory.create_batch(
            ["a", "b", "c", "d", "e"],
            provider=ProviderEnum.OPENAI,
        )
        migrated = MigrationHelper.migrate_provider(
            embeddings,
            ProviderEnum.OPENAI,
            ProviderEnum.ANTHROPIC,
        )
        assert len(migrated) == len(embeddings)
