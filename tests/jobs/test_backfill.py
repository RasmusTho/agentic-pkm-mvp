import os
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.agents.normalizer.agent import run as normalize_run
from app.agents.chunker.agent import run as chunk_run
from app.agents.indexer.agent import run as index_run
from app.agents.reviewer.agent import run as review_run
from app.agents.set_evaluator.agent import run as evaluate_run
from app.jobs.backfill import run_backfill

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://app:app@127.0.0.1:15432/app")


def _dsn() -> str:
    return os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")


def _count(sql: str, *params: Any) -> int:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return int(list(row.values())[0]) if row else 0


def _decision_exists(object_id: str, key: str) -> bool:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM decisions WHERE object_id=%s AND key=%s LIMIT 1",
                (object_id, key),
            )
            return cur.fetchone() is not None


def _membership_count(object_id: str) -> int:
    return _count("SELECT COUNT(*) FROM membership WHERE object_id=%s", object_id)


def _in_view(view: str, object_id: str) -> bool:
    with psycopg.connect(_dsn(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT 1 FROM {view} WHERE object_id=%s LIMIT 1", (object_id,))
            return cur.fetchone() is not None


def _audit_count(agent: str, object_id: str) -> int:
    return _count(
        "SELECT COUNT(*) FROM audit WHERE agent=%s AND object_id=%s",
        agent,
        object_id,
    )


def _normalize_note(path: Path, text: str, trace_id: str) -> str:
    path.write_text(text)
    res = normalize_run(str(path), trace_id=trace_id)
    return res["object_id"]


def test_backfill_hydrates_missing_pipeline(tmp_path: Path) -> None:
    os.environ["LLM_PROVIDER"] = "mock"
    os.environ["LLM_MOCK_RESPONSE"] = '{"type":"note","trust":"own","tags":["topic/test"],"confidence":0.95}'

    note1 = _normalize_note(tmp_path / "missing_chunks.md", "# A\n\nContent", "t-backfill-seed-1")
    note2 = _normalize_note(tmp_path / "missing_embeddings.md", "# B\n\nSecond", "t-backfill-seed-2")
    chunk_run(note2, trace_id="t-backfill-seed-2")

    note3 = _normalize_note(tmp_path / "ready_projection.md", "# C\n\nThird note with citation https://example.org", "t-backfill-seed-3")
    chunk_run(note3, trace_id="t-backfill-seed-3")
    index_run(note3, trace_id="t-backfill-seed-3")
    review_run(note3, trace_id="t-backfill-seed-3")
    evaluate_run(note3, trace_id="t-backfill-seed-3")

    assert _in_view("view_objects_missing_chunks", note1)
    assert _in_view("view_chunks_missing_embeddings", note2)
    assert _in_view("view_objects_missing_review", note1)
    assert _in_view("view_objects_missing_review", note2)
    assert _in_view("view_objects_ready_for_projection", note3)

    before_membership_note3 = _membership_count(note3)
    summary = run_backfill(
        trace_id="job-backfill-test",
        limit=50,
        set_name="published",
        dry_run=False,
    )

    assert summary.chunked or summary.indexed or summary.reviewed or summary.evaluated or summary.projected

    for oid in (note1, note2, note3):
        chunks = _count("SELECT COUNT(*) FROM chunks WHERE object_id=%s", oid)
        embeddings = _count("SELECT COUNT(*) FROM embeddings WHERE object_id=%s", oid)
        assert chunks >= 1
        assert embeddings >= chunks
        assert _decision_exists(oid, "review")
        assert _decision_exists(oid, "evaluate")
        assert _membership_count(oid) >= 1
        assert _audit_count("chunker", oid) >= 1
        assert _audit_count("indexer", oid) >= 1
        assert _audit_count("reviewer", oid) >= 1
        assert _audit_count("set_evaluator", oid) >= 1
        assert _audit_count("projector", oid) >= 1

    after_membership_note3 = _membership_count(note3)
    assert after_membership_note3 >= before_membership_note3

    assert not _in_view("view_objects_missing_chunks", note1)
    assert not _in_view("view_chunks_missing_embeddings", note2)
    assert not _in_view("view_objects_missing_review", note1)
    assert not _in_view("view_objects_missing_review", note2)
    assert not _in_view("view_objects_ready_for_projection", note3)

    second_pass = run_backfill(
        trace_id="job-backfill-test",
        limit=50,
        set_name="published",
        dry_run=False,
    )
    for oid in (note1, note2, note3):
        assert oid not in second_pass.chunked
        assert oid not in second_pass.indexed
        assert oid not in second_pass.reviewed
        assert oid not in second_pass.evaluated
        assert oid not in second_pass.projected
        assert _membership_count(oid) >= 1
