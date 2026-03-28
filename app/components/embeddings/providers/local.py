"""Local embedding provider using in-process models."""

from __future__ import annotations

from typing import Sequence

from app.components.embeddings.base import EmbeddingProvider
from app.components.embeddings.schema import EmbeddingTag, TaggedEmbedding


class LocalEmbeddings(EmbeddingProvider):
    """Embedding provider using local models.

    Uses in-process embedding models (e.g., sentence-transformers).
    All embeddings tagged with provider='local' and configurable model.

    Guarantees:
    - No network calls required
    - Model runs in-process
    - All embeddings tagged with provider='local'
    - Suitable for offline/self-hosted setups
    """

    def __init__(self, model: str = "all-minilm-l6-v2") -> None:
        """Initialize local embeddings provider.

        Args:
            model: Model identifier (default 'all-minilm-l6-v2')
        """
        if not model:
            raise ValueError("model cannot be empty")
        self._model = model
        self._tag = EmbeddingTag(provider="local", model=model)

    @property
    def tag(self) -> EmbeddingTag:
        return self._tag

    def embed(self, text: str) -> TaggedEmbedding:
        """Embed a single text using local model.

        Args:
            text: Text to embed

        Returns:
            TaggedEmbedding with local provider tag

        Raises:
            ValueError: if text is empty
            Exception: if model loading/execution fails
        """
        if not text:
            raise ValueError("text cannot be empty")

        # TODO: Integrate with actual local embedding model
        # For now, return placeholder vector
        vector = [0.0] * 384  # Placeholder dimension

        # Use text hash as deterministic uuid
        import uuid as _uuid
        text_uuid = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, text))

        return TaggedEmbedding(
            uuid=text_uuid,
            text=text,
            vector=vector,
            tag=self._tag,
        )

    def embed_batch(self, texts: Sequence[str]) -> list[TaggedEmbedding]:
        """Embed multiple texts using local model.

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
            # TODO: Batch process using actual local model
            vector = [0.0] * 384  # Placeholder dimension
            # Use text hash as deterministic uuid
            text_uuid = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, text))
            emb = TaggedEmbedding(
                uuid=text_uuid,
                text=text,
                vector=vector,
                tag=self._tag,
            )
            embeddings.append(emb)

        return embeddings
