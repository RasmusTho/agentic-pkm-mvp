from __future__ import annotations

import os
from typing import Any, Dict, Mapping, MutableMapping

from pydantic import BaseModel, Field

from app.events.models import Event
from app.orchestrator.handler import OrchestratorContext, handle_event
from app.planner.schema import Plan
from app.settings.panel_actions import PanelActionMapping, load_panel_action_mappings

from .agent import PanelAgentResult, handle_note_update

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_VALUES
    return bool(value)


def _ensure_context(ctx: OrchestratorContext | Mapping[str, Any] | None) -> OrchestratorContext:
    if ctx is None:
        return OrchestratorContext()
    if isinstance(ctx, OrchestratorContext):
        return ctx
    if isinstance(ctx, MutableMapping) or isinstance(ctx, dict):
        return OrchestratorContext(settings=dict(ctx))
    raise TypeError("ctx must be OrchestratorContext, mapping, or None")


def panel_events_enabled(ctx: OrchestratorContext | Mapping[str, Any] | None = None) -> bool:
    context = _ensure_context(ctx)
    settings = context.settings or {}
    if "panel_events_enable" in settings:
        return _truthy(settings.get("panel_events_enable"))
    env_value = os.getenv("PANEL_EVENTS_ENABLE")
    if env_value is not None:
        return _truthy(env_value)
    return False


class PanelPipelineResult(BaseModel):
    panel: PanelAgentResult
    events: list[Event]
    plans: list[Plan] = Field(default_factory=list)
    dispatch_count: int = 0


def handle_panel_update(
    *,
    note_id: str,
    old_markdown: str,
    new_markdown: str,
    ctx: OrchestratorContext | Mapping[str, Any] | None = None,
    action_mappings: Dict[str, PanelActionMapping] | None = None,
) -> PanelPipelineResult:
    context = _ensure_context(ctx)
    mappings = action_mappings or load_panel_action_mappings()
    panel_result = handle_note_update(note_id, old_markdown, new_markdown, action_mappings=mappings)
    events = list(panel_result.events)
    plans: list[Plan] = []
    if events and panel_events_enabled(context):
        for event in events:
            plan = handle_event(event, context)
            plans.append(plan)
    return PanelPipelineResult(panel=panel_result, events=events, plans=plans, dispatch_count=len(plans))


__all__ = ["PanelPipelineResult", "handle_panel_update", "panel_events_enabled"]
