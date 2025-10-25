from __future__ import annotations
import os
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from app.agents.normalizer.graph import invoke as normalize_invoke
from app.agents.classifier.graph import invoke as classify_invoke
from app.agents.chunker.graph import invoke as chunk_invoke
from app.agents.indexer.graph import invoke as index_invoke

def _dsn() -> str:
    return (os.environ.get("DATABASE_URL") or "postgresql+psycopg://app:app@127.0.0.1:15432/app").replace("postgresql+psycopg://","postgresql://")

def _count(sql: str, *params) -> int:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return int(list(cur.fetchone().values())[0])

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
    n_chunks = _count("SELECT COUNT(*) FROM chunks WHERE object_id=%s", oid)
    n_emb = _count("SELECT COUNT(*) FROM embeddings WHERE object_id=%s", oid)
    assert n_emb >= n_chunks
    n_hits = _count("SELECT COUNT(*) FROM objects WHERE id=%s AND search_vector @@ plainto_tsquery('english','pgvector')", oid)
    assert n_hits == 1
