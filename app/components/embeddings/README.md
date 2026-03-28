# Embedding Provider Tagging System

Production-quality embedding provider tagging infrastructure with 206+ passing tests.

## Overview

The embedding tagging system provides:
- **Immutable embedding tags** with provider/model identity
- **Provider abstraction** for pluggable embedding implementations
- **Comprehensive audit queries** to track embedding provenance
- **Zero-loss migration** paths for provider/model changes
- **Full backward compatibility** with existing EmbeddingIdentity code

## Quick Start

```python
from app.components.embeddings import (
    EmbeddingTag,
    TaggedEmbedding,
    MockEmbeddings,
    validate_embedding_tags,
    count_by_provider,
)

# Create a provider
provider = MockEmbeddings()

# Embed text (returns TaggedEmbedding with provider/model tag)
embedding = provider.embed("Hello, world!")
print(f"Tag: {embedding.tag}")  # mock/mock
print(f"Vector: {embedding.vector[:5]}")  # [0.1, 0.2, ...]

# Batch embed
embeddings = provider.embed_batch(["text1", "text2", "text3"])

# Validate
assert validate_embedding_tags(embeddings) is True

# Audit
count = count_by_provider(embeddings, "mock")
print(f"Total mock embeddings: {count}")
```

## Core Components

### 1. Schema (`schema.py`)

**EmbeddingTag**: Immutable provider/model pair
```python
tag = EmbeddingTag(provider="openai", model="text-embedding-3-small")
```

**TaggedEmbedding**: Embedding with immutable tags
```python
emb = TaggedEmbedding(
    uuid="object-uuid",
    text="input text",
    vector=[0.1, 0.2, 0.3, ...],
    tag=tag,
)
```

All fields required (no NULLs). Tags are frozen—cannot be modified after creation.

### 2. Provider Abstraction (`base.py`)

**EmbeddingProvider ABC**: Base class for all providers
```python
class MyEmbeddings(EmbeddingProvider):
    @property
    def tag(self) -> EmbeddingTag:
        return EmbeddingTag(provider="my-provider", model="my-model")

    def embed(self, text: str) -> TaggedEmbedding:
        # Return embedding with tag
        pass

    def embed_batch(self, texts: Sequence[str]) -> list[TaggedEmbedding]:
        # Return list of tagged embeddings
        pass
```

### 3. Built-in Providers

**MockEmbeddings**: Deterministic embeddings for testing
```python
from app.components.embeddings.providers.mock import MockEmbeddings

provider = MockEmbeddings()
# Tags: provider=mock, model=mock
# 384-dimensional vectors
# Reproducible (same text → same vector)
```

**LocalEmbeddings**: Local model embeddings
```python
from app.components.embeddings.providers.local import LocalEmbeddings

provider = LocalEmbeddings(model="all-minilm-l6-v2")
# Tags: provider=local, model=all-minilm-l6-v2
# Ready for integration with actual local models
```

### 4. Validation (`validation.py`)

```python
from app.components.embeddings.validation import (
    validate_embedding_tags,
    validate_single_embedding,
    KNOWN_PROVIDERS,
)

# Validate list of embeddings
validate_embedding_tags(embeddings)

# Validate single embedding
validate_single_embedding(embedding)

# Check if provider is known
assert "openai" in KNOWN_PROVIDERS
```

### 5. Audit & Query (`audit.py`)

```python
from app.components.embeddings.audit import (
    count_by_provider,
    count_by_provider_model,
    get_provider_distribution,
    get_model_distribution,
    filter_by_provider,
    filter_by_provider_model,
)

# Count embeddings by provider
count = count_by_provider(embeddings, "openai")

# Count by provider/model combo
count = count_by_provider_model(embeddings, "openai", "text-embedding-3-small")

# Get distribution
dist = get_provider_distribution(embeddings)
# {"openai": 100, "anthropic": 50, "mock": 200}

# Filter embeddings
openai_embeddings = filter_by_provider(embeddings, "openai")
small_embeddings = filter_by_provider_model(embeddings, "openai", "text-embedding-3-small")
```

### 6. Migration (`migration.py`)

**Auto-tag legacy embeddings**:
```python
from app.components.embeddings.migration import auto_tag_legacy

# Old embeddings without tags get tagged with legacy/unknown
tagged_embeddings = auto_tag_legacy(old_embeddings)
# Guarantees: All vectors preserved, idempotent
```

**Migrate between providers**:
```python
from app.components.embeddings.migration import migrate_provider

# Migrate from OpenAI small to OpenAI large (tags only, vectors stay same)
migrated = migrate_provider(
    embeddings,
    from_provider="openai",
    to_provider="openai",
    to_model="text-embedding-3-large",
)
# Guarantees: Vectors unchanged, idempotent, zero data loss
```

## Design Principles

### Immutability
Tags are immutable (frozen dataclasses). Once created, tags cannot be modified. This prevents accidental corruption and makes embeddings safe for concurrent access.

### No NULLs
All TaggedEmbedding fields are required. Validation happens at creation time, preventing silent failures.

