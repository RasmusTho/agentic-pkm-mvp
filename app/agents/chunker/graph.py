from __future__ import annotations
from typing import Any
from app.agents.base.graph import PERSpec, build_graph, AgentState
from app.agents.base.audit import audit_log
from app.agents.chunker.agent import run as chunker_run
from app.memory.store import recall

AGENT = "chunker"

def _plan(state: AgentState) -> AgentState:
    state["memory_context"] = recall(AGENT, "chunked", object_id=None, limit=3)
    state["plan"] = "chunk_heading_first"
    audit_log(object_id=(state.get("input") or {}).get("object_id"), agent=AGENT, action="plan", trace_id=state.get("trace_id"), details={"plan": state["plan"]})
    return state

def _act(state: AgentState) -> AgentState:
    inp = state.get("input") or {}
    res = chunker_run(inp["object_id"], max_tokens=inp.get("max_tokens", 800), overlap=inp.get("overlap", 120), strategy=inp.get("strategy", "heading_first"), trace_id=state.get("trace_id"))
    state["act_result"] = res
    return state

def _reflect(state: AgentState) -> AgentState:
    res = state.get("act_result") or {}
    ok = bool(res.get("chunks", 0))
    state["reflection"] = {"ok": ok}
    return state

def _emit(state: AgentState) -> AgentState:
    res = state.get("act_result") or {}
    oid = (state.get("input") or {}).get("object_id")
    out = {"event": "ingest.chunk.done", "object_id": oid, "chunks": int(res.get("chunks", 0))}
    state["output"] = out
    audit_log(object_id=oid, agent=AGENT, action="emit", trace_id=state.get("trace_id"), details=out)
    return state

SPEC = PERSpec(name=AGENT, plan=_plan, act=_act, reflect=_reflect, emit=_emit)
GRAPH = build_graph(SPEC)

def invoke(object_id: str, *, trace_id: str, max_tokens: int = 800, overlap: int = 120, strategy: str = "heading_first") -> dict[str, Any]:
    state: AgentState = {"trace_id": trace_id, "input": {"object_id": object_id, "max_tokens": max_tokens, "overlap": overlap, "strategy": strategy}}
    return dict(GRAPH.invoke(state))
