from __future__ import annotations

import json
from pathlib import Path

from app.llm.trace_inspect import group_by_trace_id, load_trace


def test_group_by_trace_id_sorts_and_groups(tmp_path: Path) -> None:
    trace_path = tmp_path / "llm-trace.jsonl"
    rows = [
        {
            "timestamp": 3.0,
            "trace_id": "t-2",
            "provider": "mock",
            "model": "m",
            "agent": "planner",
            "kind": "planner.plan",
            "prompt_preview": "p3",
            "response_preview": "r3",
        },
        {
            "timestamp": 1.0,
            "trace_id": "t-1",
            "provider": "mock",
            "model": "m",
            "agent": "reasoning",
            "kind": "reasoning.single",
            "prompt_preview": "p1",
            "response_preview": "r1",
        },
        {
            "timestamp": 2.0,
            "trace_id": "t-1",
            "provider": "mock",
            "model": "m",
            "agent": "planner",
            "kind": "planner.plan",
            "prompt_preview": "p2",
            "response_preview": "r2",
        },
    ]
    with trace_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    records = load_trace(trace_path)
    grouped = group_by_trace_id(records)

    assert list(grouped.keys()) == ["t-1", "t-2"]
    assert [rec.timestamp for rec in grouped["t-1"]] == [1.0, 2.0]
    assert grouped["t-2"][0].kind == "planner.plan"
