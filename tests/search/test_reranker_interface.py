from __future__ import annotations
from app.search.rerank import HeuristicReranker, ScoredHit

def test_reranker_interface_contract() -> None:
    hits = [
        ScoredHit(object_id=1, text="alpha", score=0.1, payload={"x": 1}),
        ScoredHit(object_id=2, text="beta",  score=0.9, payload={"x": 2}),
    ]
    r = HeuristicReranker()
    out = r.rerank("query", hits, k=1)
    # Infrastruktur-kontrakt: lista, <= k items, fält finns kvar
    assert isinstance(out, list)
    assert len(out) <= 1
    h = out[0]
    assert hasattr(h, "object_id") and hasattr(h, "text") and hasattr(h, "score") and hasattr(h, "payload")
