from __future__ import annotations

from fastapi.testclient import TestClient

from app.agents.ask.state import AgentState
from app.api.app import app
from app.api.routes import ask as ask_module
from app.retrieval.hybrid import get_store


def _stub_embeddings(monkeypatch) -> None:
    monkeypatch.setattr("app.index.embeddings.embed_texts", lambda texts, **_kwargs: [[0.1, 0.1, 0.1] for _ in texts])
    monkeypatch.setattr("app.index.embeddings.embed_text", lambda text, **_kwargs: [0.1, 0.1, 0.1])
    monkeypatch.setattr("app.retrieval.hybrid.embed_text", lambda text, language=None: [0.1, 0.1, 0.1])
    monkeypatch.setattr(
        "app.retrieval.hybrid.embed_batches",
        lambda texts, batch_size=32: ([[0.1, 0.1, 0.1] for _ in list(texts[:batch_size])],),
    )


def test_ask_contract_structure(monkeypatch) -> None:
    # Minimal embeddings stub to keep determinism
    _stub_embeddings(monkeypatch)

    hybrid = get_store()
    hybrid.set_documents(
        [
            {
                "doc_id": "contract-1",
                "text": "Reality-MVP contract note for API structure testing.",
                "source_ref": "tests/fixtures/reality_mvp/demo_note.md",
                "payload": {"origin": "vault", "zone": "hot", "trust": "own_raw", "title": "Contract"},
            }
        ]
    )
    ask_module._HYBRID_WARMED = True
    client = TestClient(app)
    try:
        resp = client.post("/api/ask", json={"question": "contract structure"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data.get("answer"), str)
        assert data["answer"].strip() != ""
        sources = data.get("sources")
        assert isinstance(sources, list)
        assert sources, "Expected at least one source"
        hit = sources[0]
        assert isinstance(hit.get("uuid"), str)
        assert isinstance(hit.get("origin"), str)
        assert hit.get("plane") == hit.get("origin"), "plane should mirror origin"
        assert "path" in hit
        # Zone should not be read from artifact payload; it should be None
        assert hit.get("zone") is None, "Zone should not be derived from artifact payload"
        if hit.get("title") is not None:
            assert isinstance(hit.get("title"), str)
    finally:
        hybrid.set_documents([])
        ask_module._HYBRID_WARMED = False


def test_ask_contract_no_hits_returns_default_answer_and_empty_sources(monkeypatch) -> None:
    _stub_embeddings(monkeypatch)

    hybrid = get_store()
    hybrid.set_documents([])
    ask_module._HYBRID_WARMED = True
    client = TestClient(app)
    try:
        resp = client.post("/api/ask", json={"question": "no matching docs"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("answer") == "No results found."
        assert data.get("sources") == []
    finally:
        hybrid.set_documents([])
        ask_module._HYBRID_WARMED = False


def test_ask_contract_propagates_trace_id_from_header(monkeypatch) -> None:
    _stub_embeddings(monkeypatch)
    ask_module._HYBRID_WARMED = True
    hybrid = get_store()
    hybrid.set_documents([])
    captured: dict[str, str | None] = {"trace_id": None}

    def _fake_run_ask_graph(query: str, trace_id: str | None = None, ask_settings=None) -> AgentState:
        captured["trace_id"] = trace_id
        return AgentState(trace_id=trace_id, query=query, hits=[], answer="No results found.")

    monkeypatch.setattr(ask_module, "run_ask_graph", _fake_run_ask_graph)
    client = TestClient(app)
    try:
        resp = client.post("/api/ask", json={"question": "trace header"}, headers={"x-trace-id": "trace-ask-header-1"})
        assert resp.status_code == 200
        assert captured["trace_id"] == "trace-ask-header-1"
    finally:
        hybrid.set_documents([])
        ask_module._HYBRID_WARMED = False


def test_ask_contract_generates_trace_id_when_missing(monkeypatch) -> None:
    _stub_embeddings(monkeypatch)
    ask_module._HYBRID_WARMED = True
    hybrid = get_store()
    hybrid.set_documents([])
    captured: dict[str, str | None] = {"trace_id": None}

    def _fake_run_ask_graph(query: str, trace_id: str | None = None, ask_settings=None) -> AgentState:
        captured["trace_id"] = trace_id
        return AgentState(trace_id=trace_id, query=query, hits=[], answer="No results found.")

    class _FakeUuid:
        hex = "generated-ask-trace-1"

    monkeypatch.setattr(ask_module, "run_ask_graph", _fake_run_ask_graph)
    monkeypatch.setattr("app.middleware.trace.uuid.uuid4", lambda: _FakeUuid())
    client = TestClient(app)
    try:
        resp = client.post("/api/ask", json={"question": "trace generated"})
        assert resp.status_code == 200
        assert captured["trace_id"] == "generated-ask-trace-1"
        assert resp.headers.get("x-trace-id") == "generated-ask-trace-1"
    finally:
        hybrid.set_documents([])
        ask_module._HYBRID_WARMED = False
