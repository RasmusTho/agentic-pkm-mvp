from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import ask as ask_module
from app.retrieval.hybrid import get_store as get_hybrid_store
from app.stores import get_object_store, reset_store_backends
from app.stores.pg import pg_available


@pytest.mark.pg
def test_ask_warm_loads_pg_store(monkeypatch) -> None:
    if not pg_available():
        pytest.skip("Postgres backend not available")

    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")
    reset_store_backends()
    hybrid_store = get_hybrid_store()
    hybrid_store.set_documents([])
    ask_module._HYBRID_WARMED = False

    store = get_object_store()
    object_id = uuid4()
    store.put(
        object_id,
        kind="note",
        source_ref="unit-test://warm-load",
        payload={"text": "Alpha warm content", "origin": "vault"},
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
    ask_module._HYBRID_WARMED = False
