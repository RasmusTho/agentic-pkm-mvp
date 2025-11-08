from __future__ import annotations
from dataclasses import dataclass
from typing import List, Any

@dataclass
class ScoredHit:
    object_id: Any
    text: str
    score: float
    payload: dict

class Reranker:
    """Base reranker interface."""
    def rerank(self, query: str, hits: List[ScoredHit], k: int = 5) -> List[ScoredHit]:
        raise NotImplementedError

class HeuristicReranker(Reranker):
    """Toy model: prefer docs whose text shares more tokens with query."""
    def rerank(self, query: str, hits: List[ScoredHit], k: int = 5) -> List[ScoredHit]:
        q_tokens = set((query or "").lower().split())
        scored = []
        for h in hits:
            text = (h.text or "")
            doc_tokens = set(text.lower().split())
            overlap = len(q_tokens & doc_tokens)
            # bump score slightly per token overlap
            h.score = float(h.score) + 0.01 * overlap
            scored.append(h)
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:k]
