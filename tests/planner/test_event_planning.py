from __future__ import annotations

from app.events.models import new_event
from app.events.types import ASK_QUERY_RECEIVED, INGEST_OBJECT_CREATED
from app.planner.events import plan_for_event
from app.stores.plan_store import get_plan_store, reset_plan_store


def setup_function() -> None:
    reset_plan_store()


def test_ingest_event_produces_plan_with_flow_tags() -> None:
    event = new_event(
        event_type=INGEST_OBJECT_CREATED,
        payload={
            "uuid": "obj-100",
            "content": "Body",
            "title": "Demo",
        },
    )
    plan = plan_for_event(event, ctx={"origin": "test"})
    assert plan.trigger is not None
    assert plan.trigger.event_type == INGEST_OBJECT_CREATED
    assert plan.trigger.event_id == event.event_id
    assert any(tag in {"ingest", "flow:ingest"} for tag in plan.tags)
    assert plan.goal
    stored = get_plan_store().get(plan.id)
    assert stored is plan


def test_ask_event_maps_to_qa_flow() -> None:
    event = new_event(event_type=ASK_QUERY_RECEIVED, payload={"question": "How to plan?"})
    plan = plan_for_event(event)
    assert plan.trigger is not None
    assert plan.trigger.event_type == ASK_QUERY_RECEIVED
    assert any(tag in {"qa", "flow:qa"} for tag in plan.tags)
