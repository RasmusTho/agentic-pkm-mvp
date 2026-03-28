"""Mock embedding provider for testing."""

from __future__ import annotations

import hashlib
from typing import Sequence

from app.components.embeddings.base import EmbeddingProvider
from app.components.embeddings.schema import EmbeddingTag, TaggedEmbedding


class MockEmbeddings(EmbeddingProvider):
    """Mock embedding provider for testing.

    Generates deterministic fake embeddings based on text hash.
    Always tags embeddings with 'mock' provider.

    Guarantees:
    - Same text always produces same embedding vector
    - All embeddings tagged with provider='mock', model='mock'
    - No network calls or external dependencies
    - Suitable for unit tests and offline testing
    """

    _TAG = EmbeddingTag(provider="mock", model="mock")
    _DIMENSION = 384  # Common embedding dimension

    @property
    def tag(self) -> EmbeddingTag:
        return self._TAG

    def embed(self, text: str) -> TaggedEmbedding:
        """Embed a single text using deterministic hashing.

        Args:
            text: Text to embed

        Returns:
            TaggedEmbedding with mock provider tag
        """
        if not text:
            raise ValueError("text cannot be empty")

        vector = self._hash_to_vector(text, self._DIMENSION)

        # Use text hash as deterministic uuid for mock provider
        import uuid as _uuid
        text_uuid = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, text))

        return TaggedEmbedding(
            uuid=text_uuid,
            text=text,
            vector=vector,
            tag=self._TAG,
        )

    def embed_batch(self, texts: Sequence[str]) -> list[TaggedEmbedding]:
        """Embed multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of TaggedEmbedding objects in same order as input
        """
        if not texts:
            return []

        embeddings = []
        import uuid as _uuid
        for text in texts:
            if not text:
                raise ValueError("text items cannot be empty")
            vector = self._hash_to_vector(text, self._DIMENSION)
            # Use text hash as deterministic uuid for mock provider
            text_uuid = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, text))
            emb = TaggedEmbedding(
                uuid=text_uuid,
                text=text,
                vector=vector,
                tag=self._TAG,
            )
            embeddings.append(emb)

        return embeddings

    @staticmethod
    def _hash_to_vector(text: str, dimension: int) -> list[float]:
        """Convert text to deterministic embedding vector via hashing.

        Args:
            text: Input text
            dimension: Vector dimension

        Returns:
            Deterministic float vector
        """
        # Hash the text to get a seed
        hash_obj = hashlib.sha256(text.encode("utf-8"))
        hash_bytes = hash_obj.digest()

        # Generate vector by chunking hash bytes
        vector = []
        for i in range(dimension):
            byte_idx = (i * 2) % len(hash_bytes)
            byte1 = hash_bytes[byte_idx]
            byte2 = hash_bytes[(byte_idx + 1) % len(hash_bytes)]
            # Combine bytes and normalize to [-1, 1] range
            combined = ((byte1 ^ byte2) - 128) / 128.0
            vector.append(combined)

        return vector
