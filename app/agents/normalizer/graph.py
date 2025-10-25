from __future__ import annotations
from typing import Any
import os, uuid
import psycopg
from psycopg.rows import dict_row
from app.agents.base.graph import PERSpec, build_graph, AgentState
from app.agents.base.audit import audit_log
from app.agents.base.memory import remember
from app.agents.normalizer.agent import run as normalizer_run

AGENT = "normalizer"

def _dsn() -> str:
    return (os.environ.get("DATABASE_URL") or "postgresql+psycopg://app:app@127.0.0.1:15432/app").replace("postgresql+psycopg://","postgresql://")

def _fetch_core6(object_id: str | None) -> dict:
    if not object_id:
        return {}
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, payload FROM objects WHERE id=%s LIMIT 1", (uuid.UUID(object_id),))
            row = cur.fetchone()
            if not row:
                return {}
            p = row["payload"] or {}
            c6 = p.get("core6") or {}
            if c6:
                return c6
            keys = ["id","type","title","created","updated","origin"]
            out = {}
            for k in keys:
                if k == "id":
                    out["id"] = str(row["id"])
                else:
                    v = p.get(k)
                    if v is not None:
                        out[k] = v
            return out

def _plan(state: AgentState) -> AgentState:
    inp = state.get("input", {})
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
    oid = res.get("object_id")
    if oid:
        remember(agent=AGENT, key="last_normalize", value={"ok": ok}, scope_object_id=oid, ttl_seconds=86400)
    return state

def _emit(state: AgentState) -> AgentState:
    res = state.get("act_result", {})
    oid = res.get("object_id")
    core6 = res.get("core6") or _fetch_core6(oid)
    out = {"event": "ingest.normalize.done", "object_id": oid, "core6": core6}
    state["output"] = out
    audit_log(object_id=oid, agent=AGENT, action="emit", trace_id=state.get("trace_id"), details=out)
    return state

SPEC = PERSpec(name=AGENT, plan=_plan, act=_act, reflect=_reflect, emit=_emit)
GRAPH = build_graph(SPEC)

def invoke(path: str, *, trace_id: str) -> dict[str, Any]:
    state: AgentState = {"trace_id": trace_id, "input": {"path": path}}
    return dict(GRAPH.invoke(state))
