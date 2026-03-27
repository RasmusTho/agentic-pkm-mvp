from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

import app.guardrails as guardrails
from app.agents.planner.graph import run_planner_for_goal
from app.guardrails import GuardrailDecision
from app.store.object_store import DomainObject, ObjectStore

pytestmark = [pytest.mark.not_pg]


def _make_note(store: ObjectStore, review_state: str = "draft") -> str:
    note_uuid = str(uuid4())
    obj = DomainObject(
        uuid=note_uuid,
        kind="note",
        payload={
            "frontmatter": {"uuid": note_uuid, "review_state": review_state},
            "body": "Guardrail note",
        },
        source_ref=None,
        created_at=datetime.now(timezone.utc),
    )
    store.save_object(obj, emit_outbox=False)
    return note_uuid


def test_guardrails_are_invoked_for_primitive_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_pre(tool_name: str, args: dict, state: dict) -> GuardrailDecision:
        calls.append((tool_name, args))
        return GuardrailDecision(status="allow", modified_args=None, modified_result=None, reasons=[])

    monkeypatch.setattr(guardrails, "run_pre_guardrails", fake_pre)

    store = ObjectStore()
    note_uuid = _make_note(store)
    goal = f"Process note {note_uuid}"

    run_planner_for_goal(goal=goal, store=store, max_steps=5, max_replans=1)

    assert calls, "Guardrails pre-hook should be invoked at least once"


def test_guardrails_can_block_and_prevent_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_block(tool_name: str, args: dict, state: dict) -> GuardrailDecision:
        return GuardrailDecision(status="block", modified_args=None, modified_result=None, reasons=["blocked"])

    monkeypatch.setattr(guardrails, "run_pre_guardrails", fake_block)

    store = ObjectStore()
    note_uuid = _make_note(store, review_state="draft")
    goal = f"Promote note {note_uuid}"

    plan = run_planner_for_goal(goal=goal, store=store, max_steps=3, max_replans=0, max_depth=0)

    assert plan.status == "failed"
    blocked_steps = [s for s in plan.steps if s.state == "failed"]
    assert blocked_steps, "At least one step should be marked failed when guardrails block"

    updated = store.get_object(note_uuid)
    assert updated is not None
    fm = (updated.payload or {}).get("frontmatter", {})
    # mutation should not have happened
    assert fm.get("review_state") == "draft"
