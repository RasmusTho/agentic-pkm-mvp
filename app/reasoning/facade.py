"""ReasoningFacade -- mode-agnostic interface for agents.

Wraps the existing ``run_reasoning`` provider with convenience methods
and adds a graph-builder post-processor that converts CLAIMS output
into structured ``GraphExtraction`` objects.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable

from pydantic import BaseModel, Field

from app.reasoning.models import ReasoningMode, ReasoningRun


# ---------------------------------------------------------------------------
# Graph models
# ---------------------------------------------------------------------------

class GraphNode(BaseModel):
    """A node in a knowledge-graph extraction."""

    id: str
    label: str
    kind: str  # concept | entity | claim | evidence
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """A directed edge in a knowledge-graph extraction."""

    source: str
    target: str
    relation: str
    weight: float = 1.0
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphExtraction(BaseModel):
    """Container returned by ``ReasoningFacade.build_graph``."""

    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    source_run_id: str = ""


# ---------------------------------------------------------------------------
# Provider type
# ---------------------------------------------------------------------------

ProviderFn = Callable[..., ReasoningRun]


def _default_provider() -> ProviderFn:
    """Lazy import to avoid circular deps at module level."""
    from app.reasoning.provider import run_reasoning

    return run_reasoning


# ---------------------------------------------------------------------------
# Graph builder helpers
# ---------------------------------------------------------------------------

def _claims_to_graph(run: ReasoningRun) -> GraphExtraction:
    """Convert a CLAIMS-mode ReasoningRun result into graph nodes + edges."""

    result: dict[str, Any] = run.result if isinstance(run.result, dict) else {}
    claims = result.get("claims") or []
    evidence_list = result.get("evidence") or []
    inferences = result.get("inferences") or []

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    claim_ids: set[str] = set()

    for c in claims:
        cid = c.get("id") or str(uuid.uuid4())
        claim_ids.add(cid)
        nodes.append(
            GraphNode(
                id=cid,
                label=c.get("text", ""),
                kind="claim",
                properties={
                    k: v
                    for k, v in c.items()
                    if k not in {"id", "text"}
                },
            )
        )

    for ev in evidence_list:
        eid = ev.get("id") or str(uuid.uuid4())
        nodes.append(
            GraphNode(
                id=eid,
                label=ev.get("source_ref", ""),
                kind="evidence",
                properties={
                    k: v
                    for k, v in ev.items()
                    if k not in {"id", "source_ref"}
                },
            )
        )

    for inf in inferences:
        iid = inf.get("id") or str(uuid.uuid4())
        conclusion = inf.get("conclusion_id", "")
        premises = inf.get("premises") or []
        relation = inf.get("type", "infers")
        rationale = inf.get("rationale", "")

        for premise in premises:
            edges.append(
                GraphEdge(
                    source=premise,
                    target=conclusion,
                    relation=relation,
                    properties={"inference_id": iid, "rationale": rationale},
                )
            )

    return GraphExtraction(nodes=nodes, edges=edges, source_run_id=run.id)


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------

class ReasoningFacade:
    """Simplified, mode-agnostic reasoning interface for agents.

    The provider is injectable (any callable with the ``run_reasoning``
    signature) which makes the facade easy to test and the underlying
    implementation swappable.
    """

    def __init__(self, *, provider: ProviderFn | None = None) -> None:
        self._provider: ProviderFn = provider or _default_provider()

    # -- convenience methods ------------------------------------------------

    def extract_claims(
        self,
        object_id: str,
        *,
        trace_id: str | None = None,
    ) -> ReasoningRun:
        """Run CLAIMS extraction for a single object."""
        return self._provider(
            ReasoningMode.CLAIMS,
            [object_id],
            trace_id,
        )

    def review(
        self,
        object_id: str,
        *,
        trace_id: str | None = None,
    ) -> ReasoningRun:
        """Run REVIEW for a single object."""
        return self._provider(
            ReasoningMode.REVIEW,
            [object_id],
            trace_id,
        )

    def rank(
        self,
        object_ids: list[str],
        *,
        question: str | None = None,
        trace_id: str | None = None,
    ) -> ReasoningRun:
        """Rank a set of objects, optionally against a question."""
        return self._provider(
            ReasoningMode.RANKING,
            object_ids,
            trace_id,
            question=question,
        )

    def answer(
        self,
        question: str,
        *,
        context: str | None = None,
        object_ids: list[str] | None = None,
        trace_id: str | None = None,
    ) -> ReasoningRun:
        """Answer a question (ASK_ANSWER mode)."""
        return self._provider(
            ReasoningMode.ASK_ANSWER,
            object_ids or [],
            trace_id,
            question=question,
            context=context,
        )

    def plan(
        self,
        object_ids: list[str],
        *,
        goal: str | None = None,
        trace_id: str | None = None,
    ) -> ReasoningRun:
        """Run PLANNING mode for a set of objects."""
        return self._provider(
            ReasoningMode.PLANNING,
            object_ids,
            trace_id,
            question=goal,
        )

    # -- graph builder ------------------------------------------------------

    def build_graph(
        self,
        object_id: str,
        *,
        trace_id: str | None = None,
    ) -> GraphExtraction:
        """Extract claims then convert to a graph structure.

        This is a two-step operation:
        1. Run CLAIMS extraction via the provider.
        2. Post-process the result into ``GraphExtraction``.

        If the claims run fails, an empty ``GraphExtraction`` is returned
        with the ``source_run_id`` set so callers can inspect the run.
        """
        run = self.extract_claims(object_id, trace_id=trace_id)
        if run.status != "ok":
            return GraphExtraction(source_run_id=run.id)
        return _claims_to_graph(run)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_singleton: ReasoningFacade | None = None


def get_reasoning_facade(*, provider: ProviderFn | None = None) -> ReasoningFacade:
    """Return a (lazily-created) ReasoningFacade singleton.

    Pass *provider* to override the default ``run_reasoning`` function
    (useful in tests).  When a custom provider is given the singleton
    cache is bypassed so tests stay isolated.
    """
    global _singleton  # noqa: PLW0603

    if provider is not None:
        return ReasoningFacade(provider=provider)

    if _singleton is None:
        _singleton = ReasoningFacade()
    return _singleton


__all__ = [
    "GraphEdge",
    "GraphExtraction",
    "GraphNode",
    "ReasoningFacade",
    "get_reasoning_facade",
]
