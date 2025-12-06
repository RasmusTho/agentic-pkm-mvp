from __future__ import annotations

from typing import Literal

from app.retrieval.rerank import BaseReranker
from app.retrieval.rerank.provider import get_reranker as _get_reranker
from app.search.rerank import HeuristicReranker, ScoredHit


class _HeuristicAdapter:
    def __init__(self) -> None:
        self._inner = HeuristicReranker()

    def rerank(self, query: str, items, top_k: int | None = None):  # type: ignore[override]
        # HeuristicReranker expects a `k` argument; adapt to the shared interface.
        return self._inner.rerank(query, items, k=top_k or 5)


def get_reranker(profile: Literal["balanced", "heuristic"] | str = "balanced") -> BaseReranker:
    """
    Retrieve the configured reranker.
    - balanced: current default cross-encoder selection (env-driven via RERANK_PROVIDER)
    - heuristic: lightweight in-process heuristic reranker (used in some agent demos/tests)
    """
    spec = (profile or "balanced").strip().lower()
    if spec == "heuristic":
        return _HeuristicAdapter()  # type: ignore[return-value]
    return _get_reranker()


__all__ = ["get_reranker", "ScoredHit"]
