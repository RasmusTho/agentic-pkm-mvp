from __future__ import annotations

from typing import Any, Dict, List, Set

from app.planner.schema import Plan, PlanStep

from .events import emit_step_error, emit_step_finished, emit_step_started
from .executor import MockPlanExecutor, PlanExecutor, StepContext, StepExecutionError


class OrchestratorError(Exception):
    """Base error for orchestrator failures."""


class PlanValidationError(OrchestratorError):
    """Raised when a plan violates structural requirements."""


class Orchestrator:
    def __init__(self, executor: PlanExecutor | None = None) -> None:
        self._executor = executor or MockPlanExecutor()

    def run_plan(self, plan: Plan) -> List[Dict[str, Any]]:
        self._validate_plan(plan)
        results: List[Dict[str, Any]] = []
        plan_results: Dict[str, Dict[str, Any]] = {}
        object_id = plan.meta.source_object_uuid or None
        trace_id = plan.meta.trace_id
        for step in plan.steps:
            emit_step_started(plan_id=plan.id, step=step, object_id=object_id, trace_id=trace_id)
            context = StepContext(
                plan_id=plan.id,
                object_id=object_id,
                trace_id=trace_id,
                metadata=plan.meta,
                results=plan_results,
            )
            try:
                output = self._executor.execute_step(step, context)
            except StepExecutionError as exc:
                error_message = str(exc)
                emit_step_error(plan_id=plan.id, step=step, error=error_message, object_id=object_id, trace_id=trace_id)
                results.append({"step_id": step.id, "status": "error", "error": error_message})
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
