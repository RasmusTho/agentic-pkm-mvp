from __future__ import annotations

import os
from typing import Any, Dict, List

from app.retrieval.hybrid_rerank_hook import apply_optional_rerank


def maybe_rerank(query: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    flag = os.getenv("RERANK_ENABLE", "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return apply_optional_rerank(query, items)
    return items
