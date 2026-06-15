from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable, List, Optional

from langgraph.graph import END, START, StateGraph

from app.agent_memory.recall_activation import activate_guarded_recall
from app.agent_memory.recall_explanation import (
    ActivationReason,
    RecallUseRight,
    render_recall_footer,
)
from app.agent_memory.recall_retrieval import RecallCandidate, retrieve_relevant_promoted
from app.agents.ask.state import AgentState, RetrievedHit
from app.agents.ask.utils import build_ask_context, get_ask_settings, llm_answer, reasoning_enabled, score_hit
from app.components.rerankers import get_reranker
from app.retrieval.capability import RetrievalRequest, retrieve
from app.vault.manager import get_vault_manager

TOP_K_INITIAL = 40
RECALL_TOP_K = 3
DEFAULT_RECALL_RECEIPTS_PATH = Path("runtime/agent_memory/recall_receipts.jsonl")


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
    response = retrieve(RetrievalRequest(query=state.query, k=k, trace_id=state.trace_id))
    enriched: list[RetrievedHit] = []
    for retrieval_hit in response.hits:
        hit = retrieval_hit.to_hybrid_dict()
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


def _recall_receipt_path() -> Path:
    configured = os.getenv("RECALL_RECEIPTS_PATH")
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_RECALL_RECEIPTS_PATH


def _active_recall_vault_root() -> Path | None:
    context = get_vault_manager().context
    if context.status == "selected" and context.active_vault_path:
        return Path(context.active_vault_path).expanduser().resolve()
    env_root = os.getenv("VAULT_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    return None


def _source_artifact_path(candidate: RecallCandidate, vault_root: Path | None) -> Path | None:
    if not candidate.artifact_path:
        return None
    if not vault_root:
        return None
    return vault_root / candidate.artifact_path


def _recall_node(state: AgentState, *, ask_settings) -> AgentState:
    vault_root = _active_recall_vault_root()
    candidates = retrieve_relevant_promoted(state.query, k=RECALL_TOP_K, vault_root=vault_root)
    if not candidates:
        state.recalled = []
        return state

    recalled = []
    recalled_content: dict[str, str] = {}
    reasoning = list(state.reasoning or [])
    receipt_path = _recall_receipt_path()
    for candidate in candidates:
        guarded = activate_guarded_recall(
            candidate.promoted,
            use_right=RecallUseRight.ACTIVATABLE,
            activation_reason=ActivationReason.CONTEXTUAL_RELEVANCE,
            why_now=candidate.reason,
            receipt_path=receipt_path,
            source_artifact_path=_source_artifact_path(candidate, vault_root),
        )
        if guarded.may_answer:
            recalled.append(guarded.explanation)
            content = (candidate.promoted.candidate.content or "").strip()
            if content:
                recalled_content[guarded.explanation.artifact_id] = content
            reasoning.append(
                f"recall:{guarded.memory_id}:{guarded.explanation.title}:{candidate.reason}"
            )

    state.recalled = recalled
    state.recalled_content = recalled_content
    if reasoning:
        state.reasoning = reasoning
    return state


def _recall_only_fallback(state: AgentState) -> str:
    """Compose a minimal non-reasoning answer from recalled memory alone.

    Recalled memory stays supporting input only — this surfaces the recalled
    fact without claiming retrieval authority. Used when retrieval returned
    zero hits but guarded recall yielded a usable may_answer memory and
    reasoning is disabled.

    Prefer the recalled memory body (the actual fact); fall back to the title
    and, only if no content is available, the recall match reason.
    """
    top = state.recalled[0]
    title = (top.title or "").strip()
    content = (state.recalled_content.get(top.artifact_id) or "").strip()
    if content:
        return f"{title}: {content}" if title else content
    why = (top.why_now or "").strip()
    if title and why:
        return f"{title}: {why}"
    return title or why


def _answer_node(state: AgentState, *, ask_settings) -> AgentState:
    if not state.hits and not state.recalled:
        # Preserve the fallback only when neither retrieval nor recall produced context.
        state.answer = "No results found."
        return state

    if state.hits:
        # Default answer: snippet/text of top hit
        top = state.hits[0]
        fallback = (top.snippet or top.payload.get("text") or top.payload.get("raw_text") or "").strip()
    else:
        # Recall-only path: retrieval was empty but guarded recall found supporting memory.
        fallback = _recall_only_fallback(state)
    answer_text = fallback or "No results found."

    if reasoning_enabled():
        context = build_ask_context(
            state.query,
            [h.model_dump() for h in state.hits],
            ask_settings,
            recalled=state.recalled,
        )
        llm, route = llm_answer(state.query, context, ask_settings)
        if llm:
            answer_text = llm
        if route:
            state.llm_route = route

    # Treatment A (#1972): when recall fired, attribute it with a footer keyed to
    # the recall receipt — outside the answer prose, never shown when recall is empty.
    footer = render_recall_footer(state.recalled or [])
    state.answer = f"{answer_text}\n\n{footer}" if footer else answer_text
    return state


def build_ask_graph(ask_settings=None):
    ask_settings = ask_settings or get_ask_settings()
    graph = StateGraph(AgentState)
    graph.add_node("retrieve", lambda s: _retrieve_node(s, k=TOP_K_INITIAL, ask_settings=ask_settings))
    graph.add_node("rerank", lambda s: _rerank_node(s, ask_settings=ask_settings))
    graph.add_node("recall", lambda s: _recall_node(s, ask_settings=ask_settings))
    graph.add_node("answer", lambda s: _answer_node(s, ask_settings=ask_settings))

    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "rerank")
    graph.add_edge("rerank", "recall")
    graph.add_edge("recall", "answer")
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
