from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping, MutableMapping, Set, Union

from app.planner.schema import Plan, PlanStep

from .events import emit_step_error, emit_step_finished, emit_step_started
from .executor import MockPlanExecutor, PlanExecutor, StepContext, StepExecutionError


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def _get_orchestrator_version() -> str:
    """Get orchestrator version from environment, defaulting to v1."""
    version = os.environ.get("ORCHESTRATOR_VERSION", "v1").lower()
    if version not in ("v1", "v2"):
        return "v1"
    return version


def _default_agent_id_for_flow(flow_id: str | None) -> str | None:
    if not flow_id:
        return None
    normalized = str(flow_id).strip().lower()
    if normalized in {"ask", "qa", "ask.graph.v1"}:
        return "ask.v1"
    return None


def _resolve_step_agent_id(step: PlanStep, flow_id: str | None, plan_context: Mapping[str, Any] | None) -> str | None:
    if getattr(step, "agent_id", None):
        return step.agent_id
    metadata = None
    try:
        metadata = step.metadata
    except Exception:
        metadata = None
    if isinstance(metadata, Mapping):
        meta_agent = metadata.get("agent_id")
        if isinstance(meta_agent, str) and meta_agent.strip():
            return meta_agent.strip()
    if plan_context and isinstance(plan_context, Mapping):
        ctx_agent = plan_context.get("agent_id")
        if isinstance(ctx_agent, str) and ctx_agent.strip():
            return ctx_agent.strip()
    return _default_agent_id_for_flow(flow_id)


class OrchestratorError(Exception):
    """Base error for orchestrator failures."""


class PlanValidationError(OrchestratorError):
    """Raised when a plan violates structural requirements."""


class Orchestrator:
    def __init__(self, executor: PlanExecutor | None = None, *, tool_settings: Mapping[str, Any] | None = None) -> None:
        self._executor = executor or MockPlanExecutor()
        self._tool_settings = dict(tool_settings) if tool_settings else None
        self._run_plan_impl = None  # Can be set by factory to use alternate implementation

    def run_plan(self, plan: Plan) -> List[Dict[str, Any]]:
        # If using alternate implementation (e.g., V2), delegate to it
        if self._run_plan_impl is not None:
            return self._run_plan_impl(plan)
        self._validate_plan(plan)
        results: List[Dict[str, Any]] = []
        plan_results: Dict[str, Dict[str, Any]] = {}
        object_id = plan.meta.source_object_uuid or None
        trace_id = plan.meta.trace_id

        plan_tool_settings = None
        if plan.context and isinstance(plan.context.get("tool_settings"), Mapping):
            plan_tool_settings = dict(plan.context.get("tool_settings") or {})
        context_tool_settings = self._tool_settings
        if plan_tool_settings:
            if context_tool_settings:
                merged = dict(context_tool_settings)
                merged.update(plan_tool_settings)
                context_tool_settings = merged
            else:
                context_tool_settings = plan_tool_settings

        budget_state: MutableMapping[str, int] = {"steps": 0, "tool_calls": 0}
        max_steps = _coerce_int(context_tool_settings.get("max_steps")) if context_tool_settings else None

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
            elif plan.context and plan.context.get("flows"):
                legacy_flows = plan.context.get("flows") or []
                if isinstance(legacy_flows, list) and legacy_flows:
                    plan_flow_id = legacy_flows[0]

            if max_steps is not None and budget_state.get("steps", 0) >= max_steps:
                results.append({
                    "step_id": step.id,
                    "status": "error",
                    "error": "step budget exhausted",
                    "error_type": "budget_exhausted",
                })
                break

            budget_state["steps"] = budget_state.get("steps", 0) + 1

            agent_id = _resolve_step_agent_id(step, plan_flow_id, plan.context)
            context = StepContext(
                plan_id=plan.id,
                object_id=object_id,
                trace_id=trace_id,
                metadata=plan.meta,
                results=plan_results,
                flow_id=plan_flow_id,
                event_type=plan.trigger.event_type if plan.trigger else None,
                tool_settings=context_tool_settings,
                budget_state=budget_state,
                agent_id=agent_id,
            )
            try:
                output = self._executor.execute_step(step, context)
            except StepExecutionError as exc:
                error_message = str(exc)
                error_type = getattr(exc, "error_type", None)
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


def create_orchestrator(executor: PlanExecutor | None = None, *, tool_settings: Mapping[str, Any] | None = None) -> Orchestrator:
    """Factory function to create the appropriate orchestrator version.

    Checks ORCHESTRATOR_VERSION environment variable:
    - "v2" -> returns Orchestrator wrapping V2 implementation
    - "v1" or unset/unrecognized -> returns standard V1 Orchestrator
    """
    version = _get_orchestrator_version()
    if version == "v2":
        from .v2_runtime import OrchestratorV2
        # Wrap V2 in the standard Orchestrator interface
        v2_impl = OrchestratorV2(executor=executor, tool_settings=tool_settings)
        # Return an Orchestrator that delegates to V2
        orch = Orchestrator(executor=executor, tool_settings=tool_settings)
        orch._run_plan_impl = v2_impl.run_plan
        return orch
    else:
        return Orchestrator(executor=executor, tool_settings=tool_settings)


__all__ = ["Orchestrator", "OrchestratorError", "PlanValidationError", "create_orchestrator"]