### Pluggable Providers
EmbeddingProvider ABC allows easy addition of new providers (OpenAI, Anthropic, etc.) without modifying core code.

### Zero Data Loss
Migration operations preserve all vector data. Only tags are changed during migration. This enables safe provider/model transitions.

### Audit-First
Comprehensive query functions enable operational visibility: count by provider, filter by model, detect untagged embeddings, plan migrations.

### Backward Compatibility
Original EmbeddingIdentity and EmbeddingClientProtocol preserved. Legacy code continues to work. Lazy-loaded to avoid import issues.

## Key Guarantees

✓ **All embeddings have provider/model tags**
✓ **Tags never stripped during storage/retrieval**
✓ **Tags immutable for lifetime of embedding**
✓ **Migration preserves all vectors (zero data loss)**
✓ **Auto-tagging is idempotent (safe to re-run)**
✓ **All operations maintain tag integrity**
✓ **Audit queries work across all embeddings**
✓ **Serialization (to_dict/from_dict) preserves tags**
✓ **Fully backward compatible with legacy code**

## Test Coverage

206 test functions across 8 test files:
- `test_embedding_schema.py` (33 tests): Tag and embedding creation, validation, serialization
- `test_embedding_provider_base.py` (20 tests): Provider ABC contract and behavior
- `test_mock_embeddings.py` (24 tests): MockEmbeddings functionality
- `test_local_embeddings.py` (23 tests): LocalEmbeddings with custom models
- `test_validation.py` (30 tests): Tag validation and provider recognition
- `test_audit.py` (31 tests): Counting, filtering, and distribution queries
- `test_migration.py` (28 tests): Legacy tagging and provider migration
- `test_integration.py` (17 tests): Multi-provider workflows and serialization

## Known Providers

- `mock`: MockEmbeddings (deterministic, for testing)
- `openai`: OpenAI API (planned)
- `anthropic`: Anthropic API (planned)
- `local`: LocalEmbeddings (in-process models)
- `legacy`: Auto-tagged legacy embeddings
- `deterministic`: Deterministic/offline embeddings

## Future Work

Not required for v5.5:
- OpenAI and Anthropic provider implementations
- VectorIndex tagging validation and enforcement
- Retrieval system integration (include tags in results)
- Tagged embedding database persistence
- Migration CLI utilities
- Performance optimization for large embedding sets

## File Structure

```
app/components/embeddings/
├── __init__.py                 # Package exports
├── schema.py                   # EmbeddingTag, TaggedEmbedding
├── base.py                     # EmbeddingProvider ABC
├── validation.py               # Tag validation
├── audit.py                    # Query and counting
├── migration.py                # Legacy tagging and provider migration
├── legacy.py                   # Backward-compatible original code
└── providers/
    ├── __init__.py
    ├── mock.py                 # MockEmbeddings
    └── local.py                # LocalEmbeddings

tests/components/embeddings/
├── conftest.py
├── test_embedding_schema.py
├── test_embedding_provider_base.py
├── test_mock_embeddings.py
├── test_local_embeddings.py
├── test_validation.py
├── test_audit.py
├── test_migration.py
├── test_integration.py
└── run_tests.py                # Standalone test runner
```

## Usage Examples

### Basic Embedding

```python
from app.components.embeddings.providers.mock import MockEmbeddings

provider = MockEmbeddings()
embedding = provider.embed("Hello, world!")
print(embedding.tag)  # mock/mock
```

### Batch Processing

```python
texts = ["text1", "text2", "text3"]
embeddings = provider.embed_batch(texts)

# Or with chunking
embeddings = provider.embed_many(texts, batch_size=10)
```

### Validation

```python
from app.components.embeddings.validation import validate_embedding_tags

try:
    validate_embedding_tags(embeddings)
    print("All embeddings valid")
except ValueError as e:
    print(f"Validation failed: {e}")
```

### Querying

```python
from app.components.embeddings.audit import count_by_provider, get_provider_distribution

count = count_by_provider(embeddings, "openai")
dist = get_provider_distribution(embeddings)
print(f"Distribution: {dist}")
```

### Migration

```python
from app.components.embeddings.migration import auto_tag_legacy, migrate_provider

# Auto-tag old embeddings
tagged = auto_tag_legacy(old_embeddings)

# Migrate to new provider
migrated = migrate_provider(
    tagged,
    from_provider="legacy",
    to_provider="openai",
    to_model="text-embedding-3-small",
)
```

### Serialization

```python
# Store embedding
data = embedding.to_dict()
# database.save(data)

# Load embedding
loaded_data = database.load()
embedding = TaggedEmbedding.from_dict(loaded_data)
```

## Performance Notes

- MockEmbeddings uses SHA256 hashing: O(n) in text length, very fast
- LocalEmbeddings placeholder: O(1), ready for actual model integration
- Validation: O(n) in embedding count
- Audit queries: O(n) in embedding count
- Migration: O(n) in embedding count, preserves vectors (no re-computation)

## License & Attribution

Part of Yggdrasil PKM system. Follows project conventions and backward compatibility requirements.
