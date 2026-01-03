from __future__ import annotations

from uuid import UUID

from app.search.service import ingest_object
from app.components.embeddings import get_embedding_identity


def test_ingest_roundtrip(stub_index) -> None:
    text = "Alpha beta gamma"
    metadata = {"title": "Sample doc"}

    object_id, dims = ingest_object(
        object_id=None,
        kind="note",
        source_ref="unit-test",
        payload=metadata,
        text=text,
    )

    assert isinstance(object_id, UUID)
    identity = get_embedding_identity()
    assert dims == identity.dim

    stored = stub_index.store[object_id]
    assert stored.kind == "note"
    assert stored.source_ref == "unit-test"
    assert stored.model == identity.model
    assert stored.payload["title"] == "Sample doc"
    assert stored.payload["text"].startswith("Alpha beta")
    assert stored.payload["content"].startswith("Alpha beta")
    assert stored.payload["object_type"] == "note"
    assert stored.payload["system_intent"] == "learn"
    assert stored.payload["emergent_tags"] == []
