from __future__ import annotations

from typing import Any, List

from app.agents.panel_agent.intent import PanelActionIntent
from app.events.panel import PanelIntentAction
from app.events.types import PLANNER_PLAN_CREATED
from app.planner.schema import Plan, PlanMetadata, PlanStep, PlanTrigger, new_plan_id
from app.stores.plan_store import get_plan_store
from app.events.models import new_event


_PANEL_AGENT_ID = "panel_agent.v5"
_PANEL_PLAN_CONTRACT_VERSION = "panel.ordered.v1"


def _is_promotion(action_id: str, action: PanelIntentAction | None) -> bool:
    if action and action.mapping and (action.mapping.intent_type or "").lower() == "promotion":
        return True
    return action_id in {"promote.evergreen", "promote_evergreen"}


def _promotion_tool_args(action_id: str, note_uuid: str, action: PanelIntentAction | None, instruction: str) -> dict:
    args = {"action_id": action_id, "note_uuid": note_uuid, "instruction": instruction}
    if action:
        args["action_label"] = action.label
        mapping = action.mapping
        if mapping:
            args["downstream_event"] = mapping.downstream_event
            if mapping.params:
                args.update({k: v for k, v in mapping.params.items() if v is not None})
    return args


def _steps_for_actions(
    actions: List[str], note_uuid: str, resolved: List[PanelIntentAction] | None, instruction: str
) -> List[PlanStep]:
    steps: List[PlanStep] = []
    resolved = resolved or []
    total = len(actions)
    for idx, action_id in enumerate(actions, start=1):
        action = next((candidate for candidate in resolved if candidate.id == action_id), None)
        metadata: dict[str, Any] = {
            "action_id": action_id,
            "sequence_index": idx,
            "sequence_total": total,
            "ordered_contract": _PANEL_PLAN_CONTRACT_VERSION,
        }
        depends_on = [f"step-{idx - 1}"] if idx > 1 else []
        if _is_promotion(action_id, action):
            steps.append(
                PlanStep(
                    id=f"step-{idx}",
                    kind="tool_call",
                    description="Emit promotion intent for evergreen",
                    tool="promotion.emit_intent",
                    tool_args=_promotion_tool_args(action_id, note_uuid, action, instruction),
                    reason="Panel requested evergreen promotion",
                    depends_on=depends_on,
                    metadata={**metadata, "intent_type": "promotion"},
                    agent_id=_PANEL_AGENT_ID,
                )
            )
        else:
            steps.append(
                PlanStep(
                    id=f"step-{idx}",
                    kind="note",
                    description=f"Unhandled panel action: {action_id}",
                    reason="Panel action not yet mapped to a tool",
                    depends_on=depends_on,
                    metadata=metadata,
                )
            )
    return steps


def plan_panel_actions(intent: PanelActionIntent, *, event_id: str | None = None, trace_id: str | None = None) -> Plan:
    goal = f"Panel actions for note {intent.note.uuid}"
    trigger = PlanTrigger(event_type="panel.intent.created", event_id=event_id or intent.note.uuid, trace_id=trace_id)
    plan = Plan(
        id=new_plan_id(),
        meta=PlanMetadata(
            goal=goal,
            source_object_uuid=intent.note.uuid,
            created_by="panel_agent",
            trace_id=trace_id,
        ),
        steps=_steps_for_actions(intent.actions, intent.note.uuid, intent.resolved_actions, intent.instruction),
        trigger=trigger,
        goal=goal,
        context={
            "panel_instruction": intent.instruction,
            "panel_actions": list(intent.actions),
            "panel_plan": {
                "contract_version": _PANEL_PLAN_CONTRACT_VERSION,
                "ordered": True,
                "action_ids": list(intent.actions),
            },
            "source": intent.source,
        },
        tags=["panel", "panel_agent", "panel:planner"],
    )
    store = get_plan_store()
    store.save(plan)
    # Emit a lightweight event for observability; planners/orchestrators can consume as needed.
    new_event(event_type=PLANNER_PLAN_CREATED, payload={"plan_id": plan.id, "note_uuid": intent.note.uuid})
    return plan


__all__ = ["plan_panel_actions"]
