from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import ask as ask_module
from app.components.embeddings import EmbeddingIdentity
from app.retrieval.hybrid import get_store as get_hybrid_store
from app.retrieval.hybrid import reset_durable_rebuild_state
from app.stores import get_vector_index, reset_store_backends
from app.db.dsn import resolve_dsn
from app.stores.pg import pg_available


@pytest.mark.pg
def test_ask_warm_loads_pg_store(monkeypatch) -> None:
    """KERNEL-05: the ASK warm-load path rebuilds the retrieval cache from the
    durable ``store_vector_index`` — not from a scan of the object store. See
    docs/RUNTIME_CORRECTNESS_KERNEL/RETRIEVAL_READS_DURABLE_INDEX.md."""
    if not pg_available():
        pytest.skip("Postgres backend not available")

    monkeypatch.setenv("DATABASE_URL", resolve_dsn() or "postgresql://app:app@127.0.0.1:15432/app")
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")
    reset_store_backends()
    hybrid_store = get_hybrid_store()
    hybrid_store.set_documents([])
    reset_durable_rebuild_state()
    ask_module._HYBRID_WARMED = False

    identity = EmbeddingIdentity(provider="mock", model="mock-embedding", dim=8, normalize=False)
    vector_index = get_vector_index()
    object_id = uuid4()
    vector_index.upsert(
        object_id=object_id,
        kind="note",
        source_ref="unit-test://warm-load",
        payload={"text": "Alpha warm content", "content": "Alpha warm content", "origin": "vault"},
        embedding=[0.1] * 8,
        model=identity.model,
        identity=identity,
    )

    client = TestClient(app)
    resp = client.post("/api/ask", json={"question": "warm content"})
    assert resp.status_code == 200

    docs = hybrid_store.all()
    assert any(doc.doc_id == str(object_id) for doc in docs)

    data = resp.json()
    assert data["sources"], "Hybrid store should provide at least one source"
    assert data["answer"] != "No results found."

    reset_store_backends()
    hybrid_store.set_documents([])
    reset_durable_rebuild_state()
    ask_module._HYBRID_WARMED = False
