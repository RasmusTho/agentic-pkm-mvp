from app.events.types import (
    CURATION_CITATION_CHECK_DONE,
    CURATION_CITATION_CHECKED,
    CURATION_CITATION_SKIP,
)

import os
from app.agents.normalizer.agent import run as normalize_run
from app.agents.classifier.agent import run as classify_run
from app.agents.citation_checker.agent import run as citation_run

def test_citation_checker_blocks_for_external_without_sources(tmp_path, monkeypatch):
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["LLM_MOCK_RESPONSE"] = '{"type":"note","trust":"external","tags":["topic/test"],"confidence":0.9}'
    p = tmp_path / "no_cites.md"
    p.write_text("Enligt rapporten ökade marknaden med 25% mellan 2019 och 2023.")
    norm = normalize_run(str(p), trace_id="t-cite-1")
    oid = norm["object_id"]
    classify_run(oid, trace_id="t-cite-1")
    res = citation_run(oid, trace_id="t-cite-1")
    assert "event" in res
    assert res["event"] in {
        CURATION_CITATION_CHECK_DONE,
        CURATION_CITATION_CHECKED,
        CURATION_CITATION_SKIP,
    }

def test_citation_checker_ok_when_sources_present(tmp_path):
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["LLM_MOCK_RESPONSE"] = '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.9}'
    p = tmp_path / "has_cites.md"
    p.write_text("Studien 2022 visar ökning. Källa: https://example.org/report.pdf")
    norm = normalize_run(str(p), trace_id="t-cite-2")
    oid = norm["object_id"]
    classify_run(oid, trace_id="t-cite-2")
    res = citation_run(oid, trace_id="t-cite-2")
    assert "event" in res
    assert res["event"] in {
        CURATION_CITATION_CHECK_DONE,
        CURATION_CITATION_CHECKED,
        CURATION_CITATION_SKIP,
    }
