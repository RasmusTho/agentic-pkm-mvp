from __future__ import annotations

from typing import Any, Dict, List

from app.retrieval.hybrid_rerank_hook import apply_optional_rerank
from app.retrieval.tuning import get_retrieval_tuning


def maybe_rerank(query: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rerank gate (ADR-0059 D3, #3404): reads the process-resolved RetrievalTuning surface.

    ``RERANK_ENABLE`` keeps working as an override into that surface (compat) — see
    ``app.retrieval.tuning``. ``rerank="conditional"`` cannot reach here: resolution already raises
    for it before a config value is returned.
    """
    tuning = get_retrieval_tuning()
    if tuning.rerank != "always":
        return items
    return apply_optional_rerank(query, items)
