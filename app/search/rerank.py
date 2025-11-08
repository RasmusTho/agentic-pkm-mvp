from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List


@dataclass(frozen=True)
class ScoredHit:
    object_id: Any
    text: str
    score: float
    payload: Dict[str, Any]


class HeuristicReranker:
    """
    Infra-friendly placeholder reranker.

    Deterministic ordering rule:
    1) Token-overlap count with the query (desc)
    2) Original score (desc)
    3) Original input order (asc)

    This keeps behavior stable for tests while being easy to replace
    with an AI reranker behind the same interface later.
    """

    def rerank(self, query: str, hits: Iterable[ScoredHit], k: int = 5) -> List[ScoredHit]:
        q_tokens = _tokens(query)
        indexed = list(enumerate(hits))  # (idx, ScoredHit)

        def key(item):
            i, h = item
            overlap = len(q_tokens & _tokens(h.text))
            # Sort by: overlap desc, score desc, original index asc
            return (-overlap, -float(h.score or 0.0), i)

        ranked = [h for _, h in sorted(indexed, key=key)]
        return ranked[: (k if k is not None else 5)]


def _tokens(text: str) -> set[str]:
    if not text:
        return set()
    # Super simple tokenization for infra tests
    return {t for t in text.lower().split() if t}
