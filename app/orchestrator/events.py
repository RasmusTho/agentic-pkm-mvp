from __future__ import annotations

from typing import Any, Dict

from app.agents.base.audit import audit_log
from app.events.types import (
    MCP_TOOL_CALL_FINISHED,
    MCP_TOOL_CALL_STARTED,
    ORCHESTRATOR_STEP_ERROR,
    ORCHESTRATOR_STEP_FINISHED,
    ORCHESTRATOR_STEP_STARTED,
)
from app.planner.schema import PlanStep

ORCHESTRATOR_AGENT = "orchestrator.runtime"


def _emit(action: str, *, object_id: str | None, trace_id: str | None, details: Dict[str, Any]) -> None:
    audit_log(object_id=object_id, agent=ORCHESTRATOR_AGENT, action=action, trace_id=trace_id, details=details)


def _base_step_details(plan_id: str, step: PlanStep) -> Dict[str, Any]:
    return {
        "plan_id": plan_id,
        "step_id": step.id,
        "step_kind": step.kind,
        "depends_on": list(step.depends_on),
        "description": step.description,
    }


def emit_step_started(*, plan_id: str, step: PlanStep, object_id: str | None, trace_id: str | None) -> None:
    details = _base_step_details(plan_id, step)
    _emit(ORCHESTRATOR_STEP_STARTED, object_id=object_id, trace_id=trace_id, details=details)


def emit_step_finished(
    *, plan_id: str, step: PlanStep, result: Dict[str, Any], object_id: str | None, trace_id: str | None
) -> None:
    details = _base_step_details(plan_id, step)
    details["result"] = result
    _emit(ORCHESTRATOR_STEP_FINISHED, object_id=object_id, trace_id=trace_id, details=details)


def emit_step_error(
    *, plan_id: str, step: PlanStep, error: str, object_id: str | None, trace_id: str | None
) -> None:
    details = _base_step_details(plan_id, step)
    details["error"] = error
    _emit(ORCHESTRATOR_STEP_ERROR, object_id=object_id, trace_id=trace_id, details=details)


def emit_mcp_tool_call_started(
    *, plan_id: str, step_id: str, tool_name: str, object_id: str | None, trace_id: str | None
) -> None:
    details = {"plan_id": plan_id, "step_id": step_id, "tool": tool_name}
    _emit(MCP_TOOL_CALL_STARTED, object_id=object_id, trace_id=trace_id, details=details)


def emit_mcp_tool_call_finished(
    *, plan_id: str, step_id: str, tool_name: str, result: Dict[str, Any], object_id: str | None, trace_id: str | None
) -> None:
    details = {"plan_id": plan_id, "step_id": step_id, "tool": tool_name, "result": result}
    _emit(MCP_TOOL_CALL_FINISHED, object_id=object_id, trace_id=trace_id, details=details)


__all__ = [
    "emit_step_started",
    "emit_step_finished",
    "emit_step_error",
    "emit_mcp_tool_call_started",
    "emit_mcp_tool_call_finished",
    "ORCHESTRATOR_AGENT",
]
