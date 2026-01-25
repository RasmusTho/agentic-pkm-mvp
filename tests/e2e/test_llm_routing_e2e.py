from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import ask as ask_module
from app.retrieval.hybrid import get_store


@pytest.mark.e2e
def test_force_override_affects_ask_api(monkeypatch) -> None:
    """
    Validate that LLM_FORCE_MODEL propagates through full stack.

    Chain: Router → Fabric → call_llm → ASK agent → API response

    See: docs/LLM_ROUTING.md §How to debug routing
    """
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("LLM_FORCE_PROVIDER", "mock")
    monkeypatch.setenv("LLM_FORCE_MODEL", "mock-forced-test")
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("REASONING_ENABLE", "1")
    monkeypatch.setenv("REASONING_PROVIDER", "llm")
    monkeypatch.setenv("EMBED_PROFILE", "deterministic")

    hybrid = get_store()
    hybrid.set_documents(
        [
            {
                "doc_id": "e2e-1",
                "text": "Test document for force override validation",
                "source_ref": "test://e2e",
                "payload": {"origin": "vault", "title": "E2E"},
            }
        ]
    )
    monkeypatch.setattr(ask_module, "_HYBRID_WARMED", False, raising=False)

    client = TestClient(app)
    try:
        resp = client.post("/api/ask", json={"question": "test"})
        assert resp.status_code == 200
        data = resp.json()
        route = data.get("llm_route") or {}
        assert route.get("provider") == "mock"
        assert route.get("model") == "mock-forced-test"
    finally:
        hybrid.set_documents([])
        monkeypatch.setattr(ask_module, "_HYBRID_WARMED", False, raising=False)
