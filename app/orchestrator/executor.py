from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, MutableMapping, Protocol

from app.a2a.events import send_agent_request
from app.agents.base.loop import Agent
from app.planner.schema import PlanMetadata, PlanStep
from app.planner.tools import get_tool_descriptor

from .events import emit_mcp_tool_call_finished, emit_mcp_tool_call_started


class StepExecutionError(Exception):
    """Raised when a plan step cannot be executed."""


@dataclass
class StepContext:
    plan_id: str
    object_id: str | None
    trace_id: str | None
    metadata: PlanMetadata
    results: MutableMapping[str, Dict[str, Any]] = field(default_factory=dict)


class PlanExecutor(Protocol):
    def execute_step(self, step: PlanStep, context: StepContext) -> Dict[str, Any]:
        ...


class MockPlanExecutor(PlanExecutor):
    """Deterministic executor used in CI and development."""

    _TYPE_MAP: Dict[str, tuple[type, ...]] = {
        "string": (str,),
        "integer": (int,),
        "number": (int, float),
        "boolean": (bool,),
    }

    def __init__(self) -> None:
        self._default_agent = Agent()

    def execute_step(self, step: PlanStep, context: StepContext) -> Dict[str, Any]:
        if step.kind == "agent_call":
            return self._execute_agent_call(step, context)
        if step.kind == "tool_call":
            return self._execute_tool_call(step, context)
        if step.kind == "decision":
            return {"decision": step.description, "depends_on": list(step.depends_on)}
        if step.kind == "note":
            return {"note": step.description}
        raise StepExecutionError(f"unsupported step kind '{step.kind}'")

    def _execute_agent_call(self, step: PlanStep, context: StepContext) -> Dict[str, Any]:
        agent_name = step.agent or "unknown-agent"
        request = send_agent_request(
            sender="orchestrator.runtime",
            recipient=agent_name,
            intent=step.intent,
            payload={
                "plan_id": context.plan_id,
                "step_id": step.id,
                "object_id": context.object_id,
                "description": step.description,
            },
            metadata={"plan": context.metadata.model_dump(), "step": step.metadata},
            correlation_id=step.id,
            trace_id=context.trace_id,
            object_id=context.object_id,
        )
        # Dispatch to the default handler to keep behavior deterministic and audited.
        self._default_agent.handle_agent_request(request)
        return {"agent": agent_name, "request_id": str(request.id)}

    def _execute_tool_call(self, step: PlanStep, context: StepContext) -> Dict[str, Any]:
        if not step.tool:
            raise StepExecutionError("tool_call step missing tool name")
        descriptor = get_tool_descriptor(step.tool)
        if descriptor is None:
            raise StepExecutionError(f"unknown MCP tool '{step.tool}'")
        args = step.tool_args or {}
        self._validate_tool_args(args, descriptor.allowed_args)
        self._validate_required_args(args, descriptor.schema.get("required", []))
        emit_mcp_tool_call_started(
            plan_id=context.plan_id,
            step_id=step.id,
            tool_name=descriptor.name,
            object_id=context.object_id,
            trace_id=context.trace_id,
        )
        result = dict(descriptor.mock_result or {"status": "ok"})
        emit_mcp_tool_call_finished(
            plan_id=context.plan_id,
            step_id=step.id,
            tool_name=descriptor.name,
            result=result,
            object_id=context.object_id,
            trace_id=context.trace_id,
        )
        return {"tool": descriptor.name, "result": result}

    def _validate_tool_args(self, args: Mapping[str, Any], allowed_args: Mapping[str, str]) -> None:
        allowed_keys = set(allowed_args.keys())
        unknown = set(args.keys()) - allowed_keys
        if unknown:
            raise StepExecutionError(f"unexpected arguments for tool: {sorted(unknown)}")
        for key, type_name in allowed_args.items():
            if key not in args:
                continue
            expected = self._TYPE_MAP.get(type_name, (object,))
            if not isinstance(args[key], expected):
                raise StepExecutionError(f"argument '{key}' must be of type {type_name}")

    def _validate_required_args(self, args: Mapping[str, Any], required: list[str]) -> None:
        for key in required:
            if key not in args:
                raise StepExecutionError(f"missing required argument '{key}'")


__all__ = ["StepExecutionError", "StepContext", "PlanExecutor", "MockPlanExecutor"]
