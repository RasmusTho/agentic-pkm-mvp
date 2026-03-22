from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.agents.base.graph import AgentState
from app.agents.planner.graph import PlannerGraph
from app.domain.commitments import CommitmentHandle
from app.store.object_store import DomainObject, ObjectStore


def _make_note(store: ObjectStore) -> str:
    note_uuid = str(uuid4())
    obj = DomainObject(
        uuid=note_uuid,
        kind="note",
        payload={
            "frontmatter": {"uuid": note_uuid, "review_state": "inbox"},
            "body": "Test note",
        },
        source_ref=None,
        created_at=datetime.now(timezone.utc),
    )
    store.save_object(obj, emit_outbox=False)
    return note_uuid


def test_planner_node_attaches_commitment_handles_to_state_only() -> None:
    store = ObjectStore()
    note_uuid = _make_note(store)
    goal = f"Review return for project note {note_uuid}"
    graph = PlannerGraph(goal=goal, store=store)

    state: AgentState = {
        "input": {"goal": goal},
        "goal": goal,
        "current_plan_id": None,
        "current_step_id": None,
    }
    planned = graph._planner_node(state)

    handles = planned.get("commitment_handles") or []
    assert handles
    assert all(isinstance(handle, CommitmentHandle) for handle in handles)
    assert {handle.commitment_kind for handle in handles} == {"project", "review_return"}

    plan = planned["plan"]
    assert all("commitment_kind" not in step.args for step in plan.steps)
    assert all("commitment_handle" not in step.args for step in plan.steps)

    stored_note = store.get_object(note_uuid)
    frontmatter = (stored_note.payload or {}).get("frontmatter", {})
    assert frontmatter == {"uuid": note_uuid, "review_state": "inbox"}
