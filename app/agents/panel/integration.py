from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Mapping, MutableMapping

from pydantic import BaseModel, Field

from app.events.models import Event
from app.events.schema import OutboxEvent
from app.orchestrator.handler import OrchestratorContext, handle_event
from app.planner.schema import Plan
from app.settings.panel_actions import PanelActionMapping, load_panel_action_mappings

from .agent import PanelAgentResult, handle_note_update
from .writeback import upsert_executed_ids

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
    note_id: str
    panel: PanelAgentResult
    events: list[Event | OutboxEvent]
    plans: list[Plan] = Field(default_factory=list)
    dispatch_count: int = 0


def prepare_panel_update(
    *,
    note_id: str,
    old_markdown: str,
    new_markdown: str,
    ctx: OrchestratorContext | Mapping[str, Any] | None = None,
    action_mappings: Dict[str, PanelActionMapping] | None = None,
    note_path: Path | str | None = None,
) -> PanelPipelineResult:
    mappings = action_mappings or load_panel_action_mappings()
    resolved_note_path = str(note_path) if note_path is not None else None
    panel_result = handle_note_update(
        note_id,
        old_markdown,
        new_markdown,
        action_mappings=mappings,
        note_path=resolved_note_path,
        persist_executed_ids=False,
    )
    events = list(panel_result.events)
    return PanelPipelineResult(note_id=note_id, panel=panel_result, events=events)


def commit_panel_update(
    prepared: PanelPipelineResult,
    *,
    ctx: OrchestratorContext | Mapping[str, Any] | None = None,
) -> PanelPipelineResult:
    """Persist/dispatch a prepared panel transition after canonical write success."""

    context = _ensure_context(ctx)
    if prepared.panel.executed_action_ids:
        upsert_executed_ids(
            prepared.note_id,
            prepared.panel.executed_action_ids,
        )
    plans: list[Plan] = []
    if prepared.events and panel_events_enabled(context):
        for event in prepared.events:
            if event.event in {"panel.intent.created", "panel.intent.executed", "panel.action.triggered"}:
                continue
            plan = handle_event(event, context)
            plans.append(plan)
    return prepared.model_copy(update={"plans": plans, "dispatch_count": len(plans)})


def handle_panel_update(
    *,
    note_id: str,
    old_markdown: str,
    new_markdown: str,
    ctx: OrchestratorContext | Mapping[str, Any] | None = None,
    action_mappings: Dict[str, PanelActionMapping] | None = None,
    note_path: Path | str | None = None,
) -> PanelPipelineResult:
    """Compatibility path for callers without a separate canonical write commit."""

    prepared = prepare_panel_update(
        note_id=note_id,
        old_markdown=old_markdown,
        new_markdown=new_markdown,
        ctx=ctx,
        action_mappings=action_mappings,
        note_path=note_path,
    )
    return commit_panel_update(prepared, ctx=ctx)


__all__ = [
    "PanelPipelineResult",
    "commit_panel_update",
    "handle_panel_update",
    "panel_events_enabled",
    "prepare_panel_update",
]
