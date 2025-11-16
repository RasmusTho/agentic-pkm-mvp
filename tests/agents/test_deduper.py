from app.events.types import CURATION_DEDUPE_DONE

import os
from app.agents.normalizer.agent import run as normalize_run
from app.agents.deduper.agent import run as dedupe_run

def test_deduper_marks_duplicate(tmp_path):
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text("# Title\n\nThis is a short note about vector search and embeddings.\nIt references pgvector and BM25.\n")
    b.write_text("Title\n\nThis is a short note about vector search and embeddings.\nIt references pgvector and bm25!\n")

    ra = normalize_run(str(a), trace_id="t-dedupe-1")
    rb = normalize_run(str(b), trace_id="t-dedupe-1")
    oids = [ra["object_id"], rb["object_id"]]

    res = dedupe_run(oids, threshold=0.90, trace_id="t-dedupe-1")
    assert res["event"] == CURATION_DEDUPE_DONE
    assert isinstance(res.get("pairs"), list)
    assert len(res["pairs"]) >= 1
    assert any(pair.get("duplicate") for pair in res["pairs"])
