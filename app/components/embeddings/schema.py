"""Schema definitions for tagged embeddings.

Core data structures for embedding provenance tracking.
"""

from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class EmbeddingTag:
    """Immutable embedding provider/model identity.

    Attributes:
        provider: Provider identifier (e.g., 'openai', 'anthropic', 'local', 'mock')
        model: Model identifier (e.g., 'text-embedding-3-small', 'claude-3-haiku')
    """
    provider: str
    model: str

    def __post_init__(self) -> None:
        # Validate required fields
        if not self.provider or not isinstance(self.provider, str):
            raise ValueError(f"provider must be a non-empty string, got: {self.provider!r}")
        if not self.model or not isinstance(self.model, str):
            raise ValueError(f"model must be a non-empty string, got: {self.model!r}")

    def __str__(self) -> str:
        return f"{self.provider}/{self.model}"

    def __repr__(self) -> str:
        return f"EmbeddingTag(provider={self.provider!r}, model={self.model!r})"


@dataclass(frozen=True)
class TaggedEmbedding:
    """Immutable embedding with provenance tags.

    All fields are required (no NULLs allowed). The tag is permanent
    for the lifetime of this embedding and cannot be stripped during
    storage or retrieval.

    Attributes:
        uuid: Reference to the object being embedded
        text: Original text that was embedded
        vector: Embedding vector (normalized floats)
        tag: Provider/model identity (immutable)
        id: Unique identifier for this embedding record (auto-generated)
        created_at: Timestamp when embedding was created (auto-set)
        version: Schema version for forward compatibility (default 1)
    """
    uuid: str = field()  # Reference to embedded object
    text: str = field()
    vector: list[float] = field()
    tag: EmbeddingTag = field()
    id: str = field(default_factory=lambda: str(_uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.utcnow)
    version: int = field(default=1)

    def __post_init__(self) -> None:
        # Validate all required fields are present and non-null
        if not self.id or not isinstance(self.id, str):
            raise ValueError(f"id must be a non-empty string, got: {self.id!r}")
        if not self.uuid or not isinstance(self.uuid, str):
            raise ValueError(f"uuid must be a non-empty string, got: {self.uuid!r}")
        if not self.text or not isinstance(self.text, str):
            raise ValueError(f"text must be a non-empty string, got: {self.text!r}")
        if not isinstance(self.vector, list):
            raise ValueError(f"vector must be a list, got: {type(self.vector)}")
        if not self.vector:
            raise ValueError("vector cannot be empty")
        if not all(isinstance(x, (int, float)) for x in self.vector):
            raise ValueError("vector must contain only numeric values")
        if not isinstance(self.tag, EmbeddingTag):
            raise ValueError(f"tag must be an EmbeddingTag instance, got: {type(self.tag)}")
        if not isinstance(self.created_at, datetime):
            raise ValueError(f"created_at must be a datetime, got: {type(self.created_at)}")
        if not isinstance(self.version, int) or self.version < 1:
            raise ValueError(f"version must be a positive integer, got: {self.version!r}")

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "uuid": self.uuid,
            "text": self.text,
            "vector": self.vector,
            "provider": self.tag.provider,
            "model": self.tag.model,
            "created_at": self.created_at.isoformat(),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TaggedEmbedding:
        """Reconstruct from dictionary (e.g., from storage)."""
        return cls(
            id=data["id"],
            uuid=data["uuid"],
            text=data["text"],
            vector=data["vector"],
            tag=EmbeddingTag(
                provider=data["provider"],
                model=data["model"],
            ),
            created_at=datetime.fromisoformat(data["created_at"]),
            version=data.get("version", 1),
        )
