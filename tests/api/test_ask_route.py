from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import ask as ask_module
from app.retrieval.capability import RetrievalHit, RetrievalResponse
from app.retrieval.hybrid import get_store


def test_ask_route_uses_retrieval_capability_contract(monkeypatch) -> None:
    monkeypatch.setattr("app.api.routes.ask._ensure_hybrid_store_loaded", lambda: None)
    ask_module._HYBRID_WARMED = True

    called = {"count": 0}

    def _fake_retrieve(request):  # type: ignore[no-untyped-def]
        called["count"] += 1
        return RetrievalResponse(
            query=request.query,
            trace_id=request.trace_id,
            metadata={
                "provenance": {"capability": "retrieval", "adapter": "hybrid_search"},
                "temporal_validity": {
                    "state": "fresh",
                    "is_fresh": True,
                    "is_stale": False,
                    "is_partial": False,
                    "is_unknown": False,
                },
            },
            hits=[
                RetrievalHit(
                    object_id="contract-ask-1",
                    doc_id="contract-ask-1",
                    text="retrieval capability answer context",
                    score=0.9,
                    snippet="retrieval capability answer context",
                    source_ref="vault/contract-ask-1.md",
                    payload={"title": "Contract Ask", "origin": "vault"},
                )
            ],
        )

    monkeypatch.setattr("app.agents.ask.graph.retrieve", _fake_retrieve)
    monkeypatch.setattr("app.agents.ask.graph.reasoning_enabled", lambda: False)

    client = TestClient(app)
    try:
        response = client.post("/api/ask", json={"question": "contract path"})
        assert response.status_code == 200
        body = response.json()
        assert called["count"] == 1
        assert body["answer"] == "retrieval capability answer context"
        assert body["sources"][0]["uuid"] == "contract-ask-1"
    finally:
        ask_module._HYBRID_WARMED = False
        get_store().set_documents([])
