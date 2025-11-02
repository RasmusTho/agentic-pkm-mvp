import os
from pathlib import Path

from app.agents.normalizer.agent import run as normalize_run
from app.agents.classifier.agent import run as classify_run
from app.agents.chunker.agent import run as chunk_run
from app.agents.indexer.agent import run as index_run
from app.agents.citation_checker.agent import run as citation_run
from app.agents.reviewer.agent import run as review_run
from app.agents.set_evaluator.agent import run as evaluate_run

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://app:app@127.0.0.1:15432/app")


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


def test_set_evaluator_scores_and_gates(tmp_path: Path) -> None:
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["LLM_MOCK_RESPONSE"] = '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}'

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

    assert flagged_eval["event"] == "promotion.evaluate.done"
    assert "promote" in flagged_eval
    assert "score" in flagged_eval
    assert "allow" in flagged_eval

    assert clean_eval["event"] == "promotion.evaluate.done"
    assert "promote" in clean_eval
    assert "score" in clean_eval
    assert "allow" in clean_eval
