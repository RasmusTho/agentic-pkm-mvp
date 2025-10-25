import os
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.agents.normalizer.agent import run as normalize_run
from app.agents.classifier.agent import run as classify_run
from app.agents.chunker.agent import run as chunk_run
from app.agents.citation_checker.agent import run as citation_run
from app.agents.reviewer.agent import run as review_run
from app.memory.store import recall

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://app:app@127.0.0.1:15432/app")


def _dsn() -> str:
    return os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")


def _fetch_decisions(object_id: str) -> list[dict[str, Any]]:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT key, value FROM decisions WHERE object_id=%s ORDER BY created_at DESC",
                (object_id,),
            )
            return cur.fetchall()


def _count_audit(agent: str, object_id: str) -> int:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS c FROM audit WHERE agent=%s AND object_id=%s",
                (agent, object_id),
            )
            row = cur.fetchone()
            return int(row["c"])


def test_reviewer_gates_promotion(tmp_path: Path) -> None:
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["LLM_MOCK_RESPONSE"] = '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}'

    missing_src = tmp_path / "missing.md"
    clean_src = tmp_path / "clean.md"

    missing_src.write_text("Enligt rapporten ökade marknaden med 25% sedan 2020.")
    clean_src.write_text("Studien 2022 visar ökning. Källa: https://example.org/report.pdf")

    trace_missing = "t-review-miss"
    trace_clean = "t-review-clean"

    missing_norm = normalize_run(str(missing_src), trace_id=trace_missing)
    clean_norm = normalize_run(str(clean_src), trace_id=trace_clean)

    missing_oid = missing_norm["object_id"]
    clean_oid = clean_norm["object_id"]

    classify_run(missing_oid, trace_id=trace_missing)
    classify_run(clean_oid, trace_id=trace_clean)

    chunk_run(missing_oid, trace_id=trace_missing)
    chunk_run(clean_oid, trace_id=trace_clean)

    citation_run(missing_oid, trace_id=trace_missing)
    citation_run(clean_oid, trace_id=trace_clean)

    blocked = review_run(missing_oid, trace_id=trace_missing, threshold=0.75)
    allowed = review_run(clean_oid, trace_id=trace_clean, threshold=0.75)

    assert blocked["allow"] is False
    assert blocked["missing_citations"] >= 1
    assert blocked["trust"] < 0.75

    decisions_blocked = _fetch_decisions(missing_oid)
    assert any(row["key"] == "review" for row in decisions_blocked)
    assert _count_audit("reviewer", missing_oid) >= 1

    assert allowed["allow"] is True
    assert allowed["trust"] >= 0.75
    decisions_allowed = _fetch_decisions(clean_oid)
    assert any(row["key"] == "review" for row in decisions_allowed)
    assert _count_audit("reviewer", clean_oid) >= 1

    memories = recall("reviewer", "review", object_id=None, limit=10)
    assert any(isinstance(entry.get("allow"), bool) for entry in memories)
