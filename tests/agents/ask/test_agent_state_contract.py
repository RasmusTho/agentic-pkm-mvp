"""Adapter-internal ASK state contract tests.

These tests lock the ASK adapter boundary only. They are not assertions about
public `/api/ask` product contracts.
"""

from app.agents.ask.graph import _to_retrieved_hit
from app.agents.ask.graph import run_ask_graph
from app.agents.ask.state import AgentState
from app.retrieval.capability import RetrievalResponse


def test_agent_state_minimal_valid_shape_and_documented_fields() -> None:
    """Validate the minimal adapter-internal AgentState shape and fields."""
    state = AgentState(query="what is yggdrasil")

    assert state.trace_id is None
    assert state.query == "what is yggdrasil"
    assert state.hits == []
    assert state.recalled == []
    assert state.recalled_content == {}
    assert state.answer is None
    assert state.reasoning is None
    assert state.llm_route is None


def test_retrieved_hit_fields_and_trace_id_carry_through_behavior() -> None:
    """Verify adapter-internal RetrievedHit mapping plus trace_id carry-through."""
    raw_hit = {
        "id": "doc-123",
        "score": 0.72,
        "source_ref": "docs/ARCHITECTURE.md",
        "snippet": "Yggdrasil routes through ASK.",
        "payload": {
            "origin": "vault",
            "trust": "high",
            "title": "Architecture",
            "source_ref": "docs/ARCHITECTURE.md",
            "extra": "kept",
        },
    }

    mapped = _to_retrieved_hit(raw_hit, ask_score=0.88)

    assert mapped.object_id == "doc-123"
    assert mapped.score == 0.72
    assert mapped.ask_score == 0.88
    assert mapped.origin == "vault"
    assert mapped.zone is None
    assert mapped.trust == "high"
    assert mapped.title == "Architecture"
    assert mapped.path == "docs/ARCHITECTURE.md"
    assert mapped.snippet == "Yggdrasil routes through ASK."
    assert mapped.payload["extra"] == "kept"

    state = AgentState(trace_id="trace-ask-1", query="ask query", hits=[mapped])
    assert state.trace_id == "trace-ask-1"
    assert state.hits[0].object_id == "doc-123"


def test_ask_trace_id_forwards_into_retrieval_request(monkeypatch) -> None:
    """Verify run_ask_graph propagates trace_id into retrieval capability input."""
    captured: dict[str, str | None] = {"trace_id": None}

    def _fake_retrieve(request):
        captured["trace_id"] = request.trace_id
        return RetrievalResponse(query=request.query, hits=[], trace_id=request.trace_id)

    monkeypatch.setattr("app.agents.ask.graph.retrieve", _fake_retrieve)

    state = run_ask_graph("trace contract", trace_id="trace-ask-propagation-1")

    assert captured["trace_id"] == "trace-ask-propagation-1"
    assert state.trace_id == "trace-ask-propagation-1"


def test_ask_without_hits_or_recall_returns_no_results(monkeypatch) -> None:
    """Preserve the fallback when neither retrieval hits nor recalled memory exist (#1990)."""

    def _fake_retrieve(request):
        return RetrievalResponse(query=request.query, hits=[], trace_id=request.trace_id)

    def _fake_recall(query, **kwargs):
        return []

    monkeypatch.setattr("app.agents.ask.graph.retrieve", _fake_retrieve)
    monkeypatch.setattr("app.agents.ask.graph.retrieve_relevant_promoted", _fake_recall)

    state = run_ask_graph("no hits and no recall", trace_id="trace-no-context")

    assert state.hits == []
    assert state.recalled == []
    assert state.answer == "No results found."
