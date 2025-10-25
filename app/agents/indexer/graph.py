from __future__ import annotations
from langgraph.graph import StateGraph, END
from typing import TypedDict
from app.agents.indexer.agent import run as index_run

class S(TypedDict, total=False):
    object_id: str
    trace_id: str
    output: dict

def _plan(s: S) -> S:
    return s

def _act(s: S) -> S:
    res = index_run(s["object_id"], trace_id=s["trace_id"])
    s["output"] = {"event": "ingest.index.done", "embeddings": res.get("embeddings", 0), "object_id": s["object_id"]}
    return s

def _reflect(s: S) -> S:
    return s

def invoke(object_id: str, *, trace_id: str) -> dict:
    g = StateGraph(S)
    g.add_node("plan", _plan)
    g.add_node("act", _act)
    g.add_node("reflect", _reflect)
    g.set_entry_point("plan")
    g.add_edge("plan", "act")
    g.add_edge("act", "reflect")
    g.add_edge("reflect", END)
    app = g.compile()
    out = app.invoke({"object_id": object_id, "trace_id": trace_id})
    return out
