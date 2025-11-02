from __future__ import annotations
from pathlib import Path
from app.agents.normalizer.graph import invoke as normalize_invoke
from app.agents.classifier.graph import invoke as classify_invoke
from app.agents.chunker.graph import invoke as chunk_invoke
from app.agents.indexer.graph import invoke as index_invoke

def test_indexer_builds_embeddings_and_fts(tmp_path: Path):
    trace_id = "t-index-1"
    p = tmp_path / "note.md"
    p.write_text("# BM25 Vector\n\nThis note mentions pgvector and embeddings so we can index chunks.")
    r = normalize_invoke(str(p), trace_id=trace_id)
    oid = r["output"]["object_id"]
    classify_invoke(oid, trace_id=trace_id)
    ch = chunk_invoke(oid, trace_id=trace_id, max_tokens=200, overlap=40, strategy="heading_first")
    assert ch["output"]["chunks"] >= 1
    ix = index_invoke(oid, trace_id=trace_id)
    assert ix["output"]["event"] == "ingest.index.done"
    assert ix["output"]["embeddings"] >= 1
