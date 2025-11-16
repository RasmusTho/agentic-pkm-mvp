from __future__ import annotations
from typing import Any

from app.agents.base.graph import PERSpec, build_graph, AgentState
from app.agents.base.audit import audit_log
from app.events.types import INGEST_NORMALIZE_DONE
from app.agents.normalizer.agent import run as normalizer_run
from app.memory.store import recall
from app.store.object_store import ObjectStore

AGENT = "normalizer"

def _fetch_core6(object_id: str | None) -> dict:
    if not object_id:
        return {}
    store = ObjectStore()
    obj = store.get_object(object_id)
    if not obj:
        return {}
    payload = obj.payload or {}
    core6 = payload.get("core6") or {}
    if core6:
        return core6
    return {
        k: payload.get(k)
        for k in ["id", "type", "title", "created", "updated", "origin"]
        if payload.get(k) is not None
    }

def _plan(state: AgentState) -> AgentState:
    inp = state.get("input", {})
    state["memory_context"] = recall(AGENT, "normalized", object_id=None, limit=3)
    state["plan"] = "normalize_core6"
    audit_log(object_id=inp.get("object_id"), agent=AGENT, action="plan", trace_id=state.get("trace_id"), details={"plan": state["plan"]})
    return state

def _act(state: AgentState) -> AgentState:
    inp = state.get("input", {})
    res = normalizer_run(inp["path"], trace_id=state.get("trace_id"))
    state["act_result"] = res
    return state

def _reflect(state: AgentState) -> AgentState:
    res = state.get("act_result", {})
    ok = bool(res.get("object_id"))
    state["reflection"] = {"ok": ok}
    return state

def _emit(state: AgentState) -> AgentState:
    res = state.get("act_result", {})
    oid = res.get("object_id")
    core6 = res.get("core6") or _fetch_core6(oid)
    out = {"event": INGEST_NORMALIZE_DONE, "object_id": oid, "core6": core6}
    state["output"] = out
    audit_log(object_id=oid, agent=AGENT, action="emit", trace_id=state.get("trace_id"), details=out)
    return state

SPEC = PERSpec(name=AGENT, plan=_plan, act=_act, reflect=_reflect, emit=_emit)
GRAPH = build_graph(SPEC)

def invoke(path: str, *, trace_id: str) -> dict[str, Any]:
    state: AgentState = {"trace_id": trace_id, "input": {"path": path}}
    return dict(GRAPH.invoke(state))
