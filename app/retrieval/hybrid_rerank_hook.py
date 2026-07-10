from __future__ import annotations

from typing import Any, Dict, List

from app.components.rerankers import get_reranker
from app.retrieval.rerank import RerankItem
from app.retrieval.tuning import get_retrieval_tuning


def apply_optional_rerank(query: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Apply the optional rerank hook, gated and sized by the process-resolved RetrievalTuning
    surface (ADR-0059 D3, #3404/#3407). ``RERANK_ENABLE``/``RERANK_TOP_K`` keep working as
    overrides into that surface (compat); ``RERANK_PROVIDER`` continues to select the reranker
    implementation directly via :func:`app.components.rerankers.get_reranker` (untouched —
    provider selection is not part of the D3 config shape).

    This function always applies the hook once called; the WHETHER-to-call decision (including the
    ``"conditional"`` score-margin gate) lives in ``app/retrieval/hook_adapter.py::maybe_rerank``,
    the sole production caller. The only local guard here is ``rerank="off"`` — kept so direct
    callers (tests, other consumers) get the same inert-by-default behavior without duplicating the
    gate logic."""
    tuning = get_retrieval_tuning()
    if tuning.rerank == "off":
        return items
    top_k = tuning.rerank_top_k
    reranker = get_reranker()
    rr_items = [
        RerankItem(
            id=str(it.get("id")),
            text=str(it.get("text", "")),
            vec=it.get("vec"),
            meta={k: v for k, v in it.items() if k not in {"id", "text", "vec"}},
        )
        for it in items
    ]
    results = reranker.rerank(query, rr_items, top_k=top_k)
    by_id = {str(it.get("id")): it for it in items}
    reordered = [by_id[r.id] for r in results if r.id in by_id]
    seen = {r.id for r in results}
    tail = [it for it in items if str(it.get("id")) not in seen]
    return reordered + tail
