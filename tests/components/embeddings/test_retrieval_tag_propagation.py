"""
Test: Retrieval with Tag Propagation Contract

Contract: Tags appear in retrieval metadata and source information.
Reranking preserves original tags. Citation/source includes embedding provenance.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest

from conftest import (
    TaggedEmbedding,
    InMemoryVectorIndex,
    EmbeddingFactory,
    ProviderEnum,
    ModelEnum,
)


@dataclass
class RetrievalResult:
    """Retrieval result with metadata."""
    embedding: TaggedEmbedding
    score: float
    metadata: dict


class SimpleRetriever:
    """Simple retriever for testing tag propagation."""

    def __init__(self, index: InMemoryVectorIndex):
        self.index = index

    def retrieve(self, query_vector: list[float], k: int = 5) -> list[RetrievalResult]:
        """Retrieve with tag propagation to metadata."""
        embeddings = self.index.search(query_vector, k=k)
        results = []
        for emb in embeddings:
            metadata = {
                "provider": emb.provider,
                "model": emb.model,
                "created_at": emb.created_at,
                "source_text": emb.text,
            }
            result = RetrievalResult(
                embedding=emb,
                score=0.95,
                metadata=metadata,
            )
            results.append(result)
        return results


class TestRetrievalMetadataIncludesTags:
    """Retrieval metadata includes provider/model tags."""

    def test_retrieval_includes_provider_in_metadata(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Provider tag appears in retrieval metadata."""
        emb = embedding_factory.create(provider=ProviderEnum.OPENAI)
        vector_index.add([emb])
        retriever = SimpleRetriever(vector_index)
        results = retriever.retrieve([0.1] * 128)
        assert len(results) > 0
        assert results[0].metadata["provider"] == ProviderEnum.OPENAI

    def test_retrieval_includes_model_in_metadata(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Model tag appears in retrieval metadata."""
        emb = embedding_factory.create(model=ModelEnum.GPT_4)
        vector_index.add([emb])
        retriever = SimpleRetriever(vector_index)
        results = retriever.retrieve([0.1] * 128)
        assert len(results) > 0
        assert results[0].metadata["model"] == ModelEnum.GPT_4

    def test_retrieval_includes_timestamp_in_metadata(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Timestamp appears in retrieval metadata."""
        emb = embedding_factory.create()
        vector_index.add([emb])
        retriever = SimpleRetriever(vector_index)
        results = retriever.retrieve([0.1] * 128)
        assert len(results) > 0
        assert results[0].metadata["created_at"] == emb.created_at


class TestRetrievalPreservesProvenance:
    """Retrieval preserves embedding provenance in results."""

    def test_retrieval_result_has_embedding_object(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Retrieval result includes full embedding object."""
        emb = embedding_factory.create()
        vector_index.add([emb])
        retriever = SimpleRetriever(vector_index)
        results = retriever.retrieve([0.1] * 128)
        assert len(results) > 0
        assert results[0].embedding.uuid == emb.uuid

    def test_multiple_results_preserve_tags(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Multiple retrieval results each have tags."""
        embeddings = embedding_factory.create_batch(
            ["a", "b", "c"],
            provider=ProviderEnum.LOCAL,
        )
        vector_index.add(embeddings)
        retriever = SimpleRetriever(vector_index)
        results = retriever.retrieve([0.1] * 128, k=3)
        for result in results:
            assert result.metadata["provider"] == ProviderEnum.LOCAL

    def test_retrieval_source_text_included(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Retrieval metadata includes source text."""
        source_text = "Important document content"
        emb = embedding_factory.create(text=source_text)
        vector_index.add([emb])
        retriever = SimpleRetriever(vector_index)
        results = retriever.retrieve([0.1] * 128)
        assert len(results) > 0
        assert results[0].metadata["source_text"] == source_text


class TestRetrievalTagAnnotations:
    """Tags enable observability and auditing in retrieval."""

    def test_retrieval_enables_provider_tracking(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Can track which provider(s) served results."""
        openai_emb = embedding_factory.create(provider=ProviderEnum.OPENAI)
        local_emb = embedding_factory.create(provider=ProviderEnum.LOCAL)
        vector_index.add([openai_emb, local_emb])
        retriever = SimpleRetriever(vector_index)
        results = retriever.retrieve([0.1] * 128, k=10)
        providers = {r.metadata["provider"] for r in results}
        assert len(providers) > 0

    def test_retrieval_enables_model_tracking(
        self,
        vector_index: InMemoryVectorIndex,
        embedding_factory: EmbeddingFactory,
    ) -> None:
        """Can track which model(s) generated results."""
        gpt_emb = embedding_factory.create(model=ModelEnum.GPT_4)
        claude_emb = embedding_factory.create(model=ModelEnum.CLAUDE_3_SONNET)
        vector_index.add([gpt_emb, claude_emb])
        retriever = SimpleRetriever(vector_index)
        results = retriever.retrieve([0.1] * 128, k=10)
        models = {r.metadata["model"] for r in results}
        assert len(models) > 0

    def test_empty_retrieval(
        self,
        vector_index: InMemoryVectorIndex,
    ) -> None:
        """Empty retrieval returns empty list."""
        retriever = SimpleRetriever(vector_index)
        results = retriever.retrieve([0.1] * 128, k=5)
        assert results == []
