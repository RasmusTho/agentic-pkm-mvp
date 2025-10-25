from app.search.bm25_lite import BM25Lite

def test_bm25_basic_rank():
    bm = BM25Lite()
    bm.add("a", "The quick brown fox jumps over the lazy dog")
    bm.add("b", "Neural retrieval with embeddings and vector search")
    bm.add("c", "Crows and ravens are corvids; corvid cognition is remarkable")
    hits = bm.query("vector retrieval", k=2)
    ids = [h[0] for h in hits]
    assert "b" in ids

def test_bm25_idempotent_add():
    bm = BM25Lite()
    bm.add("x", "hello world hello")
    before = bm.N
    bm.add("x", "hello world hello")
    assert bm.N == before
