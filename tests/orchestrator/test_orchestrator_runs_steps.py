from __future__ import annotations

import pytest

from app.a2a.schema import AgentRequest, AgentResponse, new_response
from app.agents.base.audit import _audit_ring_snapshot
from app.events.types import (
    ORCHESTRATOR_STEP_FINISHED,
    ORCHESTRATOR_STEP_STARTED,
)
from app.orchestrator.executor import MockPlanExecutor
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


def _ingest_handler(request: AgentRequest) -> AgentResponse:
    return new_response(
        sender="ingest-agent",
        recipient=request.sender,
        status="ok",
        payload={"handled": True},
        correlation_id=request.correlation_id,
        trace_id=request.trace_id,
    )


def test_orchestrator_runs_mock_plan() -> None:
    plan = _mock_plan()
    executor = MockPlanExecutor(handlers={"ingest-agent": _ingest_handler})
    orchestrator = Orchestrator(executor=executor)
    before = _audit_ring_snapshot()
    results = orchestrator.run_plan(plan)
    after = _audit_ring_snapshot()
    assert len(results) == len(plan.steps)
    assert all(entry["status"] == "ok" for entry in results)
    new_events = [evt for evt in after if evt not in before]
    assert any(evt["event_type"] == ORCHESTRATOR_STEP_STARTED for evt in new_events)
    assert any(evt["event_type"] == ORCHESTRATOR_STEP_FINISHED for evt in new_events)
