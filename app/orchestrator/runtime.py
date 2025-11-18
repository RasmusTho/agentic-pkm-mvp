from __future__ import annotations

from typing import Any, Dict, List, Mapping, Set

from app.planner.schema import Plan, PlanStep

from .events import emit_step_error, emit_step_finished, emit_step_started
from .executor import MockPlanExecutor, PlanExecutor, StepContext, StepExecutionError


class OrchestratorError(Exception):
    """Base error for orchestrator failures."""


class PlanValidationError(OrchestratorError):
    """Raised when a plan violates structural requirements."""


class Orchestrator:
    def __init__(self, executor: PlanExecutor | None = None, *, tool_settings: Mapping[str, Any] | None = None) -> None:
        self._executor = executor or MockPlanExecutor()
        self._tool_settings = dict(tool_settings) if tool_settings else None

    def run_plan(self, plan: Plan) -> List[Dict[str, Any]]:
        self._validate_plan(plan)
        results: List[Dict[str, Any]] = []
        plan_results: Dict[str, Dict[str, Any]] = {}
        object_id = plan.meta.source_object_uuid or None
        trace_id = plan.meta.trace_id
        for step in plan.steps:
            emit_step_started(plan_id=plan.id, step=step, object_id=object_id, trace_id=trace_id)
            plan_flow_id = None
            profile_selection = (plan.context or {}).get("profile_selection") if plan.context else None
            if isinstance(profile_selection, dict) and profile_selection.get("flow_id"):
                plan_flow_id = profile_selection.get("flow_id")
            elif plan.context and plan.context.get("flow_ids"):
                flow_ids = plan.context.get("flow_ids") or []
                if isinstance(flow_ids, list) and flow_ids:
                    plan_flow_id = flow_ids[0]
            plan_tool_settings = None
            if plan.context and isinstance(plan.context.get('tool_settings'), Mapping):
                plan_tool_settings = dict(plan.context.get('tool_settings') or {})
            context_tool_settings = self._tool_settings
            if plan_tool_settings:
                if context_tool_settings:
                    merged = dict(context_tool_settings)
                    merged.update(plan_tool_settings)
                    context_tool_settings = merged
                else:
                    context_tool_settings = plan_tool_settings
            context = StepContext(
                plan_id=plan.id,
                object_id=object_id,
                trace_id=trace_id,
                metadata=plan.meta,
                results=plan_results,
                flow_id=plan_flow_id,
                event_type=plan.trigger.event_type if plan.trigger else None,
                tool_settings=context_tool_settings,
            )
            try:
                output = self._executor.execute_step(step, context)
            except StepExecutionError as exc:
                error_message = str(exc)
                error_type = getattr(exc, 'error_type', None)
                emit_step_error(
                    plan_id=plan.id,
                    step=step,
                    error=error_message,
                    error_type=error_type,
                    object_id=object_id,
                    trace_id=trace_id,
                )
                entry = {"step_id": step.id, "status": "error", "error": error_message}
                if error_type:
                    entry["error_type"] = error_type
                results.append(entry)
                break
            else:
                emit_step_finished(
                    plan_id=plan.id,
                    step=step,
                    result=output,
                    object_id=object_id,
                    trace_id=trace_id,
                )
                plan_results[step.id] = output
                results.append({"step_id": step.id, "status": "ok", "result": output})
        return results

    def _validate_plan(self, plan: Plan) -> None:
        if not plan.id:
            raise PlanValidationError("plan missing identifier")
        if not plan.meta.source_object_uuid:
            raise PlanValidationError("plan missing source object reference")
        seen: Set[str] = set()
        for step in plan.steps:
            self._validate_step(step, seen)
            seen.add(step.id)

    def _validate_step(self, step: PlanStep, seen: Set[str]) -> None:
        if not step.id:
            raise PlanValidationError("plan step missing identifier")
        if step.id in seen:
            raise PlanValidationError(f"duplicate plan step id '{step.id}'")
        for dep in step.depends_on:
            if dep not in seen:
                raise PlanValidationError(f"step '{step.id}' depends on unknown or future step '{dep}'")
        if step.kind == "agent_call" and not step.agent:
            raise PlanValidationError(f"agent_call step '{step.id}' missing agent name")
        if step.kind == "tool_call" and not step.tool:
            raise PlanValidationError(f"tool_call step '{step.id}' missing tool name")


__all__ = ["Orchestrator", "OrchestratorError", "PlanValidationError"]
