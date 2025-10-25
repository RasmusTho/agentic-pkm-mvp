from __future__ import annotations
import os
from pathlib import Path
import psycopg
from psycopg.rows import dict_row

from app.agents.normalizer.graph import invoke as normalize_invoke
from app.agents.classifier.graph import invoke as classify_invoke
from app.agents.chunker.graph import invoke as chunk_invoke
from app.agents.deduper.graph import invoke as dedupe_invoke
from app.agents.indexer.graph import invoke as index_invoke
from app.agents.citation_checker.agent import run as citation_run
from app.agents.reviewer.graph import invoke as review_invoke

def _dsn() -> str:
    return (os.environ.get("DATABASE_URL") or "postgresql+psycopg://app:app@127.0.0.1:15432/app").replace("postgresql+psycopg://","postgresql://")

def _count(sql: str, *params) -> int:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return int(list(cur.fetchone().values())[0])

def test_e2e_pipe(tmp_path: Path):
    trace_id = "t-e2e-graph-1"
    os.environ.setdefault("LLM_PROVIDER", "mock")
    os.environ.setdefault("LLM_MOCK_RESPONSE", '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}')
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    c = tmp_path / "c.md"
    a.write_text("# Title\n\nAccording to the 2023 report, vector search adoption grew 25% last year.\nIt references pgvector and BM25 without citing sources.\n")
    b.write_text("Title\n\nAccording to the 2023 report, vector search adoption grew 25% last year.\nIt references pgvector and bm25!\nSee https://example.org/report.\n")
    c.write_text("# Different\n\nA totally different topic about LangGraph and PER loops.\n")

    r1 = normalize_invoke(str(a), trace_id=trace_id)
    r2 = normalize_invoke(str(b), trace_id=trace_id)
    r3 = normalize_invoke(str(c), trace_id=trace_id)

    oids = [r1["output"]["object_id"], r2["output"]["object_id"], r3["output"]["object_id"]]
    assert all(oids)
    assert all(r["output"]["core6"].get("id") for r in [r1,r2,r3])

    for oid in oids:
        cr = classify_invoke(oid, trace_id=trace_id)
        assert cr["output"]["event"] == "curation.classify.done"

    for oid in oids:
        ch = chunk_invoke(oid, trace_id=trace_id, max_tokens=800, overlap=120, strategy="heading_first")
        assert ch["output"]["event"] == "ingest.chunk.done"
        assert ch["output"]["chunks"] >= 1

    dres = dedupe_invoke(oids[:2], trace_id=trace_id, threshold=0.85)
    assert dres["output"]["event"] == "curation.dedupe.done"
    assert isinstance(dres["output"]["pairs"], list)

    for oid in oids:
        citation_run(oid, trace_id=trace_id)

    reviews = []
    for oid in oids:
        ix = index_invoke(oid, trace_id=trace_id)
        assert ix["output"]["event"] == "ingest.index.done"
        assert ix["output"]["embeddings"] >= 1
        rv = review_invoke(oid, trace_id=trace_id, threshold=0.75)
        assert rv["output"]["event"] == "curation.review.done"
        reviews.append(rv["output"])

    n_objects = _count("SELECT COUNT(*) FROM objects")
    n_chunks = _count("SELECT COUNT(*) FROM chunks")
    n_audit = _count("SELECT COUNT(*) FROM audit WHERE trace_id=%s", trace_id)
    n_dup_decisions = _count("SELECT COUNT(*) FROM decisions WHERE key='duplicate_of'")
    n_emb = _count("SELECT COUNT(*) FROM embeddings")

    n_review_decisions = _count("SELECT COUNT(*) FROM decisions WHERE key='review'")

    assert n_objects >= 3
    assert n_chunks >= 3
    assert any(r["allow"] for r in reviews)
    assert any(not r["allow"] for r in reviews)

    assert n_audit >= 6
    assert n_dup_decisions >= 0
    assert n_emb >= len(oids)
    assert n_review_decisions >= len(oids)
    for oid in oids:
        per_obj = _count("SELECT COUNT(*) FROM embeddings WHERE object_id=%s", oid)
        assert per_obj >= 1
