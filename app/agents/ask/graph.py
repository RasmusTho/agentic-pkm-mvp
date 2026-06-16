from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Iterable, List, Optional

from langgraph.graph import END, START, StateGraph

from app.activation.ask_synthesis import emit_ask_synthesis_receipt, evaluate_ask_synthesis
from app.agent_memory.recall_activation import activate_guarded_recall
from app.agent_memory.recall_explanation import (
    ActivationReason,
    RecallUseRight,
    render_recall_footer,
)
from app.agent_memory.recall_retrieval import RecallCandidate, retrieve_relevant_promoted
from app.agents.ask.state import AgentState, RetrievedHit
from app.agents.ask.utils import build_ask_context, get_ask_settings, llm_answer, score_hit
from app.components.rerankers import get_reranker
from app.retrieval.capability import RetrievalRequest, retrieve
from app.vault.manager import get_vault_manager

logger = logging.getLogger(__name__)

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
        # Carry the full note body for LLM grounding (build_ask_context bounds it
        # by max_context_chars). Without this the synthesis context only ever
        # sees the short display snippet.
        text=hit.get("text") or payload.get("text") or payload.get("raw_text"),
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


def _synthesis_source_ids(state: AgentState) -> list[str]:
    """Stable ids for the retrieved/recalled context offered to the gate.

    These are the same ids surfaced as ASK sources, so the admitted set links
    the synthesized answer back to its grounded sources.
    """
    ids: list[str] = [h.object_id for h in state.hits if h.object_id]
    ids.extend(r.artifact_id for r in (state.recalled or []) if r.artifact_id)
    return ids


def _synthesis_source_paths(state: AgentState) -> dict[str, str]:
    paths: dict[str, str] = {}
    for hit in state.hits:
        if hit.object_id and hit.path:
            paths[hit.object_id] = str(hit.path)
    return paths


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

    # Expansion Activation Gate (#2026): ASK answer synthesis is now activated
    # THROUGH the deterministic admissibility gate (#2025) over the retrieved
    # context, not the raw REASONING_ENABLE env flag. When the gate admits, run
    # the existing run_reasoning(ASK_ANSWER) generation path and emit a
    # provenance-bearing activation receipt. When it blocks (or generation
    # yields nothing), preserve the existing literal-snippet fallback.
    source_ids = _synthesis_source_ids(state)
    decision = evaluate_ask_synthesis(source_ids)
    if decision.activatable:
        context = build_ask_context(
            state.query,
            [h.model_dump() for h in state.hits],
            ask_settings,
            recalled=state.recalled,
            recalled_content=state.recalled_content,
        )
        llm, route = llm_answer(state.query, context, ask_settings)
        if route:
            state.llm_route = route
        if llm:
            answer_text = llm
            receipt_id = emit_ask_synthesis_receipt(
                decision,
                answer_preview=llm,
                source_paths=_synthesis_source_paths(state),
                llm_route=route,
            )
            state.synthesis_receipt_id = receipt_id
            state.synthesis_source_ids = list(decision.admitted_artifact_ids)
        else:
            # Gate admitted but generation produced no answer: fall back to the
            # literal snippet with a logged reason. No receipt for a non-synthesis.
            logger.info(
                "ask.synthesis: gate admitted but generation returned no answer; "
                "falling back to literal snippet (capability=%s, admitted=%d)",
                decision.capability_id,
                len(decision.admitted_artifact_ids),
            )
    else:
        logger.info(
            "ask.synthesis: gate blocked synthesis; serving literal snippet "
            "(capability=%s, reasons=%s)",
            decision.capability_id,
            ",".join(decision.blocked_reasons) or "none",
        )

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
