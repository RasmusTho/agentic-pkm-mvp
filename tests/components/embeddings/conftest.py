"""
Fixtures for EmbeddingProvider tagging tests.

Provides:
- Mock embedding clients
- In-memory vector index
- Embedding factory
- Provider stubs
"""
from __future__ import annotations

import hashlib
import uuid as uuid_module
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Protocol, Sequence

import pytest

from app.components.embeddings.providers.mock import MockEmbeddings
from app.components.embeddings.schema import EmbeddingTag as SchemaEmbeddingTag
from app.components.embeddings.schema import TaggedEmbedding as SchemaTaggedEmbedding


class ProviderEnum:
    """Embedding provider enumeration."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    LOCAL = "local"
    MOCK = "mock"


class ModelEnum:
    """Supported embedding models."""

    GPT_4 = "gpt-4-embedding"
    CLAUDE_3_SONNET = "claude-3-sonnet"
    ALL_MINILM = "all-minilm-l6-v2"
    MOCK = "mock"


@dataclass(frozen=True)
class TaggedEmbedding:
    """Embedding with provider/model provenance tags."""

    id: str
    uuid: str
    text: str
    vector: list[float]
    provider: str
    model: str
    created_at: str
    version: int = 1

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "uuid": self.uuid,
            "text": self.text,
            "vector": self.vector,
            "provider": self.provider,
            "model": self.model,
            "created_at": self.created_at,
            "version": self.version,
        }


@dataclass(frozen=True)
class EmbeddingTag:
    """Provider/model tag metadata."""

    provider: str
    model: str
    created_at: str
    version: int = 1


class MockEmbeddingProvider(Protocol):
    """Protocol for mock embedding clients."""

    provider: str
    model: str

    def embed(self, text: str) -> TaggedEmbedding:
        ...

    def embed_batch(self, texts: Sequence[str]) -> list[TaggedEmbedding]:
        ...


class _MockOpenAIProvider:
    """Mock OpenAI embedding provider."""

    provider = ProviderEnum.OPENAI
    model = ModelEnum.GPT_4

    def embed(self, text: str) -> TaggedEmbedding:
        embedding_id = str(uuid_module.uuid4())
        vector = self._deterministic_vector(text, 1536)
        return TaggedEmbedding(
            id=embedding_id,
            uuid=embedding_id,
            text=text,
            vector=vector,
            provider=self.provider,
            model=self.model,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def embed_batch(self, texts: Sequence[str]) -> list[TaggedEmbedding]:
        return [self.embed(text) for text in texts]

    @staticmethod
    def _deterministic_vector(text: str, dim: int) -> list[float]:
        hash_val = hashlib.md5(text.encode()).digest()
        return [(b / 255.0 * 2 - 1) for b in hash_val[:dim]]


class _MockAnthropicProvider:
    """Mock Anthropic embedding provider."""

    provider = ProviderEnum.ANTHROPIC
    model = ModelEnum.CLAUDE_3_SONNET

    def embed(self, text: str) -> TaggedEmbedding:
        embedding_id = str(uuid_module.uuid4())
        vector = self._deterministic_vector(text, 1024)
        return TaggedEmbedding(
            id=embedding_id,
            uuid=embedding_id,
            text=text,
            vector=vector,
            provider=self.provider,
            model=self.model,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def embed_batch(self, texts: Sequence[str]) -> list[TaggedEmbedding]:
        return [self.embed(text) for text in texts]

    @staticmethod
    def _deterministic_vector(text: str, dim: int) -> list[float]:
        hash_val = hashlib.sha256(text.encode()).digest()
        return [(b / 255.0 * 2 - 1) for b in hash_val[:dim]]


class _MockLocalProvider:
    """Mock local embedding provider."""

    provider = ProviderEnum.LOCAL
    model = ModelEnum.ALL_MINILM

    def embed(self, text: str) -> TaggedEmbedding:
        embedding_id = str(uuid_module.uuid4())
        vector = self._deterministic_vector(text, 384)
        return TaggedEmbedding(
            id=embedding_id,
            uuid=embedding_id,
            text=text,
            vector=vector,
            provider=self.provider,
            model=self.model,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def embed_batch(self, texts: Sequence[str]) -> list[TaggedEmbedding]:
        return [self.embed(text) for text in texts]

    @staticmethod
    def _deterministic_vector(text: str, dim: int) -> list[float]:
        hash_val = hashlib.sha1(text.encode()).digest()
        return [(b / 255.0 * 2 - 1) for b in hash_val[:dim]]


class _MockTestProvider:
    """Mock provider for testing."""

    provider = ProviderEnum.MOCK
    model = ModelEnum.MOCK

    def __init__(self, dim: int = 128):
        self.dim = dim

    def embed(self, text: str) -> TaggedEmbedding:
        embedding_id = str(uuid_module.uuid4())
        vector = [0.1] * self.dim
        return TaggedEmbedding(
            id=embedding_id,
            uuid=embedding_id,
            text=text,
            vector=vector,
            provider=self.provider,
            model=self.model,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def embed_batch(self, texts: Sequence[str]) -> list[TaggedEmbedding]:
        return [self.embed(text) for text in texts]


class InMemoryVectorIndex:
    """In-memory vector index for testing."""

    def __init__(self):
        self._embeddings: dict[str, TaggedEmbedding] = {}

    def add(self, embeddings: list[TaggedEmbedding]) -> None:
        for emb in embeddings:
            self._embeddings[emb.uuid] = emb

    def get(self, uuid: str) -> Optional[TaggedEmbedding]:
        return self._embeddings.get(uuid)

    def search(self, query_vector: list[float], k: int = 5) -> list[TaggedEmbedding]:
        if not self._embeddings or not query_vector:
            return []

        def cosine_similarity(a: list[float], b: list[float]) -> float:
            if not a or not b or len(a) != len(b):
                return 0.0
            dot = sum(x * y for x, y in zip(a, b))
            norm_a = sum(x * x for x in a) ** 0.5
            norm_b = sum(x * x for x in b) ** 0.5
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return dot / (norm_a * norm_b)

        scored = [(emb, cosine_similarity(query_vector, emb.vector)) for emb in self._embeddings.values()]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [emb for emb, _ in scored[:k]]

    def list_all(self) -> list[TaggedEmbedding]:
        return list(self._embeddings.values())

    def count(self) -> int:
        return len(self._embeddings)

    def count_by_provider(self, provider: str) -> int:
        return sum(1 for emb in self._embeddings.values() if emb.provider == provider)

    def count_by_provider_model(self, provider: str, model: str) -> int:
        return sum(
            1
            for emb in self._embeddings.values()
            if emb.provider == provider and emb.model == model
        )

    def find_untagged(self) -> list[TaggedEmbedding]:
        return [emb for emb in self._embeddings.values() if not emb.provider or not emb.model]


class EmbeddingFactory:
    """Factory for creating test embeddings."""

    def create(
        self,
        *,
        text: str = "test text",
        provider: str = ProviderEnum.MOCK,
        model: str = ModelEnum.MOCK,
        vector_dim: int = 128,
        uuid: str | None = None,
    ) -> TaggedEmbedding:
        embedding_id = uuid or str(uuid_module.uuid4())
        return TaggedEmbedding(
            id=embedding_id,
            uuid=embedding_id,
            text=text,
            vector=[0.1] * vector_dim,
            provider=provider,
            model=model,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def create_batch(
        self,
        texts: list[str],
        *,
        provider: str = ProviderEnum.MOCK,
        model: str = ModelEnum.MOCK,
    ) -> list[TaggedEmbedding]:
        return [self.create(text=text, provider=provider, model=model) for text in texts]


@pytest.fixture
def mock_openai_provider() -> _MockOpenAIProvider:
    return _MockOpenAIProvider()


@pytest.fixture
def mock_anthropic_provider() -> _MockAnthropicProvider:
    return _MockAnthropicProvider()


@pytest.fixture
def mock_local_provider() -> _MockLocalProvider:
    return _MockLocalProvider()


@pytest.fixture
def mock_test_provider() -> _MockTestProvider:
    return _MockTestProvider()


@pytest.fixture
def vector_index() -> InMemoryVectorIndex:
    return InMemoryVectorIndex()


@pytest.fixture
def embedding_factory() -> EmbeddingFactory:
    return EmbeddingFactory()


@pytest.fixture
def mock_tag() -> SchemaEmbeddingTag:
    return SchemaEmbeddingTag(provider="mock", model="mock")


@pytest.fixture
def openai_tag() -> SchemaEmbeddingTag:
    return SchemaEmbeddingTag(provider="openai", model="text-embedding-3-small")


@pytest.fixture
def anthropic_tag() -> SchemaEmbeddingTag:
    return SchemaEmbeddingTag(provider="anthropic", model="claude-3-haiku")


@pytest.fixture
def local_tag() -> SchemaEmbeddingTag:
    return SchemaEmbeddingTag(provider="local", model="all-minilm-l6-v2")


@pytest.fixture
def sample_vector() -> list[float]:
    return [0.1 * (i % 10) for i in range(384)]


@pytest.fixture
def sample_text() -> str:
    return "This is a sample text to embed."


@pytest.fixture
def sample_tagged_embedding(
    sample_text: str,
    sample_vector: list[float],
    mock_tag: SchemaEmbeddingTag,
) -> SchemaTaggedEmbedding:
    return SchemaTaggedEmbedding(
        uuid="test-uuid-1",
        text=sample_text,
        vector=sample_vector,
        tag=mock_tag,
    )


@pytest.fixture
def mock_embeddings_provider() -> MockEmbeddings:
    return MockEmbeddings()


@pytest.fixture
def sample_embeddings_batch(mock_embeddings_provider: MockEmbeddings) -> list[SchemaTaggedEmbedding]:
    texts = [
        "First sample text",
        "Second sample text",
        "Third sample text",
        "Fourth sample text",
        "Fifth sample text",
        "Sixth sample text",
        "Seventh sample text",
        "Eighth sample text",
        "Ninth sample text",
        "Tenth sample text",
    ]
    embeddings = mock_embeddings_provider.embed_batch(texts)
    for i, emb in enumerate(embeddings):
        object.__setattr__(emb, "uuid", f"uuid-{i}")
    return embeddings


@pytest.fixture
def mixed_provider_embeddings(
    sample_embeddings_batch: list[SchemaTaggedEmbedding],
    openai_tag: SchemaEmbeddingTag,
    anthropic_tag: SchemaEmbeddingTag,
    local_tag: SchemaEmbeddingTag,
) -> list[SchemaTaggedEmbedding]:
    embeddings: list[SchemaTaggedEmbedding] = []
    embeddings.extend(sample_embeddings_batch[:4])

    for i in range(4):
        embeddings.append(
            SchemaTaggedEmbedding(
                uuid=f"openai-uuid-{i}",
                text=f"OpenAI text {i}",
                vector=[0.1 * (i % 10) for _ in range(384)],
                tag=openai_tag,
            )
        )

    for i in range(2):
        embeddings.append(
            SchemaTaggedEmbedding(
                uuid=f"anthropic-uuid-{i}",
                text=f"Anthropic text {i}",
                vector=[0.2 * (i % 10) for _ in range(384)],
                tag=anthropic_tag,
            )
        )

    for i in range(2):
        embeddings.append(
            SchemaTaggedEmbedding(
                uuid=f"local-uuid-{i}",
                text=f"Local text {i}",
                vector=[0.3 * (i % 10) for _ in range(384)],
                tag=local_tag,
            )
        )

    return embeddings
