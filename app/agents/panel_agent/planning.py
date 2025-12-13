from __future__ import annotations

from typing import List

from app.agents.panel_agent.intent import PanelActionIntent
from app.events.types import PLANNER_PLAN_CREATED
from app.planner.schema import Plan, PlanMetadata, PlanStep, PlanTrigger, new_plan_id
from app.stores.plan_store import get_plan_store
from app.events.models import new_event


def _steps_for_actions(actions: List[str], note_uuid: str) -> List[PlanStep]:
    steps: List[PlanStep] = []
    for idx, action_id in enumerate(actions, start=1):
        if action_id in {"promote.evergreen", "promote_evergreen"}:
            steps.append(
                PlanStep(
                    id=f"step-{idx}",
                    kind="tool_call",
                    description="Emit promotion intent for evergreen",
                    tool="promotion.emit_intent",
                    tool_args={"action_id": action_id, "note_uuid": note_uuid},
                    reason="Panel requested evergreen promotion",
                )
            )
        else:
            steps.append(
                PlanStep(
                    id=f"step-{idx}",
                    kind="note",
                    description=f"Unhandled panel action: {action_id}",
                    reason="Panel action not yet mapped to a tool",
                    metadata={"action_id": action_id},
                )
            )
    return steps


def plan_panel_actions(intent: PanelActionIntent, *, event_id: str | None = None, trace_id: str | None = None) -> Plan:
    goal = f"Panel actions for note {intent.note.uuid}"
    trigger = PlanTrigger(event_type="panel.intent.created", event_id=event_id or intent.note.uuid, trace_id=trace_id)
    plan = Plan(
        id=new_plan_id(),
        meta=PlanMetadata(goal=goal, source_object_uuid=intent.note.uuid, created_by="panel_agent"),
        steps=_steps_for_actions(intent.actions, intent.note.uuid),
        trigger=trigger,
        goal=goal,
        context={"panel_instruction": intent.instruction, "panel_actions": list(intent.actions), "source": intent.source},
        tags=["panel", "panel_agent", "panel:planner"],
    )
    store = get_plan_store()
    store.save(plan)
    # Emit a lightweight event for observability; planners/orchestrators can consume as needed.
    new_event(event_type=PLANNER_PLAN_CREATED, payload={"plan_id": plan.id, "note_uuid": intent.note.uuid})
    return plan


__all__ = ["plan_panel_actions"]
