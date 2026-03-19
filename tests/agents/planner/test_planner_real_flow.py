from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.agents.planner.graph import run_planner_for_goal
from app.domain.plan import Plan
from app.store.object_store import DomainObject, ObjectStore

pytestmark = [pytest.mark.not_pg]


def _make_note(store: ObjectStore, review_state: str = "inbox") -> str:
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
    assert any(step.kind == "primitive" and step.target == note_uuid for step in plan.steps)

    updated = store.get_object(note_uuid)
    assert updated is not None
    fm = (updated.payload or {}).get("frontmatter", {})
    assert fm.get("review_state") == "reviewed"
    assert fm.get("maturity") == "evergreen"
