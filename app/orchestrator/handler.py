from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict

from app.events.models import Event
from app.planner.events import plan_for_event
from app.planner.schema import Plan
from app.stores.plan_store import get_plan_store

from .runtime import create_orchestrator


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


@dataclass
class OrchestratorContext:
    settings: Dict[str, Any] = field(default_factory=dict)
    orchestrator: Any | None = None  # Orchestrator or compatible implementation


def _feature_flag_enabled(ctx: OrchestratorContext) -> bool:
    if "event_orchestrator_enable" in ctx.settings:
        return _truthy(ctx.settings.get("event_orchestrator_enable"))
    env = os.getenv("EVENT_ORCHESTRATOR_ENABLE", "")
    return _truthy(env)


def handle_event(event: Event, ctx: OrchestratorContext | Dict[str, Any] | None = None) -> Plan:
    context = ctx
    if context is None:
        context = OrchestratorContext()
    elif isinstance(context, dict):
        context = OrchestratorContext(settings=context)
    if not _feature_flag_enabled(context):
        raise RuntimeError("Event orchestrator is disabled; set EVENT_ORCHESTRATOR_ENABLE=1 to enable.")
    plan = plan_for_event(event, ctx=context.settings)
    orchestrator = context.orchestrator or create_orchestrator()
    orchestrator.run_plan(plan)
    get_plan_store().save(plan)
    return plan


__all__ = ["handle_event", "OrchestratorContext"]
