from __future__ import annotations

import pytest

from app.agents.base.audit import _audit_ring_snapshot
from app.events.types import (
    AGENT_ERROR_CREATED,
    AGENT_REQUEST_CREATED,
)
from app.orchestrator.runtime import Orchestrator
from app.planner.schema import Plan, PlanMetadata, PlanStep

pytestmark = pytest.mark.not_pg


def test_agent_calls_emit_a2a_request_and_error() -> None:
    plan = Plan(
        id="plan-agent-only",
        meta=PlanMetadata(goal="demo", source_object_uuid="obj-201", created_by="tester"),
        steps=[
            PlanStep(
                id="step-agent",
                kind="agent_call",
                description="Ask reviewer to analyze note",
                agent="review-agent",
                intent="analyze",
            )
        ],
    )
    orchestrator = Orchestrator()
    before = _audit_ring_snapshot()
    orchestrator.run_plan(plan)
    after = _audit_ring_snapshot()
    new_events = [evt for evt in after if evt not in before]
    assert any(evt["event_type"] == AGENT_REQUEST_CREATED for evt in new_events)
    assert any(evt["event_type"] == AGENT_ERROR_CREATED and evt["payload"].get("details", {}).get("error_type") == "not_implemented" for evt in new_events)
