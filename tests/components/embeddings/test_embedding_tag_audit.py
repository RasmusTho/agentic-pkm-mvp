"""
Test: Tag Validation & Audit Contract

Contract: Embeddings can be audited by provider/model.
Tags enable observability: count by provider, count by model.
Untagged embeddings can be detected (migration helper).
"""
from __future__ import annotations

import pytest

from conftest import (
    InMemoryVectorIndex,
    EmbeddingFactory,
    ProviderEnum,
    ModelEnum,
)


class TagValidator:
    """Validates embedding tags."""

    @staticmethod
    def validate(embeddings: list) -> bool:
        """Check all embeddings have tags."""
        for emb in embeddings:
            if not emb.provider or not emb.model:
                return False
        return True

    @staticmethod
    def is_tagged(embedding) -> bool:
        """Check single embedding has tags."""
        return bool(embedding.provider and embedding.model)


class TestEmbeddingTagValidation:
    """Validate embedding tags."""

    def test_validate_single_tagged_embedding(
        self,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Validation passes for tagged embedding."""
        emb = embedding_factory.create(provider=ProviderEnum.OPENAI)
        assert TagValidator.validate([emb]) is True

    def test_validate_multiple_tagged_embeddings(
        self,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Validation passes for list of tagged embeddings."""
        embeddings = embedding_factory.create_batch(
            ["a", "b", "c"],
            provider=ProviderEnum.OPENAI,
        )
        assert TagValidator.validate(embeddings) is True

    def test_validate_empty_list(self) -> None:
        """Validation passes for empty list."""
        assert TagValidator.validate([]) is True

    def test_validate_mixed_providers(
        self,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Validation passes with mixed providers."""
        openai = embedding_factory.create(provider=ProviderEnum.OPENAI)
        local = embedding_factory.create(provider=ProviderEnum.LOCAL)
        assert TagValidator.validate([openai, local]) is True

    def test_validate_mixed_models(
        self,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Validation passes with mixed models."""
        gpt = embedding_factory.create(model=ModelEnum.GPT_4)
        claude = embedding_factory.create(model=ModelEnum.CLAUDE_3_SONNET)
        assert TagValidator.validate([gpt, claude]) is True


class TestEmbeddingProviderAudit:
    """Audit embeddings by provider."""

    def test_count_by_provider_empty_index(
        self,
        vector_index: InMemoryVectorIndex,
    ) -> None:
        """Count by provider on empty index is 0."""
        assert vector_index.count_by_provider(ProviderEnum.OPENAI) == 0

    def test_count_by_provider_single(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Count single provider."""
        emb = embedding_factory.create(provider=ProviderEnum.OPENAI)
        vector_index.add([emb])
        assert vector_index.count_by_provider(ProviderEnum.OPENAI) == 1

    def test_count_by_provider_multiple_same(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Count multiple embeddings from same provider."""
        embeddings = embedding_factory.create_batch(
            ["a", "b", "c"],
            provider=ProviderEnum.OPENAI,
        )
        vector_index.add(embeddings)
        assert vector_index.count_by_provider(ProviderEnum.OPENAI) == 3

    def test_count_by_provider_multiple_different(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Count embeddings from different providers."""
        openai = embedding_factory.create_batch(["a", "b"], provider=ProviderEnum.OPENAI)
        local = embedding_factory.create_batch(["c", "d"], provider=ProviderEnum.LOCAL)
        vector_index.add(openai + local)
        assert vector_index.count_by_provider(ProviderEnum.OPENAI) == 2
        assert vector_index.count_by_provider(ProviderEnum.LOCAL) == 2

    def test_count_nonexistent_provider(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Count nonexistent provider returns 0."""
        emb = embedding_factory.create(provider=ProviderEnum.OPENAI)
        vector_index.add([emb])
        assert vector_index.count_by_provider("nonexistent") == 0


class TestEmbeddingModelAudit:
    """Audit embeddings by model."""

    def test_count_by_provider_model_empty(
        self,
        vector_index: InMemoryVectorIndex,
    ) -> None:
        """Count by provider+model on empty index is 0."""
        count = vector_index.count_by_provider_model(
            ProviderEnum.OPENAI,
            ModelEnum.GPT_4,
        )
        assert count == 0

    def test_count_by_provider_model_single(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Count single provider+model pair."""
        emb = embedding_factory.create(
            provider=ProviderEnum.OPENAI,
            model=ModelEnum.GPT_4,
        )
        vector_index.add([emb])
        count = vector_index.count_by_provider_model(
            ProviderEnum.OPENAI,
            ModelEnum.GPT_4,
        )
        assert count == 1

    def test_count_by_provider_model_multiple(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Count multiple embeddings with same provider+model."""
        embeddings = embedding_factory.create_batch(
            ["a", "b", "c"],
            provider=ProviderEnum.OPENAI,
            model=ModelEnum.GPT_4,
        )
        vector_index.add(embeddings)
        count = vector_index.count_by_provider_model(
            ProviderEnum.OPENAI,
            ModelEnum.GPT_4,
        )
        assert count == 3

    def test_count_separates_models(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Count distinguishes between models."""
        gpt = embedding_factory.create(
            provider=ProviderEnum.OPENAI,
            model=ModelEnum.GPT_4,
        )
        claude = embedding_factory.create(
            provider=ProviderEnum.ANTHROPIC,
            model=ModelEnum.CLAUDE_3_SONNET,
        )
        vector_index.add([gpt, claude])
        gpt_count = vector_index.count_by_provider_model(
            ProviderEnum.OPENAI,
            ModelEnum.GPT_4,
        )
        claude_count = vector_index.count_by_provider_model(
            ProviderEnum.ANTHROPIC,
            ModelEnum.CLAUDE_3_SONNET,
        )
        assert gpt_count == 1
        assert claude_count == 1


class TestDetectUntaggedEmbeddings:
    """Detect untagged embeddings (migration helper)."""

    def test_find_untagged_empty_index(
        self,
        vector_index: InMemoryVectorIndex,
    ) -> None:
        """No untagged embeddings in empty index."""
        untagged = vector_index.find_untagged()
        assert untagged == []

    def test_all_tagged_embeddings_not_found(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Properly tagged embeddings not detected as untagged."""
        emb = embedding_factory.create(
            provider=ProviderEnum.OPENAI,
            model=ModelEnum.GPT_4,
        )
        vector_index.add([emb])
        untagged = vector_index.find_untagged()
        assert untagged == []

    def test_histogram_providers(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Can build provider histogram for observability."""
        openai = embedding_factory.create_batch(["a", "b"], provider=ProviderEnum.OPENAI)
        local = embedding_factory.create_batch(["c"], provider=ProviderEnum.LOCAL)
        vector_index.add(openai + local)

        openai_count = vector_index.count_by_provider(ProviderEnum.OPENAI)
        local_count = vector_index.count_by_provider(ProviderEnum.LOCAL)
        assert openai_count == 2
        assert local_count == 1

    def test_list_all_embeddings(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Can list all embeddings (audit helper)."""
        embeddings = embedding_factory.create_batch(["a", "b"])
        vector_index.add(embeddings)
        all_embs = vector_index.list_all()
        assert len(all_embs) == 2
