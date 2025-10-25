from __future__ import annotations
from typing import Any
from app.agents.base.graph import PERSpec, build_graph, AgentState
from app.agents.base.audit import audit_log
from app.agents.deduper.agent import run as deduper_run

AGENT = "deduper"

def _plan(state: AgentState) -> AgentState:
    state["plan"] = "dedupe_similar"
    audit_log(object_id=None, agent=AGENT, action="plan", trace_id=state.get("trace_id"), details={"plan": state["plan"]})
    return state

def _act(state: AgentState) -> AgentState:
    inp = state.get("input") or {}
    res = deduper_run(inp["object_ids"], threshold=inp.get("threshold", 0.92), trace_id=state.get("trace_id"))
    state["act_result"] = res
    return state

def _reflect(state: AgentState) -> AgentState:
    res = state.get("act_result") or {}
    ok = bool(res.get("decisions", 0) >= 0)
    state["reflection"] = {"ok": ok}
    return state

def _emit(state: AgentState) -> AgentState:
    res = state.get("act_result") or {}
    out = {"event": "curation.dedupe.done", "pairs": res.get("pairs", []), "decisions": int(res.get("decisions", 0))}
    state["output"] = out
    audit_log(object_id=None, agent=AGENT, action="emit", trace_id=state.get("trace_id"), details={"decisions": out["decisions"]})
    return state

SPEC = PERSpec(name=AGENT, plan=_plan, act=_act, reflect=_reflect, emit=_emit)
GRAPH = build_graph(SPEC)

def invoke(object_ids: list[str], *, trace_id: str, threshold: float = 0.92) -> dict[str, Any]:
    state: AgentState = {"trace_id": trace_id, "input": {"object_ids": object_ids, "threshold": threshold}}
    return dict(GRAPH.invoke(state))
