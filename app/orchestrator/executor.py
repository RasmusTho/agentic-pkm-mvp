from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, MutableMapping, Protocol

from app.a2a.events import send_agent_request
from app.agents.base.loop import Agent
from app.mcp.vault_tools import VaultToolError, append_note


from app.planner.schema import PlanMetadata, PlanStep
from app.planner.tools import get_tool_descriptor
from app.orchestrator.agents import AgentPermissionError, resolve_agent_config, validate_agent_permissions

from .events import emit_mcp_tool_call_finished, emit_mcp_tool_call_started


def _flag_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if not normalized:
            return False
        return normalized in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)):
        return value != 0
    return bool(value)


class StepExecutionError(Exception):
    """Raised when a plan step cannot be executed."""

    def __init__(self, message: str, *, error_type: str | None = None) -> None:
        super().__init__(message)
        self.error_type = error_type


@dataclass
class StepContext:
    plan_id: str
    object_id: str | None
    trace_id: str | None
    metadata: PlanMetadata
    results: MutableMapping[str, Dict[str, Any]] = field(default_factory=dict)
    flow_id: str | None = None
    event_type: str | None = None
    tool_settings: Mapping[str, Any] | None = None


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
        "array": (list, tuple),
        "object": (dict,),
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
        raise StepExecutionError(f"unsupported step kind '{step.kind}'", error_type="invalid_step_kind")

    def _execute_agent_call(self, step: PlanStep, context: StepContext) -> Dict[str, Any]:
        agent_name = step.agent or "unknown-agent"
        config = resolve_agent_config(agent_name, flow_id=context.flow_id, event_type=context.event_type)
        if config:
            try:
                validate_agent_permissions(config, flow_id=context.flow_id, event_type=context.event_type)
            except AgentPermissionError as exc:
                raise StepExecutionError(f"Agent permission denied: {exc}", error_type="agent_permission") from exc
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
            raise StepExecutionError("tool_call step missing tool name", error_type="invalid_tool")
        descriptor = get_tool_descriptor(step.tool)
        if descriptor is None:
            raise StepExecutionError(f"unknown MCP tool '{step.tool}'", error_type="invalid_tool")
        args = dict(step.tool_args or {})
        if "content" in args and "body" not in args:
            args["body"] = args["content"]
        self._validate_tool_args(args, descriptor.allowed_args)
        self._validate_required_args(args, descriptor.schema.get("required", []))
        emit_mcp_tool_call_started(
            plan_id=context.plan_id,
            step_id=step.id,
            tool_name=descriptor.name,
            object_id=context.object_id,
            trace_id=context.trace_id,
        )
        if self._should_use_real_tool(descriptor.name, context):
            result_payload = self._run_vault_append(args, context)
        else:
            result_payload = dict(descriptor.mock_result or {"status": "ok"})
        emit_mcp_tool_call_finished(
            plan_id=context.plan_id,
            step_id=step.id,
            tool_name=descriptor.name,
            result=result_payload,
            object_id=context.object_id,
            trace_id=context.trace_id,
        )
        return {"tool": descriptor.name, "result": result_payload}

    def _should_use_real_tool(self, tool_name: str, context: StepContext) -> bool:
        if tool_name != "mcp.vault.append_note":
            return False
        settings = context.tool_settings or {}
        if "mcp_vault_enable" in settings:
            return _flag_enabled(settings["mcp_vault_enable"])
        env_value = os.getenv("MCP_VAULT_ENABLE")
        if env_value is not None:
            return _flag_enabled(env_value)
        return False

    def _run_vault_append(self, args: Mapping[str, Any], context: StepContext) -> Dict[str, Any]:
        settings = context.tool_settings or {}
        relative_dir = settings.get("vault_relative_dir") or "_mcp"
        try:
            note_path = append_note(
                title=args["title"],
                body=args["body"],
                tags=args.get("tags"),
                metadata=args.get("metadata"),
                vault_root=settings.get("vault_root"),
                settings=settings,
                relative_dir=str(relative_dir),
            )
        except VaultToolError as exc:
            raise StepExecutionError(f"vault tool failed: {exc}", error_type="vault_tool_error") from exc
        return {"status": "ok", "note_path": str(note_path)}

    def _validate_tool_args(self, args: Mapping[str, Any], allowed_args: Mapping[str, str]) -> None:
        allowed_keys = set(allowed_args.keys())
        unknown = set(args.keys()) - allowed_keys
        if unknown:
            raise StepExecutionError(
                f"unexpected arguments for tool: {sorted(unknown)}",
                error_type="invalid_tool_args",
            )
        for key, type_name in allowed_args.items():
            if key not in args:
                continue
            expected = self._TYPE_MAP.get(type_name, (object,))
            if not isinstance(args[key], expected):
                raise StepExecutionError(
                    f"argument '{key}' must be of type {type_name}",
                    error_type="invalid_tool_args",
                )

    def _validate_required_args(self, args: Mapping[str, Any], required: list[str]) -> None:
        for key in required:
            if key not in args:
                raise StepExecutionError(
                    f"missing required argument '{key}'",
                    error_type="invalid_tool_args",
                )


__all__ = ["StepExecutionError", "StepContext", "PlanExecutor", "MockPlanExecutor"]
