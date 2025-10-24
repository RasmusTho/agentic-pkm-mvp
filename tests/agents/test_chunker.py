import os
import psycopg
from psycopg.rows import dict_row
from app.agents.normalizer.agent import run as normalize_run
from app.agents.chunker.agent import run as chunk_run

def _dsn():
    return os.environ["DATABASE_URL"].replace("postgresql+psycopg://","postgresql://")

def _fetch_chunks(oid: str):
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT idx, offset_start, offset_end, text FROM chunks WHERE object_id=%s ORDER BY idx ASC", (oid,))
            return cur.fetchall()

def test_chunker_heading_and_fallback(tmp_path):
    text = """# Titel
Det här är en inledning. Den har några meningar som bör hållas ihop för semantik.

## Del 1
Detta är ett längre avsnitt som ska chunkas. Här kommer flera meningar i rad för att forcera fallback vid max_tokens. Vi vill undvika att bryta mitt i meningar när det går. Detta är ytterligare en mening. Och en till. Slutligen ännu en mening för att överskrida gränsen lite grand.

## Del 2
Kort stycke.
"""
    src = tmp_path / "note.md"
    src.write_text(text)
    norm = normalize_run(str(src), trace_id="t-chunk-1")
    oid = norm["object_id"]

    res1 = chunk_run(oid, max_tokens=50, overlap=10, strategy="heading_first", trace_id="t-chunk-1")
    rows1 = _fetch_chunks(oid)
    assert res1["count"] == len(rows1) and res1["count"] > 1
    for r in rows1:
        assert 0 <= r["offset_start"] < r["offset_end"] <= len(text)
        sub = text[r["offset_start"]:r["offset_end"]]
        assert sub == r["text"]

    res2 = chunk_run(oid, max_tokens=50, overlap=10, strategy="heading_first", trace_id="t-chunk-1")
    rows2 = _fetch_chunks(oid)
    spans1 = [(r["offset_start"], r["offset_end"]) for r in rows1]
    spans2 = [(r["offset_start"], r["offset_end"]) for r in rows2]
    assert spans1 == spans2
