from __future__ import annotations
from typing import Dict, List
from app.search.rerank import HeuristicReranker, ScoredHit

def _dummy_hits() -> List[ScoredHit]:
    return [
        ScoredHit(object_id=1, text="The quick brown fox", score=0.5, payload={}),
        ScoredHit(object_id=2, text="Lazy dog jumps", score=0.4, payload={}),
    ]

def retrieve(state: Dict) -> Dict:
    state["hits"] = _dummy_hits()
    return state

def rerank(state: Dict) -> Dict:
    hits = state.get("hits", [])
    q = state.get("query", "")
    r = HeuristicReranker()
    state["hits"] = r.rerank(q, hits, k=2)
    return state

def answer(state: Dict) -> Dict:
    hits = state.get("hits") or []
    if not hits:
        state["answer"] = "No results."
        return state
    top = hits[0]
    state["answer"] = f"Best match: {top.text}"
    return state
