from app.events.types import (
    CURATION_REVIEW_DONE,
    INGEST_INDEX_DONE,
    PROMOTION_EVALUATE_DONE,
)

from pathlib import Path

import pytest

from app.agents.normalizer.agent import run as normalize_run
from app.agents.chunker.agent import run as chunk_run
from app.agents.indexer.agent import run as index_run
from app.agents.reviewer.agent import run as review_run
from app.agents.set_evaluator.agent import run as evaluate_run
from app.jobs.backfill import BackfillSummary, run_backfill


def _normalize(path: Path, text: str, trace_id: str) -> str:
    path.write_text(text)
    res = normalize_run(str(path), trace_id=trace_id)
    return res["object_id"]


def test_backfill_pipeline_structure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv(
        "LLM_MOCK_RESPONSE",
        '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}',
    )

    note1 = _normalize(tmp_path / "missing_chunks.md", "# A\n\nContent", "t-backfill-seed-1")
    note2 = _normalize(tmp_path / "missing_embeddings.md", "# B\n\nSecond", "t-backfill-seed-2")
    note3 = _normalize(
        tmp_path / "ready_projection.md",
        "# C\n\nThird note with citation https://example.org",
        "t-backfill-seed-3",
    )

    chunk_res = chunk_run(
        note2,
        trace_id="t-backfill-seed-2",
        max_tokens=200,
        overlap=40,
        strategy="heading_first",
    )
    assert chunk_res["chunks"] >= 1

    chunk_res3 = chunk_run(
        note3,
        trace_id="t-backfill-seed-3",
        max_tokens=200,
        overlap=40,
        strategy="heading_first",
    )
    assert chunk_res3["chunks"] >= 1

    index_res = index_run(note3, trace_id="t-backfill-seed-3")
    assert index_res["event"] == INGEST_INDEX_DONE
    assert index_res["embeddings"] >= 1

    review_res = review_run(note3, trace_id="t-backfill-seed-3")
    assert review_res["event"] == CURATION_REVIEW_DONE
    assert "allow" in review_res

    evaluate_res = evaluate_run(note3, trace_id="t-backfill-seed-3")
    assert evaluate_res["event"] == PROMOTION_EVALUATE_DONE
    assert "promote" in evaluate_res
    assert "score" in evaluate_res
    assert "allow" in evaluate_res
