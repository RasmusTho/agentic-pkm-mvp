from app.events.types import CURATION_REVIEW_DONE

import os
from pathlib import Path
import pytest

from app.agents.normalizer.agent import run as normalize_run
from app.agents.classifier.agent import run as classify_run
from app.agents.chunker.agent import run as chunk_run
from app.agents.citation_checker.agent import run as citation_run
from app.agents.reviewer.agent import run as review_run
from app.components.reasoning.facade import ReviewResult

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://app:app@127.0.0.1:15432/app")


def test_reviewer_returns_structure(tmp_path: Path) -> None:
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["LLM_MOCK_RESPONSE"] = '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}'

    missing_src = tmp_path / "missing.md"
    clean_src = tmp_path / "clean.md"

    missing_src.write_text("Enligt rapporten ökade marknaden med 25% sedan 2020.")
    clean_src.write_text("Studien 2022 visar ökning. Källa: https://example.org/report.pdf")

    missing_norm = normalize_run(str(missing_src), trace_id="t-review-miss")
    clean_norm = normalize_run(str(clean_src), trace_id="t-review-clean")

    for oid, trace_id in (
        (missing_norm["object_id"], "t-review-miss"),
        (clean_norm["object_id"], "t-review-clean"),
    ):
        classify_run(oid, trace_id=trace_id)
        chunk_run(
            oid,
            trace_id=trace_id,
            max_tokens=200,
            overlap=40,
            strategy="heading_first",
        )
        citation_run(oid, trace_id=trace_id)
        review = review_run(oid, trace_id=trace_id, threshold=0.75)
        assert review["event"] == CURATION_REVIEW_DONE
        assert "allow" in review and isinstance(review["allow"], bool)
        assert "reasons" in review and isinstance(review["reasons"], list)
        assert "agent" in review and review["agent"] == "reviewer"


def test_reviewer_uses_reasoning_facade(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class StubFacade:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def reason(self, task_kind, input, trace_id=None):
            self.calls.append({"task_kind": task_kind, "input": input, "trace_id": trace_id})
            return ReviewResult(summary="Facade summary", suggestions=["Facade suggestion"])

    note = tmp_path / "reviewer.md"
    note.write_text("Reviewer facade body text.")
    oid = normalize_run(str(note), trace_id="t-review-facade")["object_id"]
    stub = StubFacade()
    monkeypatch.setattr("app.agents.reviewer.agent.get_reasoning_facade", lambda: stub)

    result = review_run(oid, trace_id="t-review-facade", threshold=0.75)

    assert len(stub.calls) == 1
    call = stub.calls[0]
    assert str(call["task_kind"]).endswith("REVIEW")
    assert call["trace_id"] == "t-review-facade"
    assert call["input"]["object_uuid"] == oid
    assert call["input"]["_agent"] == "reviewer"
    assert "Reviewer facade body text." in call["input"]["text"]
    assert result["analysis"] == "Facade summary"
    assert result["suggestions"] == ["Facade suggestion"]
    assert result["reasons"] == ["Facade suggestion"]
