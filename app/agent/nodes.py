from __future__ import annotations

import json
import time
from collections.abc import Iterable
from pathlib import Path

import duckdb

from app.components.embeddings import get_embedding_client
from app.search.service import search_hybrid

from .models import AgentState, ContextItem

DB_PATH = "storage/agent.duckdb"
PROV_JSONL = "provenance.jsonl"


def _conn() -> duckdb.DuckDBPyConnection:
    Path("storage").mkdir(parents=True, exist_ok=True)
    return duckdb.connect(DB_PATH, read_only=False)


def hydrate(state: AgentState) -> AgentState:
    ctx: list[ContextItem] = []
    folder = Path("data/context")
    if folder.exists():
        for path in folder.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(data, dict) and {"id", "text"}.issubset(data):
                try:
                    ctx.append(ContextItem(**data))
                except ValueError:
                    continue
    state.ctx = ctx
    return state


def reason(state: AgentState) -> AgentState:
    if state.task == "recall":
        return _recall_documents(state)
    return _summarize_context(state)


def _recall_documents(state: AgentState) -> AgentState:
    query = (state.user_input or "").strip()
    if not query:
        state.result = "Ingen sökfråga angiven."
        state.cites = []
        state.ctx = []
        return state

    client = get_embedding_client("deterministic")
    try:
        embedding = client.embed_text(query)
    except ValueError:
        state.result = "Frågan kunde inte embedas."
        state.cites = []
        state.ctx = []
        return state

    hits = search_hybrid(query, embedding, k=5)
    if not hits:
        state.result = f"Inga träffar för: {query}"
        state.cites = []
        state.ctx = []
        return state

    ctx_items: list[ContextItem] = []
    lines: list[str] = []
    for hit in hits:
        title = hit.payload.get("title") or str(hit.object_id)
        summary = hit.payload.get("text") or hit.payload.get("content", "")
        snippet = (summary or "")[:280]
        lines.append(f"{title} ({hit.score:.3f})\n{snippet}")
        ctx_items.append(
            ContextItem(
                id=str(hit.object_id),
                text=snippet,
                tags=[f"score:{hit.score:.3f}"],
                source="search",
            )
        )

    state.ctx = ctx_items
    state.result = "\n\n".join(lines)
    state.cites = [str(hit.object_id) for hit in hits]
    return state


def _summarize_context(state: AgentState) -> AgentState:
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
        for word in ["hälsa", "diagnos", "privat", "familj"]:
            state.result = state.result.replace(word, "▇▇")
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
            (
                state.run_id,
                "agent.mvp",
                "reason",
                "ctx:fixtures",
                f"output:{state.run_id}",
                json.dumps(meta),
            ),
        )
    with open(PROV_JSONL, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"run_id": state.run_id, "ts": ts, "meta": meta}) + "\n")
    return state


def feedback(state: AgentState) -> AgentState:
    if state.feedback is None:
        return state
    with _conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback(
              run_id TEXT,
              verdict TEXT,
              notes TEXT,
              ts TIMESTAMP
            )
            """
        )
        verdict = "accept" if state.feedback.lower().startswith("a") else "edit"
        con.execute(
            "INSERT INTO feedback VALUES (?, ?, ?, now())",
            (state.run_id, verdict, state.feedback),
        )
    return state
