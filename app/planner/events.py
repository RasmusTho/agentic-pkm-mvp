from __future__ import annotations

from typing import Any, Dict, List

from app.events.models import Event
from app.planner.provider import PlannerInput, get_planner
from app.planner.schema import Plan, PlanTrigger
from app.settings.flows import get_flows_for_event
from app.stores.plan_store import get_plan_store


def _object_uuid_from_event(event: Event) -> str:
    payload = event.payload or {}
    for key in ("object_uuid", "object_id", "uuid", "source_object_uuid", "id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return event.event_id


def _extract_text(event: Event) -> str:
    payload = event.payload or {}
    for key in ("text", "content", "summary", "body"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _build_tags(flows: List[str]) -> List[str]:
    tags: List[str] = []
    for name in flows:
        if name not in tags:
            tags.append(name)
    for name in flows:
        prefixed = f"flow:{name}"
        if prefixed not in tags:
            tags.append(prefixed)
    return tags


def _goal_for_event(event_type: str, flows: List[str]) -> str:
    if flows:
        flow_label = "/".join(flows)
    else:
        flow_label = "general"
    return f"{flow_label} plan for {event_type}"


def _build_context(event: Event, flows: List[str], extra: Dict[str, Any] | None) -> Dict[str, Any]:
    context: Dict[str, Any] = {
        "event_type": event.event_type,
        "event_id": event.event_id,
        "flows": flows,
        "payload": event.payload,
    }
    if extra:
        context["extras"] = extra
    return context


def _build_metadata(event: Event, flows: List[str], trace_id: str | None) -> Dict[str, Any]:
    payload_meta = event.payload.get("metadata") if isinstance(event.payload, dict) else None
    metadata: Dict[str, Any] = {}
    if isinstance(payload_meta, dict):
        metadata.update(payload_meta)
    if trace_id and not metadata.get("trace_id"):
        metadata["trace_id"] = trace_id
    metadata.setdefault("event_id", event.event_id)
    metadata.setdefault("event_type", event.event_type)
    metadata.setdefault("flows", flows)
    return metadata


def plan_for_event(event: Event, ctx: Dict[str, Any] | None = None) -> Plan:
    flows = get_flows_for_event(event.event_type)
    tags = _build_tags(flows)
    trace_id = event.trace_id or event.payload.get("trace_id")
    trigger = PlanTrigger(event_type=event.event_type, event_id=event.event_id, trace_id=trace_id)
    goal = _goal_for_event(event.event_type, flows)
    planner_input = PlannerInput(
        object_uuid=_object_uuid_from_event(event),
        goal=goal,
        text=_extract_text(event),
        relations=[],
        metadata=_build_metadata(event, flows, trace_id),
        trigger=trigger,
        context=_build_context(event, flows, ctx),
        tags=tags,
    )
    plan = get_planner().plan(planner_input)
    if plan.trigger is None:
        plan.trigger = trigger
    if not plan.goal:
        plan.goal = goal
    if not plan.tags:
        plan.tags = tags
    if not plan.context:
        plan.context = _build_context(event, flows, ctx)
    plan.meta.goal = plan.meta.goal or goal
    if trace_id and not plan.meta.trace_id:
        plan.meta.trace_id = trace_id
    get_plan_store().save(plan)
    return plan


__all__ = ["plan_for_event"]
