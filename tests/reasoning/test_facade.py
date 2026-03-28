"""Tests for app.reasoning.facade -- ReasoningFacade and graph builder."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.reasoning.facade import (
    ReasoningFacade,
    _claims_to_graph,
    get_reasoning_facade,
)
from app.reasoning.models import ReasoningMode, ReasoningRun

pytestmark = pytest.mark.not_pg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_run(
    mode: ReasoningMode,
    *,
    status: str = "ok",
    result: Any = None,
    object_uuids: list[str] | None = None,
    trace_id: str | None = None,
    error: str | None = None,
) -> ReasoningRun:
    return ReasoningRun(
        id=str(uuid.uuid4()),
        mode=mode,
        status=status,
        result=result,
        object_uuids=object_uuids or [],
        trace_id=trace_id,
        error=error,
    )


def _fake_provider(
    mode: ReasoningMode,
    object_ids: list[str],
    trace_id: str | None = None,
    **kwargs: Any,
) -> ReasoningRun:
    """Deterministic mock provider that records calls."""
    result: dict[str, Any]
    if mode == ReasoningMode.CLAIMS:
        result = {
            "claims": [
                {"id": "c1", "object_uuid": object_ids[0], "text": "Sun is hot", "modality": "assertion", "confidence": 0.9},
            ],
            "evidence": [
                {"id": "e1", "object_uuid": object_ids[0], "source_ref": "paper.pdf", "kind": "citation", "strength": 0.8},
            ],
            "inferences": [
                {"id": "i1", "premises": ["c1"], "conclusion_id": "c1", "type": "deductive", "rationale": "trivial"},
            ],
        }
    elif mode == ReasoningMode.REVIEW:
        result = {"summary": "looks good", "issues": [], "suggestions": ["add sources"]}
    elif mode == ReasoningMode.RANKING:
        result = {"ranking": [{"object_uuid": oid, "score": 0.9, "reason": "relevant"} for oid in object_ids]}
    elif mode == ReasoningMode.ASK_ANSWER:
        result = {"answer": f"mock answer to: {kwargs.get('question', '?')}"}
    elif mode == ReasoningMode.PLANNING:
        result = {"plan": "step 1, step 2"}
    else:
        result = {}

    return _make_run(mode, result=result, object_uuids=list(object_ids), trace_id=trace_id)


def _failing_provider(
    mode: ReasoningMode,
    object_ids: list[str],
    trace_id: str | None = None,
    **kwargs: Any,
) -> ReasoningRun:
    return _make_run(mode, status="failed", error="provider exploded", object_uuids=list(object_ids), trace_id=trace_id)


# ---------------------------------------------------------------------------
# Delegation tests
# ---------------------------------------------------------------------------

class TestExtractClaims:
    def test_delegates_to_claims_mode(self) -> None:
        facade = ReasoningFacade(provider=_fake_provider)
        run = facade.extract_claims("obj-1")
        assert run.mode == ReasoningMode.CLAIMS
        assert run.status == "ok"
        assert run.object_uuids == ["obj-1"]
        assert len(run.result["claims"]) == 1

    def test_trace_id_passthrough(self) -> None:
        facade = ReasoningFacade(provider=_fake_provider)
        run = facade.extract_claims("obj-1", trace_id="t-42")
        assert run.trace_id == "t-42"


class TestReview:
    def test_delegates_to_review_mode(self) -> None:
        facade = ReasoningFacade(provider=_fake_provider)
        run = facade.review("obj-2")
        assert run.mode == ReasoningMode.REVIEW
        assert run.status == "ok"
        assert run.result["summary"] == "looks good"

    def test_trace_id_passthrough(self) -> None:
        facade = ReasoningFacade(provider=_fake_provider)
        run = facade.review("obj-2", trace_id="t-99")
        assert run.trace_id == "t-99"


class TestRank:
    def test_delegates_to_ranking_mode(self) -> None:
        facade = ReasoningFacade(provider=_fake_provider)
        run = facade.rank(["a", "b", "c"])
        assert run.mode == ReasoningMode.RANKING
        assert len(run.result["ranking"]) == 3

    def test_question_kwarg_forwarded(self) -> None:
        calls: list[dict] = []

        def spy(mode, ids, trace_id=None, **kw):
            calls.append({"mode": mode, "kwargs": kw})
            return _fake_provider(mode, ids, trace_id, **kw)

        facade = ReasoningFacade(provider=spy)
        facade.rank(["x"], question="why?")
        assert calls[0]["kwargs"]["question"] == "why?"


class TestAnswer:
    def test_delegates_to_ask_answer_mode(self) -> None:
        facade = ReasoningFacade(provider=_fake_provider)
        run = facade.answer("What is 2+2?")
        assert run.mode == ReasoningMode.ASK_ANSWER
        assert "mock answer" in run.result["answer"]

    def test_context_and_object_ids_forwarded(self) -> None:
        calls: list[dict] = []

        def spy(mode, ids, trace_id=None, **kw):
            calls.append({"ids": ids, "kwargs": kw})
            return _fake_provider(mode, ids, trace_id, **kw)

        facade = ReasoningFacade(provider=spy)
        facade.answer("q?", context="ctx", object_ids=["o1", "o2"])
        assert calls[0]["ids"] == ["o1", "o2"]
        assert calls[0]["kwargs"]["context"] == "ctx"

    def test_defaults_object_ids_to_empty(self) -> None:
        calls: list[dict] = []

        def spy(mode, ids, trace_id=None, **kw):
            calls.append({"ids": ids})
            return _fake_provider(mode, ids, trace_id, **kw)

        facade = ReasoningFacade(provider=spy)
        facade.answer("q?")
        assert calls[0]["ids"] == []


class TestPlan:
    def test_delegates_to_planning_mode(self) -> None:
        facade = ReasoningFacade(provider=_fake_provider)
        run = facade.plan(["a", "b"], goal="ship it")
        assert run.mode == ReasoningMode.PLANNING

    def test_goal_forwarded_as_question(self) -> None:
        calls: list[dict] = []

        def spy(mode, ids, trace_id=None, **kw):
            calls.append({"kwargs": kw})
            return _fake_provider(mode, ids, trace_id, **kw)

        facade = ReasoningFacade(provider=spy)
        facade.plan(["a"], goal="do X")
        assert calls[0]["kwargs"]["question"] == "do X"


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------

class TestErrorPropagation:
    def test_failed_run_surfaces_error(self) -> None:
        facade = ReasoningFacade(provider=_failing_provider)
        run = facade.extract_claims("obj-1")
        assert run.status == "failed"
        assert run.error == "provider exploded"

    def test_failed_claims_gives_empty_graph(self) -> None:
        facade = ReasoningFacade(provider=_failing_provider)
        graph = facade.build_graph("obj-1")
        assert graph.nodes == []
        assert graph.edges == []
        assert graph.source_run_id  # should still capture run id


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

class TestBuildGraph:
    def test_claims_become_nodes(self) -> None:
        facade = ReasoningFacade(provider=_fake_provider)
        graph = facade.build_graph("obj-1")
        claim_nodes = [n for n in graph.nodes if n.kind == "claim"]
        assert len(claim_nodes) == 1
        assert claim_nodes[0].id == "c1"
        assert claim_nodes[0].label == "Sun is hot"

    def test_evidence_becomes_nodes(self) -> None:
        facade = ReasoningFacade(provider=_fake_provider)
        graph = facade.build_graph("obj-1")
        ev_nodes = [n for n in graph.nodes if n.kind == "evidence"]
        assert len(ev_nodes) == 1
        assert ev_nodes[0].label == "paper.pdf"

    def test_inferences_become_edges(self) -> None:
        facade = ReasoningFacade(provider=_fake_provider)
        graph = facade.build_graph("obj-1")
        assert len(graph.edges) == 1
        edge = graph.edges[0]
        assert edge.source == "c1"
        assert edge.target == "c1"
        assert edge.relation == "deductive"
        assert edge.properties["rationale"] == "trivial"

    def test_source_run_id_set(self) -> None:
        facade = ReasoningFacade(provider=_fake_provider)
        graph = facade.build_graph("obj-1")
        assert graph.source_run_id  # non-empty

    def test_trace_id_forwarded(self) -> None:
        calls: list[str | None] = []

        def spy(mode, ids, trace_id=None, **kw):
            calls.append(trace_id)
            return _fake_provider(mode, ids, trace_id, **kw)

        facade = ReasoningFacade(provider=spy)
        facade.build_graph("x", trace_id="t-graph")
        assert calls[0] == "t-graph"


class TestClaimsToGraphDirect:
    """Test the ``_claims_to_graph`` helper with edge cases."""

    def test_empty_result(self) -> None:
        run = _make_run(ReasoningMode.CLAIMS, result={})
        graph = _claims_to_graph(run)
        assert graph.nodes == []
        assert graph.edges == []

    def test_none_result(self) -> None:
        run = _make_run(ReasoningMode.CLAIMS, result=None)
        graph = _claims_to_graph(run)
        assert graph.nodes == []
        assert graph.edges == []

    def test_multiple_premises(self) -> None:
        run = _make_run(
            ReasoningMode.CLAIMS,
            result={
                "claims": [
                    {"id": "c1", "text": "A"},
                    {"id": "c2", "text": "B"},
                    {"id": "c3", "text": "C"},
                ],
                "evidence": [],
                "inferences": [
                    {"id": "i1", "premises": ["c1", "c2"], "conclusion_id": "c3", "type": "abductive", "rationale": "because"},
                ],
            },
        )
        graph = _claims_to_graph(run)
        assert len(graph.nodes) == 3
        assert len(graph.edges) == 2
        sources = {e.source for e in graph.edges}
        assert sources == {"c1", "c2"}
        assert all(e.target == "c3" for e in graph.edges)


# ---------------------------------------------------------------------------
# Custom provider injection
# ---------------------------------------------------------------------------

class TestCustomProvider:
    def test_injected_provider_is_used(self) -> None:
        called = {"count": 0}

        def custom(mode, ids, trace_id=None, **kw):
            called["count"] += 1
            return _fake_provider(mode, ids, trace_id, **kw)

        facade = ReasoningFacade(provider=custom)
        facade.extract_claims("x")
        facade.review("x")
        assert called["count"] == 2


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------

class TestGetReasoningFacade:
    def test_returns_facade_instance(self) -> None:
        facade = get_reasoning_facade(provider=_fake_provider)
        assert isinstance(facade, ReasoningFacade)

    def test_custom_provider_bypasses_singleton(self) -> None:
        f1 = get_reasoning_facade(provider=_fake_provider)
        f2 = get_reasoning_facade(provider=_fake_provider)
        assert f1 is not f2  # each call with custom provider is fresh
