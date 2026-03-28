"""Abstract base class and utilities for embedding providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from app.components.embeddings.schema import EmbeddingTag, TaggedEmbedding


class EmbeddingProvider(ABC):
    """Abstract interface for embedding providers.

    Every embedding provider must:
    1. Tag embeddings with provider/model identity
    2. Support single and batch embedding
    3. Return TaggedEmbedding objects with tags intact
    4. Never strip or lose tag information

    Implementation examples:
    - OpenAIEmbeddings: calls OpenAI API, tags with 'openai' provider
    - AnthropicEmbeddings: calls Anthropic SDK, tags with 'anthropic' provider
    - LocalEmbeddings: uses local model, tags with 'local' provider
    - MockEmbeddings: returns fake embeddings for tests, tags with 'mock'
    """

    @property
    @abstractmethod
    def tag(self) -> EmbeddingTag:
        """The immutable provider/model tag applied to all embeddings."""
        pass

    @abstractmethod
    def embed(self, text: str) -> TaggedEmbedding:
        """Embed a single text string.

        Args:
            text: Text to embed (must be non-empty)

        Returns:
            TaggedEmbedding with provider/model tag intact

        Raises:
            ValueError: if text is empty
            Exception: if provider API fails
        """
        pass

    @abstractmethod
    def embed_batch(self, texts: Sequence[str]) -> list[TaggedEmbedding]:
        """Embed multiple text strings in a batch.

        Args:
            texts: List of texts to embed (may be empty)

        Returns:
            List of TaggedEmbedding objects with tags intact,
            in same order as input texts.
            Empty list if input is empty.

        Raises:
            Exception: if provider API fails
        """
        pass

    def embed_many(
        self,
        texts: Sequence[str],
        batch_size: int = 32,
    ) -> list[TaggedEmbedding]:
        """Embed texts, chunking into batches if needed.

        Args:
            texts: Texts to embed
            batch_size: Chunk size for batching (default 32)

        Returns:
            List of TaggedEmbedding objects, one per input text
        """
        if not texts:
            return []

        all_embeddings: list[TaggedEmbedding] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            embeddings = self.embed_batch(batch)
            all_embeddings.extend(embeddings)

        return all_embeddings
