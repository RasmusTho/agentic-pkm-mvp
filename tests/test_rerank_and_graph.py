from __future__ import annotations
from app.search.rerank import HeuristicReranker, ScoredHit
from app.agents.graph.runner import run_graph
from app.agents.graph import nodes_basic as nb

import pytest
@pytest.mark.skip(reason='Reranker ersätts av AI; vi testar bara infrastrukturen')
def test_heuristic_reranker_orders_by_overlap():
    hits = [
        ScoredHit(object_id=1, text="red fox", score=0.4, payload={}),
        ScoredHit(object_id=2, text="blue whale", score=0.5, payload={}),
    ]
    r = HeuristicReranker()
    ranked = r.rerank("fox", hits, k=2)
    assert ranked[0].text == "red fox"

def test_graph_flow_yields_answer():
    state = {"query": "fox"}
    final = run_graph(state, [nb.retrieve, nb.rerank, nb.answer])
    assert "Best match:" in final["answer"]
