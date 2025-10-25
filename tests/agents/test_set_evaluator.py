import os
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.agents.normalizer.agent import run as normalize_run
from app.agents.classifier.agent import run as classify_run
from app.agents.chunker.agent import run as chunk_run
from app.agents.indexer.agent import run as index_run
from app.agents.citation_checker.agent import run as citation_run
from app.agents.reviewer.agent import run as review_run
from app.agents.set_evaluator.agent import run as evaluate_run
from app.memory.store import recall

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://app:app@127.0.0.1:15432/app")


def _dsn() -> str:
    return os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")


def _fetch_decisions(object_id: str, key: str) -> list[dict[str, Any]]:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT value FROM decisions WHERE object_id=%s AND key=%s ORDER BY created_at DESC",
                (object_id, key),
            )
            return [row["value"] for row in cur.fetchall()]


def _count_audit(agent: str, object_id: str) -> int:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS c FROM audit WHERE agent=%s AND object_id=%s",
                (agent, object_id),
            )
            row = cur.fetchone()
            return int(row["c"])


def _ingest_note(path: Path, text: str, trace_id: str) -> str:
    path.write_text(text)
    norm = normalize_run(str(path), trace_id=trace_id)
    oid = norm["object_id"]
    classify_run(oid, trace_id=trace_id)
    chunk_run(oid, trace_id=trace_id, max_tokens=100, overlap=10, strategy="heading_first")
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

    assert flagged_eval["promote"] is False
    assert clean_eval["promote"] is True
    assert clean_eval["score"] >= clean_eval["threshold"]

    flagged_decisions = _fetch_decisions(flagged_oid, "evaluate")
    clean_decisions = _fetch_decisions(clean_oid, "evaluate")
    assert flagged_decisions and clean_decisions
    assert all(isinstance(val.get("score"), (int, float)) for val in clean_decisions)

    assert _count_audit("set_evaluator", flagged_oid) >= 1
    assert _count_audit("set_evaluator", clean_oid) >= 1

    memories = recall("set_evaluator", "evaluation", object_id=None, limit=10)
    assert any(isinstance(entry.get("score"), (int, float)) for entry in memories)
