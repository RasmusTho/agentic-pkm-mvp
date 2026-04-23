from __future__ import annotations

from typing import Any, Dict

from app.agents.base.audit import audit_log
from app.events.types import (
    MCP_TOOL_CALL_FINISHED,
    MCP_TOOL_CALL_STARTED,
    ORCHESTRATOR_COMPENSATION_STARTED,
    ORCHESTRATOR_COMPENSATION_STEP_COMPLETED,
    ORCHESTRATOR_COMPENSATION_STEP_FAILED,
    ORCHESTRATOR_ROLLED_BACK,
    ORCHESTRATOR_STEP_ERROR,
    ORCHESTRATOR_STEP_FINISHED,
    ORCHESTRATOR_STEP_RETRY,
    ORCHESTRATOR_STEP_RETRY_EXHAUSTED,
    ORCHESTRATOR_STEP_STARTED,
)
from app.orchestrator.delivery_sla import map_delivery_sla_terminal_state
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
    details["delivery_sla_state"] = map_delivery_sla_terminal_state(status="ok")
    _emit(ORCHESTRATOR_STEP_FINISHED, object_id=object_id, trace_id=trace_id, details=details)


def emit_step_error(
    *,
    plan_id: str,
    step: PlanStep,
    error: str,
    error_type: str | None,
    object_id: str | None,
    trace_id: str | None,
) -> None:
    details = _base_step_details(plan_id, step)
    details["error"] = error
    details["delivery_sla_state"] = map_delivery_sla_terminal_state(status="error", error_type=error_type)
    if error_type:
        details["error_type"] = error_type
    _emit(ORCHESTRATOR_STEP_ERROR, object_id=object_id, trace_id=trace_id, details=details)


def emit_step_retry(
    *,
    plan_id: str,
    step: PlanStep,
    attempt: int,
    backoff_ms: int,
    error: str,
    error_type: str | None,
    object_id: str | None,
    trace_id: str | None,
) -> None:
    """Emit a retry attempt event with observability details."""
    details = _base_step_details(plan_id, step)
    details["attempt"] = attempt
    details["backoff_ms"] = backoff_ms
    details["error"] = error
    if error_type:
        details["error_type"] = error_type
    _emit(ORCHESTRATOR_STEP_RETRY, object_id=object_id, trace_id=trace_id, details=details)


def emit_step_retry_exhausted(
    *,
    plan_id: str,
    step: PlanStep,
    max_retries: int,
    final_error: str,
    error_type: str | None,
    object_id: str | None,
    trace_id: str | None,
) -> None:
    """Emit a retry exhaustion event when all retry attempts are consumed."""
    details = _base_step_details(plan_id, step)
    details["max_retries"] = max_retries
    details["final_error"] = final_error
    if error_type:
        details["error_type"] = error_type
    _emit(ORCHESTRATOR_STEP_RETRY_EXHAUSTED, object_id=object_id, trace_id=trace_id, details=details)


def emit_compensation_started(
    *,
    plan_id: str,
    failed_step_id: str,
    steps_to_compensate: list[str],
    object_id: str | None,
    trace_id: str | None,
) -> None:
    details = {
        "plan_id": plan_id,
        "failed_step_id": failed_step_id,
        "steps_to_compensate": steps_to_compensate,
    }
    _emit(ORCHESTRATOR_COMPENSATION_STARTED, object_id=object_id, trace_id=trace_id, details=details)


def emit_compensation_step_completed(
    *,
    plan_id: str,
    step_id: str,
    compensate_fn: str,
    object_id: str | None,
    trace_id: str | None,
) -> None:
    details = {"plan_id": plan_id, "step_id": step_id, "compensate_fn": compensate_fn}
    _emit(ORCHESTRATOR_COMPENSATION_STEP_COMPLETED, object_id=object_id, trace_id=trace_id, details=details)


def emit_compensation_step_failed(
    *,
    plan_id: str,
    step_id: str,
    compensate_fn: str,
    error: str,
    object_id: str | None,
    trace_id: str | None,
) -> None:
    details = {"plan_id": plan_id, "step_id": step_id, "compensate_fn": compensate_fn, "error": error}
    _emit(ORCHESTRATOR_COMPENSATION_STEP_FAILED, object_id=object_id, trace_id=trace_id, details=details)


def emit_orchestration_rolled_back(
    *,
    plan_id: str,
    failed_step: str,
    compensated_steps: list[str],
    compensation_failures: list[str],
    object_id: str | None,
    trace_id: str | None,
) -> None:
    details = {
        "plan_id": plan_id,
        "failed_step": failed_step,
        "compensated_steps": compensated_steps,
        "compensation_failures": compensation_failures,
    }
    _emit(ORCHESTRATOR_ROLLED_BACK, object_id=object_id, trace_id=trace_id, details=details)


def emit_mcp_tool_call_started(
    *,
    plan_id: str,
    step_id: str,
    tool_name: str,
    object_id: str | None,
    trace_id: str | None,
    route: Dict[str, Any] | None = None,
) -> None:
    details = {"plan_id": plan_id, "step_id": step_id, "tool": tool_name}
    if route:
        details.update(route)
    _emit(MCP_TOOL_CALL_STARTED, object_id=object_id, trace_id=trace_id, details=details)


def emit_mcp_tool_call_finished(
    *,
    plan_id: str,
    step_id: str,
    tool_name: str,
    result: Dict[str, Any],
    object_id: str | None,
    trace_id: str | None,
    route: Dict[str, Any] | None = None,
) -> None:
    details = {"plan_id": plan_id, "step_id": step_id, "tool": tool_name, "result": result}
    if route:
        details.update(route)
    _emit(MCP_TOOL_CALL_FINISHED, object_id=object_id, trace_id=trace_id, details=details)


__all__ = [
    "emit_step_started",
    "emit_step_finished",
    "emit_step_error",
    "emit_step_retry",
    "emit_step_retry_exhausted",
    "emit_compensation_started",
    "emit_compensation_step_completed",
    "emit_compensation_step_failed",
    "emit_orchestration_rolled_back",
    "emit_mcp_tool_call_started",
    "emit_mcp_tool_call_finished",
    "ORCHESTRATOR_AGENT",
]
