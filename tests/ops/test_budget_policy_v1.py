from __future__ import annotations

from dataclasses import dataclass
import time
from pathlib import Path

import pytest

from app.agents.base.audit import _audit_ring_snapshot
from app.orchestrator.runtime import Orchestrator
from app.planner.schema import Plan, PlanMetadata, PlanStep

pytestmark = pytest.mark.not_pg


def _make_plan(steps: list[PlanStep]) -> Plan:
    return Plan(
        id="plan-budget",
        meta=PlanMetadata(goal="budget-test", source_object_uuid="obj-budget", created_by="tests", trace_id="trace-budget"),
        steps=steps,
    )


def _note_step(step_id: str, description: str) -> PlanStep:
    return PlanStep(id=step_id, kind="note", description=description)


def _tool_step(step_id: str, tool_name: str, **tool_args: object) -> PlanStep:
    return PlanStep(id=step_id, kind="tool_call", description=f"call {tool_name}", tool=tool_name, tool_args={k: v for k, v in tool_args.items()})


def test_max_steps_enforced() -> None:
    steps = [_note_step("step-1", "first"), _note_step("step-2", "second")]
    plan = _make_plan(steps)
    orchestrator = Orchestrator(tool_settings={"max_steps": 1})
    results = orchestrator.run_plan(plan)
    assert len(results) == 2
    assert results[0]["status"] == "ok"
    assert results[1]["status"] == "error"
    assert results[1].get("error_type") == "budget_exhausted"


def test_max_tool_calls_enforced() -> None:
    steps = [
        _tool_step("step-tool-1", "mcp.search.objects", query="foo"),
        _tool_step("step-tool-2", "mcp.search.objects", query="bar"),
    ]
    plan = _make_plan(steps)
    orchestrator = Orchestrator(tool_settings={"max_tool_calls": 1})
    results = orchestrator.run_plan(plan)
    assert len(results) == 2
    assert results[0]["status"] == "ok"
    assert results[1]["status"] == "error"
    assert results[1].get("error_type") == "budget_exhausted"


def test_tool_timeout_seconds(monkeypatch, tmp_path: Path) -> None:
    steps = [
        _tool_step("step-tool-timeout", "internal.ingest_external", root_dir=str(tmp_path))
    ]
    plan = _make_plan(steps)

    def _sleeping_ingest(root: Path, limit: int | None = None):  # type: ignore[no-untyped-def]
        @dataclass
        class _Summary:
            ingested: int = 0

        time.sleep(0.2)
        return _Summary()

    monkeypatch.setattr("app.ingest.external.ingest_external_folder", _sleeping_ingest)
    orchestrator = Orchestrator(tool_settings={"tool_timeout_seconds": 0.01})
    results = orchestrator.run_plan(plan)
    assert len(results) == 1
    assert results[0]["status"] == "error"
    assert results[0].get("error_type") == "tool_timeout"
