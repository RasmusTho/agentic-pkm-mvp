from __future__ import annotations
from typing import Any
import os
from app.agents.base.graph import PERSpec, build_graph, AgentState
from app.agents.base.audit import audit_log
from app.events.types import CURATION_CLASSIFY_DONE
from app.agents.classifier.agent import run as classifier_run
from app.memory.store import recall

AGENT = "classifier"

def _plan(state: AgentState) -> AgentState:
    state["memory_context"] = recall(AGENT, "classified", object_id=None, limit=3)
    state["plan"] = "classify_note"
    audit_log(object_id=(state.get("input") or {}).get("object_id"), agent=AGENT, action="plan", trace_id=state.get("trace_id"), details={"plan": state["plan"]})
    return state

def _act(state: AgentState) -> AgentState:
    inp = state.get("input") or {}
    res = classifier_run(inp["object_id"], trace_id=state.get("trace_id"))
    state["act_result"] = res
    return state

def _reflect(state: AgentState) -> AgentState:
    res = state.get("act_result") or {}
    ok = bool(res.get("decisions", 0))
    state["reflection"] = {"ok": ok}
    return state

def _emit(state: AgentState) -> AgentState:
    res = state.get("act_result") or {}
    oid = (state.get("input") or {}).get("object_id")
    out = {"event": CURATION_CLASSIFY_DONE, "object_id": oid, "decisions": int(res.get("decisions", 0))}
    state["output"] = out
    audit_log(object_id=oid, agent=AGENT, action="emit", trace_id=state.get("trace_id"), details=out)
    return state

SPEC = PERSpec(name=AGENT, plan=_plan, act=_act, reflect=_reflect, emit=_emit)
GRAPH = build_graph(SPEC)

def invoke(object_id: str, *, trace_id: str) -> dict[str, Any]:
    state: AgentState = {"trace_id": trace_id, "input": {"object_id": object_id}}
    return dict(GRAPH.invoke(state))
