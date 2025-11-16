from __future__ import annotations

import pytest

from app.events.models import new_event
from app.events.types import ASK_QUERY_RECEIVED, INGEST_OBJECT_CREATED
from app.orchestrator.handler import OrchestratorContext, handle_event
from app.stores.plan_store import get_plan_store, reset_plan_store


def setup_function() -> None:
    reset_plan_store()


def test_handle_event_runs_ingest_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVENT_ORCHESTRATOR_ENABLE", "1")
    event = new_event(
        event_type=INGEST_OBJECT_CREATED,
        payload={
            "uuid": "obj-handle-1",
            "content": "Hello world",
            "title": "Demo",
        },
    )
    plan = handle_event(event, OrchestratorContext())
    assert plan.trigger is not None
    assert plan.trigger.event_type == INGEST_OBJECT_CREATED
    assert any(tag in {"ingest", "flow:ingest"} for tag in plan.tags)
    stored = get_plan_store().get(plan.id)
    assert stored is plan


def test_handle_event_runs_qa_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVENT_ORCHESTRATOR_ENABLE", "1")
    event = new_event(
        event_type=ASK_QUERY_RECEIVED,
        payload={"object_id": "qa-obj-1", "question": "What is the plan?"},
    )
    plan = handle_event(event, OrchestratorContext())
    assert plan.trigger is not None
    assert plan.trigger.event_type == ASK_QUERY_RECEIVED
    assert any(tag in {"qa", "flow:qa"} for tag in plan.tags)
