from __future__ import annotations

from typing import Any

from app.agents.base.audit import audit_log
from app.agents.base.graph import AgentState, PERSpec, build_graph
from app.agents.set_evaluator.agent import run as evaluate_run, AGENT
from app.memory.store import recall


def _plan(state: AgentState) -> AgentState:
    inp = state.get("input") or {}
    state["plan"] = "evaluate_promotion"
    state["memory_context"] = {
        "recent_evaluations": recall(AGENT, "evaluation", object_id=None, limit=3),
        "recent_reviews": recall("reviewer", "review", object_id=inp.get("object_id"), limit=1),
        "indexer_stats": recall("indexer", "embedding_stats", object_id=inp.get("object_id"), limit=1),
    }
    audit_log(
        object_id=inp.get("object_id"),
        agent=AGENT,
        action="plan",
        trace_id=state.get("trace_id"),
        details={"plan": state["plan"]},
    )
    return state


def _act(state: AgentState) -> AgentState:
    inp = state.get("input") or {}
    res = evaluate_run(
        inp["object_id"],
        trace_id=state.get("trace_id"),
        threshold=float(inp.get("threshold", 0.8)),
    )
    state["act_result"] = res
    return state


def _reflect(state: AgentState) -> AgentState:
    res = state.get("act_result") or {}
    state["reflection"] = {"ok": isinstance(res.get("score"), (int, float))}
    return state


def _emit(state: AgentState) -> AgentState:
    res = state.get("act_result") or {}
    state["output"] = res
    audit_log(
        object_id=res.get("object_id"),
        agent=AGENT,
        action="emit",
        trace_id=state.get("trace_id"),
        details=res,
    )
    return state


SPEC = PERSpec(name=AGENT, plan=_plan, act=_act, reflect=_reflect, emit=_emit)
GRAPH = build_graph(SPEC)


def invoke(object_id: str, *, trace_id: str, threshold: float = 0.8) -> dict[str, Any]:
    state: AgentState = {
        "trace_id": trace_id,
        "input": {"object_id": object_id, "threshold": threshold},
    }
    return dict(GRAPH.invoke(state))
