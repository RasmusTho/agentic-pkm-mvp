from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.agents.planner.graph import PlannerGraph, run_planner_for_goal
from app.domain.plan import Plan
from app.store.object_store import DomainObject, ObjectStore

pytestmark = [pytest.mark.not_pg]


def _make_note(store: ObjectStore, review_state: str = "draft") -> str:
    note_uuid = str(uuid4())
    obj = DomainObject(
        uuid=note_uuid,
        kind="note",
        payload={
            "frontmatter": {"uuid": note_uuid, "review_state": review_state},
            "body": "Test note",
        },
        source_ref=None,
        created_at=datetime.now(timezone.utc),
    )
    store.save_object(obj, emit_outbox=False)
    return note_uuid


def test_planner_runs_real_mutation_on_note() -> None:
    store = ObjectStore()
    note_uuid = _make_note(store)
    goal = f"Make note {note_uuid} evergreen"

    plan = run_planner_for_goal(goal=goal, store=store, max_steps=5, max_replans=1)

    assert isinstance(plan, Plan)
    assert plan.goal == goal
    assert plan.executed_steps > 0
    assert plan.status in ("done", "in_progress")
    assert any(
        step.kind == "primitive"
        and step.target == note_uuid
        and step.action == "request_promotion_transition"
        for step in plan.steps
    )

    updated = store.get_object(note_uuid)
    assert updated is not None
    fm = (updated.payload or {}).get("frontmatter", {})
    assert fm.get("review_state") == "reviewed"
    assert fm.get("maturity") == "evergreen"


def test_planner_subplan_seed_preserves_non_evergreen_goal() -> None:
    store = ObjectStore()
    note_uuid = _make_note(store)
    goal = f"Process note {note_uuid}"

    plan = run_planner_for_goal(goal=goal, store=store, max_steps=5, max_replans=1)

    assert isinstance(plan, Plan)
    assert any(
        step.kind == "primitive"
        and step.target == note_uuid
        and step.action == "set_review_state"
        for step in plan.steps
    )
    updated = store.get_object(note_uuid)
    assert updated is not None
    fm = (updated.payload or {}).get("frontmatter", {})
    assert fm.get("review_state") == "provisional"
    assert "maturity" not in fm


def test_planner_run_carries_commitment_handles_without_persisting_them_into_plan_steps() -> None:
    store = ObjectStore()
    note_uuid = _make_note(store)
    goal = f"Review return for project note {note_uuid}"
    planner = PlannerGraph(goal=goal, store=store, max_steps=0, max_replans=0)

    final_state = planner.run(
        {
            "input": {"goal": goal},
            "goal": goal,
            "current_plan_id": None,
            "current_step_id": None,
            "total_steps": 0,
            "max_total_steps": 0,
        }
    )

    handles = final_state.get("commitment_handles") or []
    assert {handle.commitment_kind for handle in handles} == {"project", "review_return"}
    primary_handle = final_state.get("primary_commitment_handle")
    assert primary_handle is not None
    assert primary_handle.commitment_kind == "review_return"

    plan = final_state.get("plan")
    assert isinstance(plan, Plan)
    assert all("commitment_kind" not in step.args for step in plan.steps)
    assert all("commitment_handle" not in step.args for step in plan.steps)
