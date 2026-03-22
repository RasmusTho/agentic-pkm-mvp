from __future__ import annotations

import json
import os
import time
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Protocol

from app.a2a.events import emit_agent_error_event, send_agent_request
from app.a2a.schema import new_error
from app.agents.base.loop import Agent
from app.domain.state_axes import normalize_promotion_payload
from app.mcp.vault_tools import VaultToolError, append_note
from app.orchestrator.agents import AgentPermissionError, resolve_agent_config, validate_agent_permissions
from app.planner.schema import PlanMetadata, PlanStep, ToolDescriptor
from app.planner.tools import get_tool_descriptor
from app.policy.enforce import assert_tool_allowed, is_policy_enforced
from app.quality import timeout_wrapper
from app.outbox.events import INDEX_OUTBOX_PATH
from app.store.object_store import ObjectStore
from app.events.schema import OutboxEvent

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
    return Path(INDEX_OUTBOX_PATH)


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
    agent_id: str | None = None


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
        agent_id = context.agent_id
        if is_policy_enforced() and not agent_id:
            raise StepExecutionError("policy: missing agent_id in StepContext", error_type="policy_denied")
        try:
            assert_tool_allowed(agent_id, descriptor.name)
        except PermissionError as exc:
            raise StepExecutionError(str(exc), error_type="policy_denied") from exc
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
            try:
                return _run_promotion_intent(args, context)
            except Exception as exc:
                raise StepExecutionError(f"promotion intent failed: {exc}", error_type="internal_tool_error") from exc
        raise StepExecutionError(f"unsupported internal tool '{name}'", error_type="invalid_tool")

    def _validate_tool_args(self, args: Mapping[str, Any], allowed_args: Mapping[str, str]) -> None:
        for arg_name, arg_type in allowed_args.items():
            if arg_name not in args:
                continue
            expected_types = self._TYPE_MAP.get(arg_type, tuple())
            if not isinstance(args[arg_name], expected_types):
                raise StepExecutionError(
                    f"argument '{arg_name}' must be of type {arg_type}", error_type="invalid_tool_args"
                )

    def _validate_required_args(self, args: Mapping[str, Any], required_args: Iterable[str]) -> None:
        for arg in required_args:
            if arg not in args:
                raise StepExecutionError(f"missing required argument '{arg}'", error_type="invalid_tool_args")

    def _should_use_real_tool(self, tool_name: str, context: StepContext) -> bool:
        if tool_name != "mcp.vault.append_note":
            return False
        settings = context.tool_settings or {}
        allowlist = settings.get("allowed_mcp_tools")
        enable_flag = settings.get("mcp_vault_enable")
        if enable_flag is None:
            enable_flag = settings.get("mcp.enable")
        if allowlist is None:
            return _flag_enabled(enable_flag)
        try:
            return tool_name in allowlist and _flag_enabled(enable_flag)
        except Exception:
            return False

    def _run_vault_append(self, args: Mapping[str, Any], context: StepContext) -> Dict[str, Any]:
        try:
            vault_root = context.tool_settings.get("vault_root") if context.tool_settings else None
            note_path = append_note(
                title=str(args.get("title") or ""),
                body=str(args.get("body") or ""),
                tags=args.get("tags") or [],
                metadata=args.get("metadata") or {},
                vault_root=vault_root,
            )
            event_kwargs = {
                "event": "mcp.vault.append_note",
                "source": "orchestrator.runtime",
                "payload": {"note_path": str(note_path)},
            }
            if context.trace_id:
                event_kwargs["trace_id"] = context.trace_id
            mcp_event = OutboxEvent(**event_kwargs)
            _write_outbox_events(_resolve_outbox_path(), [mcp_event])
            return {"status": "ok", "note_path": str(note_path)}
        except VaultToolError as exc:
            raise StepExecutionError(f"vault append failed: {exc}", error_type="mcp_tool_error") from exc


def _run_promotion_intent(args: Mapping[str, Any], context: StepContext) -> Dict[str, Any]:
    note_uuid = str(args.get("note_uuid") or "")
    note_info: Dict[str, Any] = {"uuid": note_uuid}
    try:
        obj = ObjectStore().get_object(note_uuid)
    except Exception:
        obj = None
    if obj:
        if getattr(obj, "source_ref", None):
            note_info["path"] = str(obj.source_ref)
        if isinstance(getattr(obj, "payload", None), dict):
            origin = obj.payload.get("origin")
            if origin:
                note_info["origin"] = origin

    action_id = str(args.get("action_id") or "")
    payload: Dict[str, Any] = {
        "note": note_info,
        "action": {"id": action_id, "label": str(args.get("action_label") or action_id or "")},
    }
    downstream_event = args.get("downstream_event")
    if downstream_event:
        payload["action"]["downstream_event"] = str(downstream_event)
    instruction = args.get("instruction")
    if instruction:
        payload["instruction"] = str(instruction)
    payload = normalize_promotion_payload(
        {
            **payload,
            "maturity": args.get("target_maturity") or args.get("maturity"),
            "review_state": args.get("review_state"),
        }
    )

    event_kwargs = {
        "event": "promote.intent.created",
        "source": "orchestrator.runtime",
        "payload": payload,
    }
    if context.trace_id:
        event_kwargs["trace_id"] = context.trace_id
    promote_event = OutboxEvent(**event_kwargs)
    _write_outbox_events(_resolve_outbox_path(), [promote_event])
    return {"status": "ok", "event": promote_event.model_dump(mode="json")}


__all__ = ["PlanExecutor", "StepContext", "StepExecutionError", "MockPlanExecutor"]
