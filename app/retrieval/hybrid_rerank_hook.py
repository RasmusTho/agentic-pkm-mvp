from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List

from app.retrieval.rerank import RerankItem, get_reranker


def apply_optional_rerank(query: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    flag = os.getenv("RERANK_ENABLE", "").strip().lower()
    if flag not in {"1", "true", "yes", "on"}:
        return items
    top_k_env = os.getenv("RERANK_TOP_K", "").strip()
    top_k = int(top_k_env) if top_k_env.isdigit() else None
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
