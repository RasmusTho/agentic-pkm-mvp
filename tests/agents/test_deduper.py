import os
import psycopg
from psycopg.rows import dict_row
from app.agents.normalizer.agent import run as normalize_run
from app.agents.deduper.agent import run as dedupe_run

def _dsn():
    return os.environ["DATABASE_URL"].replace("postgresql+psycopg://","postgresql://")

def _fetch_decisions(oid: str):
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT key, value FROM decisions WHERE object_id=%s ORDER BY created_at DESC", (oid,))
            return cur.fetchall()

def test_deduper_marks_duplicate(tmp_path):
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text("# Title\n\nThis is a short note about vector search and embeddings.\nIt references pgvector and BM25.\n")
    b.write_text("Title\n\nThis is a short note about vector search and embeddings.\nIt references pgvector and bm25!\n")

    ra = normalize_run(str(a), trace_id="t-dedupe-1")
    rb = normalize_run(str(b), trace_id="t-dedupe-1")
    oids = [ra["object_id"], rb["object_id"]]

    res = dedupe_run(oids, threshold=0.90, trace_id="t-dedupe-1")
    assert res["decisions"] >= 1
    pairs = res["pairs"]
    assert any(len(p) == 3 for p in pairs)

    dup = None
    for oi, oj, s in pairs:
        dup = oj
        break
    rows = _fetch_decisions(dup)
    assert any(r["key"] == "duplicate_of" for r in rows)
