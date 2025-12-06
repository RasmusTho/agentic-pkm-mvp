from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import ask as ask_module
from app.retrieval.hybrid import get_store as get_hybrid_store


def _prime_hybrid_store() -> None:
    hybrid = get_hybrid_store()
    hybrid.set_documents([])
    hybrid.add_document(doc_id="uuid-1", text="Alpha warm content for hybrid alias test.", source_ref="unit-test://note")
    ask_module._HYBRID_WARMED = True


def _reset_hybrid_store() -> None:
    hybrid = get_hybrid_store()
    hybrid.set_documents([])
    ask_module._HYBRID_WARMED = False


def test_ask_accepts_question_field() -> None:
    _prime_hybrid_store()
    client = TestClient(app)

    resp = client.post("/api/ask", json={"question": "warm content"})
    _reset_hybrid_store()

    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"], "Answer should be present"
    assert data["sources"], "Sources should not be empty"


def test_ask_accepts_query_alias() -> None:
    _prime_hybrid_store()
    client = TestClient(app)

    resp = client.post("/api/ask", json={"query": "warm content"})
    _reset_hybrid_store()

    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"], "Answer should be present"
    assert data["sources"], "Sources should not be empty"
