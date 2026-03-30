"""Standalone test runner for embedding tests (bypasses pytest conftest issues)."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from app.components.embeddings.schema import EmbeddingTag, TaggedEmbedding
from app.components.embeddings.providers.mock import MockEmbeddings
from app.components.embeddings.validation import validate_embedding_tags, validate_single_embedding, KNOWN_PROVIDERS
from app.components.embeddings.audit import count_by_provider, count_by_provider_model
from app.components.embeddings.migration import auto_tag_legacy, migrate_provider

# Test counter
passed = 0
failed = 0
errors = []


def test(name, fn):
    global passed, failed, errors
    try:
        fn()
        passed += 1
        print(f"✓ {name}")
    except AssertionError as e:
        failed += 1
        errors.append((name, str(e)))
        print(f"✗ {name}: {e}")
    except Exception as e:
        failed += 1
        errors.append((name, f"{type(e).__name__}: {str(e)}"))
        print(f"✗ {name}: {type(e).__name__}: {e}")


# ==============================================================================
# EmbeddingTag Tests
# ==============================================================================

print("\n=== EmbeddingTag Tests ===")


def test_tag_create():
    tag = EmbeddingTag(provider="openai", model="text-embedding-3-small")
    assert tag.provider == "openai"
    assert tag.model == "text-embedding-3-small"


def test_tag_frozen():
    tag = EmbeddingTag(provider="mock", model="mock")
    try:
        tag.provider = "different"  # type: ignore
        assert False, "Should not be able to modify frozen dataclass"
    except AttributeError:
        pass


def test_tag_str():
    tag = EmbeddingTag(provider="openai", model="small")
    assert str(tag) == "openai/small"


def test_tag_equality():
    tag1 = EmbeddingTag(provider="openai", model="small")
    tag2 = EmbeddingTag(provider="openai", model="small")
    assert tag1 == tag2


def test_tag_hash():
    tag1 = EmbeddingTag(provider="openai", model="small")
    tag2 = EmbeddingTag(provider="openai", model="small")
    tag_set = {tag1, tag2}
    assert len(tag_set) == 1


test("EmbeddingTag: create valid tag", test_tag_create)
test("EmbeddingTag: is frozen", test_tag_frozen)
test("EmbeddingTag: string representation", test_tag_str)
test("EmbeddingTag: equality", test_tag_equality)
test("EmbeddingTag: hashable", test_tag_hash)

# ==============================================================================
# TaggedEmbedding Tests
# ==============================================================================

print("\n=== TaggedEmbedding Tests ===")


def test_emb_create():
    tag = EmbeddingTag(provider="mock", model="mock")
    emb = TaggedEmbedding(
        uuid="test-uuid",
        text="test text",
        vector=[0.1, 0.2, 0.3],
        tag=tag
    )
    assert emb.uuid == "test-uuid"
    assert emb.text == "test text"
    assert emb.tag == tag


def test_emb_auto_id():
    tag = EmbeddingTag(provider="mock", model="mock")
    emb = TaggedEmbedding(
        uuid="uuid",
        text="text",
        vector=[0.1],
        tag=tag
    )
    assert emb.id is not None
    assert isinstance(emb.id, str)


def test_emb_auto_created_at():
    from datetime import datetime
    tag = EmbeddingTag(provider="mock", model="mock")
    before = datetime.utcnow()
    emb = TaggedEmbedding(
        uuid="uuid",
        text="text",
        vector=[0.1],
        tag=tag
    )
    after = datetime.utcnow()
    assert before <= emb.created_at <= after


def test_emb_default_version():
    tag = EmbeddingTag(provider="mock", model="mock")
    emb = TaggedEmbedding(
        uuid="uuid",
        text="text",
        vector=[0.1],
        tag=tag
    )
    assert emb.version == 1


def test_emb_to_dict():
    tag = EmbeddingTag(provider="mock", model="mock")
    emb = TaggedEmbedding(
        uuid="uuid",
        text="text",
        vector=[0.1, 0.2],
        tag=tag
    )
    d = emb.to_dict()
    assert d["uuid"] == "uuid"
    assert d["text"] == "text"
    assert d["vector"] == [0.1, 0.2]
    assert d["provider"] == "mock"
    assert d["model"] == "mock"


def test_emb_from_dict():
    from datetime import datetime
    data = {
        "id": "test-id",
        "uuid": "test-uuid",
        "text": "test text",
        "vector": [0.1, 0.2],
        "provider": "mock",
        "model": "mock",
        "created_at": datetime.utcnow().isoformat(),
        "version": 1,
    }
    emb = TaggedEmbedding.from_dict(data)
    assert emb.uuid == "test-uuid"
    assert emb.text == "test text"
    assert emb.tag.provider == "mock"


def test_emb_roundtrip():
    tag = EmbeddingTag(provider="openai", model="small")
    orig = TaggedEmbedding(
        uuid="uuid",
        text="text",
        vector=[0.1, 0.2, 0.3],
        tag=tag
    )
    d = orig.to_dict()
    restored = TaggedEmbedding.from_dict(d)
    assert restored.uuid == orig.uuid
    assert restored.text == orig.text
    assert restored.tag == orig.tag


test("TaggedEmbedding: create valid embedding", test_emb_create)
test("TaggedEmbedding: auto-generate id", test_emb_auto_id)
test("TaggedEmbedding: auto-set created_at", test_emb_auto_created_at)
test("TaggedEmbedding: default version to 1", test_emb_default_version)
test("TaggedEmbedding: serialize to dict", test_emb_to_dict)
test("TaggedEmbedding: deserialize from dict", test_emb_from_dict)
test("TaggedEmbedding: roundtrip serialization", test_emb_roundtrip)

# ==============================================================================
# MockEmbeddings Tests
# ==============================================================================

print("\n=== MockEmbeddings Tests ===")


def test_mock_tag():
    provider = MockEmbeddings()
    assert provider.tag.provider == "mock"
    assert provider.tag.model == "mock"


def test_mock_embed_single():
    provider = MockEmbeddings()
    emb = provider.embed("test text")
    assert isinstance(emb, TaggedEmbedding)
    assert emb.tag.provider == "mock"
    assert emb.text == "test text"


def test_mock_embed_deterministic():
    provider = MockEmbeddings()
    emb1 = provider.embed("same text")
    emb2 = provider.embed("same text")
    assert emb1.vector == emb2.vector


def test_mock_embed_different():
    provider = MockEmbeddings()
    emb1 = provider.embed("text1")
    emb2 = provider.embed("text2")
    assert emb1.vector != emb2.vector


def test_mock_embed_batch():
    provider = MockEmbeddings()
    embeddings = provider.embed_batch(["a", "b", "c"])
    assert len(embeddings) == 3
    assert all(isinstance(e, TaggedEmbedding) for e in embeddings)


def test_mock_embed_batch_order():
    provider = MockEmbeddings()
    texts = ["first", "second", "third"]
    embeddings = provider.embed_batch(texts)
    for i, emb in enumerate(embeddings):
        assert emb.text == texts[i]


def test_mock_embed_many():
    provider = MockEmbeddings()
    texts = [f"text{i}" for i in range(10)]
    embeddings = provider.embed_many(texts)
    assert len(embeddings) == 10


def test_mock_hash_to_vector():
    vec1 = MockEmbeddings._hash_to_vector("test", 100)
    vec2 = MockEmbeddings._hash_to_vector("test", 100)
    assert vec1 == vec2
    assert len(vec1) == 100


test("MockEmbeddings: has mock tag", test_mock_tag)
test("MockEmbeddings: embed single text", test_mock_embed_single)
test("MockEmbeddings: deterministic embedding", test_mock_embed_deterministic)
test("MockEmbeddings: different texts produce different embeddings", test_mock_embed_different)
test("MockEmbeddings: embed batch", test_mock_embed_batch)
test("MockEmbeddings: batch preserves order", test_mock_embed_batch_order)
test("MockEmbeddings: embed many", test_mock_embed_many)
test("MockEmbeddings: hash to vector", test_mock_hash_to_vector)

# ==============================================================================
# Validation Tests
# ==============================================================================

print("\n=== Validation Tests ===")


def test_validate_valid_list():
    tag = EmbeddingTag(provider="mock", model="mock")
    embeddings = [
        TaggedEmbedding(uuid="1", text="a", vector=[0.1], tag=tag),
        TaggedEmbedding(uuid="2", text="b", vector=[0.2], tag=tag),
    ]
    assert validate_embedding_tags(embeddings) is True


def test_validate_empty_list():
    assert validate_embedding_tags([]) is True


def test_validate_single():
    tag = EmbeddingTag(provider="mock", model="mock")
    emb = TaggedEmbedding(uuid="id", text="text", vector=[0.1], tag=tag)
    validate_single_embedding(emb)  # Should not raise


def test_known_providers():
    assert "mock" in KNOWN_PROVIDERS
    assert "openai" in KNOWN_PROVIDERS
    assert "anthropic" in KNOWN_PROVIDERS
    assert "local" in KNOWN_PROVIDERS
    assert "legacy" in KNOWN_PROVIDERS


test("Validation: validate valid embeddings list", test_validate_valid_list)
test("Validation: validate empty list", test_validate_empty_list)
test("Validation: validate single embedding", test_validate_single)
test("Validation: KNOWN_PROVIDERS exists", test_known_providers)

# ==============================================================================
# Audit Tests
# ==============================================================================

print("\n=== Audit Tests ===")


def test_count_by_provider():
    tag1 = EmbeddingTag(provider="openai", model="small")
    tag2 = EmbeddingTag(provider="openai", model="small")
    tag3 = EmbeddingTag(provider="anthropic", model="haiku")
    embeddings = [
        TaggedEmbedding(uuid="1", text="a", vector=[0.1], tag=tag1),
        TaggedEmbedding(uuid="2", text="b", vector=[0.2], tag=tag2),
        TaggedEmbedding(uuid="3", text="c", vector=[0.3], tag=tag3),
    ]
    assert count_by_provider(embeddings, "openai") == 2
    assert count_by_provider(embeddings, "anthropic") == 1


def test_count_by_model():
    tag1 = EmbeddingTag(provider="openai", model="small")
    tag2 = EmbeddingTag(provider="openai", model="large")
    embeddings = [
        TaggedEmbedding(uuid="1", text="a", vector=[0.1], tag=tag1),
        TaggedEmbedding(uuid="2", text="b", vector=[0.2], tag=tag1),
        TaggedEmbedding(uuid="3", text="c", vector=[0.3], tag=tag2),
    ]
    assert count_by_provider_model(embeddings, "openai", "small") == 2
    assert count_by_provider_model(embeddings, "openai", "large") == 1


test("Audit: count by provider", test_count_by_provider)
test("Audit: count by provider/model", test_count_by_model)

# ==============================================================================
# Migration Tests
# ==============================================================================

print("\n=== Migration Tests ===")


def test_auto_tag_legacy_all_tagged():
    tag = EmbeddingTag(provider="mock", model="mock")
    embeddings = [
        TaggedEmbedding(uuid="1", text="a", vector=[0.1], tag=tag),
        TaggedEmbedding(uuid="2", text="b", vector=[0.2], tag=tag),
    ]
    result = auto_tag_legacy(embeddings)
    assert len(result) == 2
    # Already tagged, so should stay the same
    assert result[0].tag == tag
    assert result[1].tag == tag


def test_migrate_provider():
    tag_old = EmbeddingTag(provider="old", model="model1")
    tag_new = EmbeddingTag(provider="new", model="model2")
    embeddings = [
        TaggedEmbedding(uuid="1", text="a", vector=[0.1], tag=tag_old),
        TaggedEmbedding(uuid="2", text="b", vector=[0.2], tag=tag_new),
    ]
    result = migrate_provider(embeddings, from_provider="old", to_provider="newer", to_model="newer")
    # First should be migrated
    assert result[0].tag.provider == "newer"
    assert result[0].tag.model == "newer"
    # Second should stay
    assert result[1].tag == tag_new


test("Migration: auto-tag legacy embeddings", test_auto_tag_legacy_all_tagged)
test("Migration: migrate provider", test_migrate_provider)

# ==============================================================================
# Results
# ==============================================================================

print(f"\n{'='*60}")
print(f"RESULTS: {passed} passed, {failed} failed")
print(f"{'='*60}")

if errors:
    print("\nFailed tests:")
    for name, error in errors:
        print(f"  - {name}")
        print(f"    {error}")

sys.exit(0 if failed == 0 else 1)
