import os
from pathlib import Path
import psycopg
from psycopg.rows import dict_row

def _dsn():
    v = os.environ.get("DATABASE_URL") or "postgresql+psycopg://app:app@127.0.0.1:15432/app"
    return v.replace("postgresql+psycopg://", "postgresql://")

def _fetch_chunks(oid: str) -> list[dict]:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT object_id, idx, offset_start, offset_end, text FROM chunks WHERE object_id=%s ORDER BY idx",
                (oid,),
            )
            return cur.fetchall() or []

def test_chunker_heading_and_fallback(tmp_path):
    from app.agents.normalizer.agent import run as normalize_run
    from app.agents.chunker.agent import run as chunk_run

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
    assert res1["chunks"] == len(rows1) >= 1

    starts = [r["offset_start"] for r in rows1]
    assert starts == sorted(starts)

    joined = " ".join(r["text"] for r in rows1)
    assert "Del 1" in joined and "Del 2" in joined
