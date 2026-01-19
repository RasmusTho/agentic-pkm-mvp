from __future__ import annotations

from uuid import uuid4

import pytest

from app.components.embeddings import EmbeddingIdentity
from app.search import service as search_service


class _CapturingIndex:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def upsert(self, *args, **kwargs):
        self.calls.append(kwargs)
        return None


class _LegacyIndex:
    def upsert(self, *args, **kwargs):
        if "identity" in kwargs:
            raise TypeError("unexpected keyword 'identity'")
        return None


def test_ingest_object_uses_canonical_identity(monkeypatch) -> None:
    identity = EmbeddingIdentity(provider="mock", model="mock-model", dim=3, normalize=True)
    index = _CapturingIndex()

    def fake_embed_query(text: str, profile: str = "default"):
        return [0.1, 0.2, 0.3], identity

    monkeypatch.setattr(search_service, "embed_query", fake_embed_query)
    monkeypatch.setattr(search_service, "get_vector_index", lambda *_: index)

    object_id, dims = search_service.ingest_object(
        object_id=uuid4(),
        kind="note",
        source_ref="tests",
        payload={"text": "hello"},
        text="hello",
    )

    assert dims == 3
    assert index.calls, "Expected ingest_object to upsert via vector index"
    call = index.calls[0]
    assert call.get("identity") is identity
    assert call.get("model") == identity.model
    assert call.get("embedding") == [0.1, 0.2, 0.3]
    assert call.get("object_id") == object_id


def test_ingest_object_requires_identity_support(monkeypatch) -> None:
    identity = EmbeddingIdentity(provider="mock", model="mock-model", dim=3, normalize=True)
    legacy = _LegacyIndex()

    def fake_embed_query(text: str, profile: str = "default"):
        return [0.1, 0.2, 0.3], identity

    monkeypatch.setattr(search_service, "embed_query", fake_embed_query)
    monkeypatch.setattr(search_service, "get_vector_index", lambda *_: legacy)

    with pytest.raises(TypeError):
        search_service.ingest_object(
            object_id=uuid4(),
            kind="note",
            source_ref="tests",
            payload={"text": "legacy"},
            text="legacy",
        )
