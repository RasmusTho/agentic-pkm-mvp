from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterable

import duckdb

from .models import AgentState, ContextItem

DB_PATH = "storage/agent.duckdb"
PROV_JSONL = "provenance.jsonl"


def _conn():
    Path("storage").mkdir(parents=True, exist_ok=True)
    return duckdb.connect(DB_PATH, read_only=False)


def hydrate(state: AgentState) -> AgentState:
    ctx: list[ContextItem] = []
    folder = Path("data/context")
    if folder.exists():
        for p in folder.glob("*.json"):
            d = json.loads(p.read_text(encoding="utf-8"))
            ctx.append(ContextItem(**d))
    try:
        with _conn() as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS context(id TEXT, text TEXT, tags LIST(TEXT), source TEXT, loaded_at TIMESTAMP)"
            )
            rows = con.execute("SELECT id, text, tags, source FROM context").fetchall()
            for r in rows:
                ctx.append(ContextItem(id=r[0], text=r[1], tags=list(r[2] or []), source=r[3] or "duckdb"))
    except duckdb.Error:
        pass
    state.ctx = ctx
    return state


def reason(state: AgentState) -> AgentState:
    if not state.ctx:
        state.result = "No context available."
        state.cites = []
        return state
    used: Iterable[ContextItem] = state.ctx[:5]
    text = "\n".join(ci.text for ci in used)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    state.result = (lines[0] if lines else "")[:800]
    state.cites = [ci.id for ci in used]
    return state


def guard(state: AgentState) -> AgentState:
    if state.profile == "work" and state.result:
        for w in ["hälsa", "diagnos", "privat", "familj"]:
            state.result = state.result.replace(w, "▇▇")
    return state


def log(state: AgentState) -> AgentState:
    ts = int(time.time())
    meta = {"cites": state.cites, "profile": state.profile}
    with _conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS provenance(
              run_id TEXT, agent TEXT, action TEXT,
              input_ref TEXT, output_ref TEXT, ts TIMESTAMP, meta JSON
            )
        """
        )
        con.execute(
            "INSERT INTO provenance VALUES (?, ?, ?, ?, ?, now(), ?)",
            (state.run_id, "agent.mvp", "reason", "ctx:fixtures", f"output:{state.run_id}", json.dumps(meta)),
        )
    with open(PROV_JSONL, "a", encoding="utf-8") as f:
        f.write(json.dumps({"run_id": state.run_id, "ts": ts, "meta": meta}) + "\n")
    return state


def feedback(state: AgentState) -> AgentState:
    if state.feedback is None:
        return state
    with _conn() as con:
        con.execute("CREATE TABLE IF NOT EXISTS feedback(run_id TEXT, verdict TEXT, notes TEXT, ts TIMESTAMP)")
        verdict = "accept" if state.feedback.lower().startswith("a") else "edit"
        con.execute("INSERT INTO feedback VALUES (?, ?, ?, now())", (state.run_id, verdict, state.feedback))
    return state
