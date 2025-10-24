import os, json
from psycopg.rows import dict_row
import psycopg
from app.agents.normalizer.agent import run as normalize_run
from app.agents.classifier.agent import run as classify_run

def _dsn():
    return os.environ["DATABASE_URL"].replace("postgresql+psycopg://","postgresql://")

def _fetch_decisions(oid: str):
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT key, value FROM decisions WHERE object_id=%s ORDER BY created_at DESC", (oid,))
            return cur.fetchall()

def test_classifier_fallback_and_trust(tmp_path, monkeypatch):
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["LLM_MOCK_RESPONSE"] = "UNSURE"
    src = tmp_path / "sample.md"
    src.write_text("# Titel\n\nDetta är en importerad text utan källor.\nLänk: http://example.com")

    norm = normalize_run(str(src), trace_id="t-classify-1")
    oid = norm["object_id"]

    res = classify_run(oid, trace_id="t-classify-1")
    value = res["classification"]
    assert value["type"] == "note"
    assert value["trust"] in {"provisional","external"}
    assert 0.5 <= value["confidence"] <= 0.7

    rows = _fetch_decisions(oid)
    assert any(r["key"] == "classification" for r in rows)
    tags = next(r for r in rows if r["key"] == "classification")["value"]["tags"]
    assert any(t.startswith("topic/") for t in tags) or tags == []
