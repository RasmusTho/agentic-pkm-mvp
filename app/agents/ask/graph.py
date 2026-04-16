from __future__ import annotations

from typing import Any, Iterable, List, Optional

from langgraph.graph import END, START, StateGraph

from app.agents.ask.state import AgentState, RetrievedHit
from app.agents.ask.utils import build_ask_context, get_ask_settings, llm_answer, reasoning_enabled, score_hit
from app.components.rerankers import get_reranker
from app.retrieval.hybrid import hybrid_search

TOP_K_INITIAL = 40


def _to_retrieved_hit(hit: dict[str, Any], ask_score: float | None = None) -> RetrievedHit:
    payload = hit.get("payload") or {}
    return RetrievedHit(
        object_id=str(hit.get("id") or hit.get("doc_id") or payload.get("uuid") or ""),
        score=float(hit.get("score") or 0.0),
        ask_score=ask_score,
        origin=payload.get("origin") or None,
        zone=None,  # Zone is derived, not read from stored payload
        trust=payload.get("trust") or None,
        title=payload.get("title") or hit.get("title"),
        path=hit.get("source_ref") or payload.get("source_ref"),
        snippet=hit.get("snippet") or hit.get("text"),
        payload=payload,
    )


def _retrieve_node(state: AgentState, *, k: int, ask_settings) -> AgentState:
    hits = hybrid_search(state.query, k=k)
    enriched: list[RetrievedHit] = []
    for hit in hits:
        ask_score = score_hit(hit)
        enriched.append(_to_retrieved_hit(hit, ask_score=ask_score))
    state.hits = enriched
    return state


def _rerank_node(state: AgentState, *, ask_settings) -> AgentState:
    if not state.hits:
        return state
    reranker = get_reranker()
    # Order by ask_score first (if present); otherwise use reranker
    sorted_hits = sorted(state.hits, key=lambda h: (h.ask_score if h.ask_score is not None else 0.0), reverse=True)

    class _RRItem:
        def __init__(self, id: str, text: str):
            self.id = id
            self.text = text

    if reranker:
        rr_items = [
            _RRItem(
                h.object_id,
                h.snippet or h.payload.get("text") or h.payload.get("raw_text") or "",
            )
            for h in sorted_hits
        ]
        try:
            results = reranker.rerank(state.query, rr_items, top_k=None)  # type: ignore[arg-type]
            order = {res.id: idx for idx, res in enumerate(results)}
            sorted_hits = sorted(sorted_hits, key=lambda h: order.get(h.object_id, len(order)))
        except Exception:
            pass

    top_k_llm = max(1, int(ask_settings.max_context_docs or 10))
    state.hits = sorted_hits[:top_k_llm]
    return state


def _answer_node(state: AgentState, *, ask_settings) -> AgentState:
    if not state.hits:
        state.answer = "No results found."
        return state
    # Default answer: snippet/text of top hit
    top = state.hits[0]
    fallback = (top.snippet or top.payload.get("text") or top.payload.get("raw_text") or "").strip()
    answer_text = fallback or "No results found."

    if reasoning_enabled():
        context = build_ask_context(state.query, [h.model_dump() for h in state.hits], ask_settings)
        llm, route = llm_answer(state.query, context, ask_settings)
        if llm:
            answer_text = llm
        if route:
            state.llm_route = route

    state.answer = answer_text
    return state


def build_ask_graph(ask_settings=None):
    ask_settings = ask_settings or get_ask_settings()
    graph = StateGraph(AgentState)
    graph.add_node("retrieve", lambda s: _retrieve_node(s, k=TOP_K_INITIAL, ask_settings=ask_settings))
    graph.add_node("rerank", lambda s: _rerank_node(s, ask_settings=ask_settings))
    graph.add_node("answer", lambda s: _answer_node(s, ask_settings=ask_settings))

    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "rerank")
    graph.add_edge("rerank", "answer")
    graph.add_edge("answer", END)
    return graph.compile()


def run_ask_graph(query: str, trace_id: Optional[str] = None, ask_settings=None) -> AgentState:
    ask_settings = ask_settings or get_ask_settings()
    compiled = build_ask_graph(ask_settings)
    initial = AgentState(trace_id=trace_id, query=query, hits=[])
    result = compiled.invoke(initial)
    if isinstance(result, AgentState):
        return result
    try:
        return AgentState.model_validate(result)
    except Exception:
        # Best-effort fallback if graph returned a plain dict
        return AgentState(trace_id=trace_id, query=query, hits=[], answer=None)


__all__ = ["run_ask_graph", "build_ask_graph", "TOP_K_INITIAL"]
