from app.store.vector_index import VectorIndex, ScoredNeighbor

def test_vector_index_interface_shape():
    vi = VectorIndex
    assert hasattr(vi, "upsert_embedding")
    assert hasattr(vi, "similar")
    assert hasattr(vi, "search_by_text")

    sn = ScoredNeighbor(uuid="x", score=1.0)
    assert sn.uuid == "x"
    assert sn.score == 1.0
