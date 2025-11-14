from __future__ import annotations

import pytest

from app.agents.base.audit import _audit_ring_snapshot
from app.orchestrator.runtime import Orchestrator
from app.planner.provider import MockPlanner, PlannerInput
from app.planner.schema import Plan

pytestmark = pytest.mark.not_pg


def _mock_plan() -> Plan:
    planner = MockPlanner()
    return planner.plan(
        PlannerInput(
            object_uuid="obj-100",
            goal="Exercise mocked execution",
            text="Mock text for orchestration",
        )
    )


def test_orchestrator_runs_mock_plan() -> None:
    plan = _mock_plan()
    orchestrator = Orchestrator()
    before = _audit_ring_snapshot()
    results = orchestrator.run_plan(plan)
    after = _audit_ring_snapshot()
    assert len(results) == len(plan.steps)
    assert all(entry["status"] == "ok" for entry in results)
    new_events = [evt for evt in after if evt not in before]
    assert any(evt["action"] == "orchestrator.step.started" for evt in new_events)
    assert any(evt["action"] == "orchestrator.step.finished" for evt in new_events)
