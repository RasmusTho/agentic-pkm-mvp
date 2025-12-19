from __future__ import annotations

import json
import os
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Protocol

from app.a2a.events import emit_agent_error_event, send_agent_request
from app.a2a.schema import new_error
from app.agents.base.loop import Agent
from app.mcp.vault_tools import VaultToolError, append_note

from app.planner.schema import PlanMetadata, PlanStep, ToolDescriptor
from app.planner.tools import get_tool_descriptor
from app.orchestrator.agents import AgentPermissionError, resolve_agent_config, validate_agent_permissions
from app.events.schema import OutboxEvent
from app.store.object_store import ObjectStore

from app.quality import timeout_wrapper

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


def _resolve_outbox_path() -> Path:
    env_path = os.getenv("INDEX_OUTBOX_PATH")
    if env_path:
        return Path(env_path)
    return Path("logs/index-outbox.jsonl")


def _write_outbox_events(outbox_path: Path, events: Iterable[Any]) -> None:
    outbox_path.parent.mkdir(parents=True, exist_ok=True)
    with outbox_path.open("a", encoding="utf-8") as handle:
        for event in events:
            if hasattr(event, "model_dump"):
                payload = event.model_dump(mode="json")
            elif isinstance(event, dict):
                payload = dict(event)
            else:
                continue
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


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
    budget_state: MutableMapping[str, int] | None = None


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
        response = self._default_agent.handle_agent_request(request)
        if response is None:
            error = new_error(
                sender="orchestrator.runtime",
                recipient=agent_name,
                error_type="not_implemented",
                error_message=f"{agent_name} cannot handle A2A messages.",
                correlation_id=str(request.id),
                trace_id=context.trace_id,
            )
            emit_agent_error_event(error, object_id=context.object_id)
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
        budget = context.budget_state if context.budget_state is not None else {}
        settings = context.tool_settings or {}
        max_tool_calls = None
        if "max_tool_calls" in settings:
            try:
                max_tool_calls = int(settings["max_tool_calls"])
            except Exception:
                max_tool_calls = None
        tool_calls = int(budget.get("tool_calls", 0))
        if max_tool_calls is not None and tool_calls >= max_tool_calls:
            raise StepExecutionError("tool call budget exhausted", error_type="budget_exhausted")
        budget["tool_calls"] = tool_calls + 1
        timeout_value = None
        if "tool_timeout_seconds" in settings:
            try:
                timeout_value = float(settings["tool_timeout_seconds"])
            except Exception:
                timeout_value = None
        try:
            result_payload = self._invoke_tool(descriptor, args, context, timeout_value)
        except (FutureTimeoutError, TimeoutError) as exc:
            raise StepExecutionError("tool call timed out", error_type="tool_timeout") from exc
        emit_mcp_tool_call_finished(
            plan_id=context.plan_id,
            step_id=step.id,
            tool_name=descriptor.name,
            result=result_payload,
            object_id=context.object_id,
            trace_id=context.trace_id,
        )
        return {"tool": descriptor.name, "result": result_payload}

    def _invoke_tool(
        self, descriptor: ToolDescriptor, args: Mapping[str, Any], context: StepContext, timeout_secs: float | None
    ) -> Dict[str, Any]:
        def call() -> Dict[str, Any]:
            if descriptor.kind == "internal":
                return self._run_internal_tool(descriptor.name, args, context)
            if self._should_use_real_tool(descriptor.name, context):
                return self._run_vault_append(args, context)
            return dict(descriptor.mock_result or {"status": "ok"})

        if timeout_secs is not None:
            return timeout_wrapper(call, timeout_secs)
        return call()

    def _run_internal_tool(self, name: str, args: Mapping[str, Any], context: StepContext) -> Dict[str, Any]:
        if name == "internal.ingest_external":
            try:
                from app.ingest.external import ingest_external_folder

                root = Path(args["root_dir"])
                summary = ingest_external_folder(root, limit=args.get("limit"))
                return {"status": "ok", "summary": asdict(summary)}
            except Exception as exc:
                raise StepExecutionError(f"external ingest failed: {exc}", error_type="internal_tool_error") from exc
        if name == "promotion.emit_intent":
            return self._emit_promotion_intent(args, context)
        raise StepExecutionError(f"unsupported internal tool '{name}'", error_type="invalid_tool")

    def _emit_promotion_intent(self, args: Mapping[str, Any], context: StepContext) -> Dict[str, Any]:
        note_uuid = args.get("note_uuid")
        action_id = args.get("action_id")
        if not note_uuid or not action_id:
            raise StepExecutionError("promotion tool requires note_uuid and action_id", error_type="invalid_tool_args")

        store = ObjectStore()
        obj = store.get_object(str(note_uuid))
        note_ref: Dict[str, Any] = {"uuid": str(note_uuid), "path": None, "origin": None}
        if obj:
            note_ref["path"] = getattr(obj, "source_ref", None)
            payload = obj.payload or {}
            note_ref["origin"] = payload.get("origin")

        payload: Dict[str, Any] = {
            "note": note_ref,
            "action": {
                "id": action_id,
                "label": args.get("action_label") or action_id,
                "downstream_event": args.get("downstream_event"),
            },
            "instruction": args.get("instruction") or "",
        }
        maturity = args.get("maturity")
        if maturity:
            payload["maturity"] = maturity
            payload.setdefault("action", {}).setdefault("params", {})["maturity"] = maturity

        trace_val = context.trace_id
        if trace_val:
            event = OutboxEvent(event="promote.intent.created", trace_id=trace_val, source="orchestrator.runtime", payload=payload)
        else:
            event = OutboxEvent(event="promote.intent.created", source="orchestrator.runtime", payload=payload)
        outbox_path = _resolve_outbox_path()
        _write_outbox_events(outbox_path, [event])
        return {"status": "ok", "event": event.event, "note_uuid": note_uuid, "action_id": action_id}

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
