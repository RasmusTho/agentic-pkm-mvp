import os, json
import psycopg
from psycopg.rows import dict_row
from app.agents.normalizer.agent import run as normalize_run
from app.agents.classifier.agent import run as classify_run
from app.agents.citation_checker.agent import run as citation_run

def _dsn():
    return os.environ["DATABASE_URL"].replace("postgresql+psycopg://","postgresql://")

def _fetch_decisions(oid: str):
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT key, value FROM decisions WHERE object_id=%s ORDER BY created_at ASC", (oid,))
            return cur.fetchall()

def test_citation_checker_blocks_for_external_without_sources(tmp_path, monkeypatch):
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["LLM_MOCK_RESPONSE"] = '{"type":"note","trust":"external","tags":["topic/test"],"confidence":0.9}'
    p = tmp_path / "no_cites.md"
    p.write_text("Enligt rapporten ökade marknaden med 25% mellan 2019 och 2023.")
    norm = normalize_run(str(p), trace_id="t-cite-1")
    oid = norm["object_id"]
    classify_run(oid, trace_id="t-cite-1")
    res = citation_run(oid, trace_id="t-cite-1")
    assert res["missing_citations"] is True
    assert res["blocked"] is True
    rows = _fetch_decisions(oid)
    keys = [r["key"] for r in rows]
    assert "missing_citations" in keys
    assert "promotion_block" in keys

def test_citation_checker_ok_when_sources_present(tmp_path):
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["LLM_MOCK_RESPONSE"] = '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.9}'
    p = tmp_path / "has_cites.md"
    p.write_text("Studien 2022 visar ökning. Källa: https://example.org/report.pdf")
    norm = normalize_run(str(p), trace_id="t-cite-2")
    oid = norm["object_id"]
    classify_run(oid, trace_id="t-cite-2")
    res = citation_run(oid, trace_id="t-cite-2")
    assert res["missing_citations"] is False
    rows = _fetch_decisions(oid)
    kv = [r for r in rows if r["key"] == "missing_citations"][-1]["value"]
    assert kv["value"] is False
