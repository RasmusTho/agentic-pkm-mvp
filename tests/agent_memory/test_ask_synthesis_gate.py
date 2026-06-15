"""ASK answer synthesis activated through the Expansion Activation Gate (#2026).

Proves the first capability activation THROUGH the deterministic admissibility
gate (#2025) instead of the raw ``REASONING_ENABLE`` env flag:

- gate admits -> existing ``run_reasoning(ASK_ANSWER)`` synthesis runs, an
  activation receipt is emitted, and the receipt id + grounded source ids are
  surfaced (AC-1, AC-2).
- gate blocks -> the existing literal-snippet fallback is preserved with a
  logged reason and no receipt (AC-1 fallback).

All cases use a MOCK provider (``llm_answer`` is monkeypatched); no live LLM.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.activation.ask_synthesis import (
    ASK_SYNTHESIS_CAPABILITY_ID,
    ASK_SYNTHESIS_RECEIPT_EVENT,
    evaluate_ask_synthesis,
)
from app.activation.gate import REASON_NO_ADMISSIBLE_CONTEXT
from app.agents.ask import graph as ask_graph
from app.agents.ask.graph import run_ask_graph
from app.retrieval.capability import RetrievalHit, RetrievalResponse


def _retrieval_response(query: str, *, text: str = "literal snippet body") -> RetrievalResponse:
    return RetrievalResponse(
        query=query,
        trace_id="trace-ask-synthesis",
        hits=[
            RetrievalHit(
                object_id="ask-synth-1",
                doc_id="ask-synth-1",
                text=text,
                score=0.9,
                snippet=text,
                source_ref="vault/source.md",
                payload={"title": "ASK Source", "origin": "vault"},
            )
        ],
    )


def _no_recall(*_args: Any, **_kwargs: Any):  # type: ignore[no-untyped-def]
    return []


def _receipt_records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# --- gate function determinism ---------------------------------------------


def test_evaluate_ask_synthesis_admits_retrieved_context() -> None:
    decision = evaluate_ask_synthesis(["ask-synth-1"], receipt_id="fixed-receipt")
    assert decision.activatable is True
    assert decision.capability_id == ASK_SYNTHESIS_CAPABILITY_ID
    assert decision.admitted_artifact_ids == ["ask-synth-1"]
    assert decision.receipt.receipt_id == "fixed-receipt"
    assert decision.blocked_reasons == []


def test_evaluate_ask_synthesis_empty_context_has_no_admissible_blocker() -> None:
    # No sources -> nothing admitted; the answer node serves "No results found."
    decision = evaluate_ask_synthesis([])
    assert decision.admitted_artifact_ids == []
    assert REASON_NO_ADMISSIBLE_CONTEXT not in decision.blocked_reasons


# --- gate-on: synthesis runs + receipt emitted (AC-1, AC-2) ----------------


def test_gate_on_runs_synthesis_and_emits_receipt(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    receipts_path = tmp_path / "runtime" / "activation" / "ask_synthesis_receipts.jsonl"
    monkeypatch.setenv("ASK_SYNTHESIS_RECEIPTS_PATH", str(receipts_path))

    captured: dict[str, str] = {}

    def _fake_retrieve(request):  # type: ignore[no-untyped-def]
        return _retrieval_response(request.query)

    def _fake_llm_answer(question: str, context: str, ask_settings):  # type: ignore[no-untyped-def]
        captured["context"] = context
        return "Synthesized answer grounded in the source.", {"provider": "mock"}

    monkeypatch.setattr(ask_graph, "retrieve", _fake_retrieve)
    monkeypatch.setattr(ask_graph, "retrieve_relevant_promoted", _no_recall)
    monkeypatch.setattr(ask_graph, "llm_answer", _fake_llm_answer)

    state = run_ask_graph("what does the source say?", trace_id="trace-on")

    # Synthesis ran (not the literal snippet) and produced the generated answer.
    assert state.answer == "Synthesized answer grounded in the source."
    assert state.answer != "literal snippet body"
    assert state.llm_route == {"provider": "mock"}
    assert "literal snippet body" in captured["context"]

    # Activation receipt emitted and surfaced on state (grounded-source linkage).
    assert state.synthesis_receipt_id
    assert state.synthesis_source_ids == ["ask-synth-1"]

    receipts = _receipt_records(receipts_path)
    assert len(receipts) == 1
    record = receipts[0]
    assert record["event"] == ASK_SYNTHESIS_RECEIPT_EVENT
    assert record["event_id"] == state.synthesis_receipt_id
    payload = record["payload"]
    assert payload["capability_id"] == ASK_SYNTHESIS_CAPABILITY_ID
    assert payload["consuming_authority"] == "read-only"
    assert payload["outcome"] == "activatable"
    assert payload["activatable"] is True
    assert payload["admitted_artifact_ids"] == ["ask-synth-1"]
    assert payload["admitted_source_paths"] == {"ask-synth-1": "vault/source.md"}


def test_gate_on_surfaces_receipt_on_ask_response(tmp_path: Path, monkeypatch) -> None:
    """AC-2: the synthesis receipt id + grounded source ids reach AskResponse."""
    from fastapi.testclient import TestClient

    from app.api.app import app
    from app.api.routes import ask as ask_module
    from app.retrieval.hybrid import get_store

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "ASK_SYNTHESIS_RECEIPTS_PATH",
        str(tmp_path / "runtime" / "activation" / "ask_synthesis_receipts.jsonl"),
    )
    monkeypatch.setattr("app.api.routes.ask._ensure_hybrid_store_loaded", lambda: None)
    ask_module._HYBRID_WARMED = True

    def _fake_retrieve(request):  # type: ignore[no-untyped-def]
        return _retrieval_response(request.query)

    def _fake_llm_answer(question: str, context: str, ask_settings):  # type: ignore[no-untyped-def]
        return "Synthesized over admitted context.", {"provider": "mock"}

    monkeypatch.setattr("app.agents.ask.graph.retrieve", _fake_retrieve)
    monkeypatch.setattr(ask_graph, "retrieve_relevant_promoted", _no_recall)
    monkeypatch.setattr("app.agents.ask.graph.llm_answer", _fake_llm_answer)

    client = TestClient(app)
    try:
        response = client.post("/api/ask", json={"question": "surface the receipt"})
        assert response.status_code == 200
        body = response.json()
        assert body["answer"] == "Synthesized over admitted context."
        assert body["synthesis_receipt_id"]
        assert body["synthesis_source_ids"] == ["ask-synth-1"]
        assert body["sources"][0]["uuid"] == "ask-synth-1"
    finally:
        ask_module._HYBRID_WARMED = False
        get_store().set_documents([])


# --- gate-off: literal-snippet fallback preserved (AC-1 fallback) ----------


def test_gate_off_falls_back_to_literal_snippet(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    receipts_path = tmp_path / "runtime" / "activation" / "ask_synthesis_receipts.jsonl"
    monkeypatch.setenv("ASK_SYNTHESIS_RECEIPTS_PATH", str(receipts_path))

    def _fake_retrieve(request):  # type: ignore[no-untyped-def]
        return _retrieval_response(request.query)

    def _blocked_decision(source_ids, **kwargs):  # type: ignore[no-untyped-def]
        # Gate blocks (e.g. admissibility not declared on the target channel):
        # synthesis must not run, literal snippet is served.
        from app.activation.gate import ActivationDecision, ConsumingAuthority, GateDecisionReceipt
        from datetime import datetime, timezone

        return ActivationDecision(
            capability_id=ASK_SYNTHESIS_CAPABILITY_ID,
            activatable=False,
            blocked_reasons=["admissibility_undeclared"],
            admitted_artifact_ids=[],
            receipt=GateDecisionReceipt(
                receipt_id="blocked-receipt",
                capability_id=ASK_SYNTHESIS_CAPABILITY_ID,
                consuming_authority=ConsumingAuthority.READ_ONLY,
                outcome="blocked",
                blocked_reasons=["admissibility_undeclared"],
                evaluated=[],
                admitted_artifact_ids=[],
                created_at=datetime.now(tz=timezone.utc),
            ),
        )

    def _must_not_run(*_args: Any, **_kwargs: Any):  # type: ignore[no-untyped-def]
        raise AssertionError("synthesis must not run when the gate blocks")

    monkeypatch.setattr(ask_graph, "retrieve", _fake_retrieve)
    monkeypatch.setattr(ask_graph, "retrieve_relevant_promoted", _no_recall)
    monkeypatch.setattr(ask_graph, "evaluate_ask_synthesis", _blocked_decision)
    monkeypatch.setattr(ask_graph, "llm_answer", _must_not_run)

    state = run_ask_graph("what does the source say?", trace_id="trace-off")

    # Literal-snippet fallback preserved; no synthesis, no receipt.
    assert state.answer == "literal snippet body"
    assert state.synthesis_receipt_id is None
    assert state.synthesis_source_ids == []
    assert not receipts_path.exists()


def test_no_context_returns_no_results_without_gate(tmp_path: Path, monkeypatch) -> None:
    """Zero retrieval + zero recall short-circuits before the gate runs."""
    monkeypatch.chdir(tmp_path)

    def _empty_retrieve(request):  # type: ignore[no-untyped-def]
        return RetrievalResponse(query=request.query, trace_id="t", hits=[])

    def _gate_must_not_run(*_args: Any, **_kwargs: Any):  # type: ignore[no-untyped-def]
        raise AssertionError("gate must not run when there is no context at all")

    monkeypatch.setattr(ask_graph, "retrieve", _empty_retrieve)
    monkeypatch.setattr(ask_graph, "retrieve_relevant_promoted", _no_recall)
    monkeypatch.setattr(ask_graph, "evaluate_ask_synthesis", _gate_must_not_run)

    state = run_ask_graph("nothing matches", trace_id="trace-empty")
    assert state.answer == "No results found."
    assert state.synthesis_receipt_id is None
