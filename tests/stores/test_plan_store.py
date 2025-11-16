from __future__ import annotations

from app.planner.schema import Plan, PlanMetadata, PlanStep, PlanTrigger
from app.stores.plan_store import MemoryPlanStore


def _make_plan(plan_id: str, event_id: str) -> Plan:
    return Plan(
        id=plan_id,
        meta=PlanMetadata(goal="demo", source_object_uuid="obj-1", created_by="tester"),
        steps=[PlanStep(id="s1", kind="note", description="noop")],
        trigger=PlanTrigger(event_type="ingest.object.created", event_id=event_id),
        goal="demo",
        tags=["flow:ingest"],
    )


def test_plan_store_roundtrip() -> None:
    store = MemoryPlanStore()
    plan = _make_plan("plan-a", "event-1")
    store.save(plan)
    fetched = store.get("plan-a")
    assert fetched is plan
    assert store.list_by_event("event-1") == [plan]


def test_plan_store_multiple_events() -> None:
    store = MemoryPlanStore()
    plan_a = _make_plan("plan-a", "event-1")
    plan_b = _make_plan("plan-b", "event-2")
    store.save(plan_a)
    store.save(plan_b)
    by_event_1 = store.list_by_event("event-1")
    assert by_event_1 == [plan_a]
    assert store.list_by_event("event-2") == [plan_b]
