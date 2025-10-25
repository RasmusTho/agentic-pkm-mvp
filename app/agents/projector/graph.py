from __future__ import annotations

from typing import Any

from app.agents.base.audit import audit_log
from app.agents.base.graph import AgentState, PERSpec, build_graph
from app.agents.projector.agent import run as projector_run, AGENT
from app.memory.store import recall


def _plan(state: AgentState) -> AgentState:
    inp = state.get("input") or {}
    state["plan"] = "project_promoted_objects"
    state["memory_context"] = {
        "recent_projections": recall(AGENT, "projection", object_id=None, limit=3),
        "latest_evaluation": recall("set_evaluator", "evaluation", object_id=inp.get("object_id"), limit=1),
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
    res = projector_run(
        inp["object_id"],
        set_name=inp.get("set_name", "published"),
        trace_id=state.get("trace_id"),
    )
    state["act_result"] = res
    return state


def _reflect(state: AgentState) -> AgentState:
    res = state.get("act_result") or {}
    state["reflection"] = {"ok": bool(res.get("event"))}
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


def invoke(object_id: str, *, trace_id: str, set_name: str = "published") -> dict[str, Any]:
    state: AgentState = {
        "trace_id": trace_id,
        "input": {"object_id": object_id, "set_name": set_name},
    }
    return dict(GRAPH.invoke(state))
