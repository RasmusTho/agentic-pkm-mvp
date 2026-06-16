from app.events.types import PROMOTION_EVALUATE_DONE

from pathlib import Path
import pytest

from app.agents.normalizer.agent import run as normalize_run
from app.agents.classifier.agent import run as classify_run
from app.agents.chunker.agent import run as chunk_run
from app.agents.indexer.agent import run as index_run
from app.agents.citation_checker.agent import run as citation_run
from app.agents.reviewer.agent import run as review_run
from app.agents.set_evaluator.agent import run as evaluate_run, run_set_evaluator
from app.components.reasoning.facade import RankingEntry, RankingResult


def _ingest_note(path: Path, text: str, trace_id: str) -> str:
    path.write_text(text)
    norm = normalize_run(str(path), trace_id=trace_id)
    oid = norm["object_id"]
    classify_run(oid, trace_id=trace_id)
    chunk_run(
        oid,
        trace_id=trace_id,
        max_tokens=100,
        overlap=10,
        strategy="heading_first",
    )
    index_run(oid, trace_id=trace_id)
    citation_run(oid, trace_id=trace_id)
    review_run(oid, trace_id=trace_id, threshold=0.75)
    return oid


def test_set_evaluator_scores_and_gates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv(
        "LLM_MOCK_RESPONSE",
        '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}',
    )

    flagged_text = (
        "# Market Analysis\n"
        "Enligt rapporten ökade marknaden med 25% mellan 2019 och 2023.\n"
        "Detta påstås i flera källor men här saknas citationer."
    )
    clean_text = (
        "# Research Summary\n"
        "Studien 2022 visar ökning.\n"
        "Källa: https://example.org/report.pdf\n"
        "Ytterligare information finns på https://example.org/data."
    )

    flagged_oid = _ingest_note(tmp_path / "flagged.md", flagged_text, "t-eval-flagged")
    clean_oid = _ingest_note(tmp_path / "clean.md", clean_text, "t-eval-clean")

    flagged_eval = evaluate_run(flagged_oid, trace_id="t-eval-flagged", threshold=0.7)
    clean_eval = evaluate_run(clean_oid, trace_id="t-eval-clean", threshold=0.7)

    assert flagged_eval["event"] == PROMOTION_EVALUATE_DONE
    assert "promote" in flagged_eval
    assert "score" in flagged_eval
    assert "allow" in flagged_eval

    assert clean_eval["event"] == PROMOTION_EVALUATE_DONE
    assert "promote" in clean_eval
    assert "score" in clean_eval
    assert "allow" in clean_eval


def test_run_set_evaluator_uses_reasoning_facade(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class StubFacade:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def reason(self, task_kind, input, trace_id=None):
            self.calls.append({"task_kind": task_kind, "input": input, "trace_id": trace_id})
            candidates = input["candidates"]
            return RankingResult(
                ranking=[
                    RankingEntry(
                        object_uuid=candidates[1]["object_uuid"],
                        score=0.91,
                        reason="Best match",
                    ),
                    RankingEntry(
                        object_uuid=candidates[0]["object_uuid"],
                        score=0.52,
                        reason="Secondary",
                    ),
                ]
            )

        @property
        def telemetry(self):
            return []

    first_oid = _ingest_note(tmp_path / "first.md", "First candidate text.", "t-rank-first")
    second_oid = _ingest_note(tmp_path / "second.md", "Second candidate text.", "t-rank-second")
    stub = StubFacade()
    monkeypatch.setattr("app.agents.set_evaluator.agent.get_reasoning_facade", lambda: stub)

    result = run_set_evaluator(
        [first_oid, second_oid],
        question="Which note best answers the question?",
        trace_id="t-rank-facade",
    )

    assert len(stub.calls) == 1
    call = stub.calls[0]
    assert str(call["task_kind"]).endswith("RANKING")
    assert call["trace_id"] == "t-rank-facade"
    assert call["input"]["question"] == "Which note best answers the question?"
    assert [candidate["object_uuid"] for candidate in call["input"]["candidates"]] == [first_oid, second_oid]
    assert result.ranking[0].object_id == second_oid
    assert result.ranking[0].reasons == ["Best match"]
    assert result.ranking[1].object_id == first_oid


def test_run_set_evaluator_falls_back_when_facade_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class StubFacade:
        def reason(self, task_kind, input, trace_id=None):
            raise RuntimeError("llm timeout")

        @property
        def telemetry(self):
            return []

    first_oid = _ingest_note(tmp_path / "first.md", "First candidate text.", "t-rank-first")
    second_oid = _ingest_note(tmp_path / "second.md", "Second candidate text.", "t-rank-second")
    monkeypatch.setattr("app.agents.set_evaluator.agent.get_reasoning_facade", lambda: StubFacade())

    result = run_set_evaluator(
        [first_oid, second_oid],
        question="Which note best answers the question?",
        trace_id="t-rank-fallback",
    )

    assert [item.object_id for item in result.ranking] == [first_oid, second_oid]
    assert all(item.reasons for item in result.ranking)
