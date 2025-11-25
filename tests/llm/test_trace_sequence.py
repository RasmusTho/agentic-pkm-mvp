from __future__ import annotations

import json

import pytest

from app.llm.trace_inspect import (
    LLMTraceRecord,
    build_sequence_for_trace,
    list_agents_in_sequence,
)


def test_build_sequence_orders_and_indexes() -> None:
    trace_id = "trace-123"
    records = [
        LLMTraceRecord(
            timestamp=20.0,
            trace_id=trace_id,
            provider="p",
            model="m",
            agent="planner",
            kind="planner.plan",
            prompt_preview="p2",
            response_preview="r2",
        ),
        LLMTraceRecord(
            timestamp=10.0,
            trace_id=trace_id,
            provider="p",
            model="m",
            agent="reasoning",
            kind="reasoning.single_note",
            prompt_preview="p1",
            response_preview="r1",
        ),
        LLMTraceRecord(
            timestamp=25.0,
            trace_id=trace_id,
            provider="p",
            model="m",
            agent="planner",
            kind="planner.refine",
            prompt_preview="p3",
            response_preview="r3",
        ),
        LLMTraceRecord(
            timestamp=30.0,
            trace_id="other",
            provider="p",
            model="m",
            agent="qa",
            kind="qa.draft",
            prompt_preview="p4",
            response_preview="r4",
        ),
    ]

    seq = build_sequence_for_trace(records, trace_id)

    assert seq.trace_id == trace_id
    assert [step.index for step in seq.steps] == [1, 2, 3]
    assert [step.kind for step in seq.steps] == [
        "reasoning.single_note",
        "planner.plan",
        "planner.refine",
    ]
    assert [step.timestamp for step in seq.steps] == [10.0, 20.0, 25.0]

    agents = list_agents_in_sequence(seq)
    assert agents == ["reasoning", "planner"]


def test_build_sequence_no_records_raises() -> None:
    with pytest.raises(ValueError):
        build_sequence_for_trace([], "missing")


def test_log_llm_call_uses_response_text(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LLM_TRACE_ENABLE", "1")
    monkeypatch.setenv("LLM_TRACE_PATH", str(tmp_path / "trace.jsonl"))

    import importlib
    import app.llm.trace as trace_module

    trace = importlib.reload(trace_module)
    trace.log_llm_call(
        provider="p",
        model="m",
        agent="reasoning",
        kind="reasoning.single_note",
        messages=[{"role": "user", "content": "hi"}],
        response={},
        response_text='{"claims": [{"id": "c1"}]}',
        trace_id="T-log",
    )

    trace_path = tmp_path / "trace.jsonl"
    with trace_path.open("r", encoding="utf-8") as handle:
        line = handle.readline()
    record = json.loads(line)
    assert record["trace_id"] == "T-log"
    assert '"claims"' in record["response_preview"]
