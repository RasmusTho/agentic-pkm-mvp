from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Protocol

from app.components.settings.tools_loader import load_tools
from app.orchestrator.events import emit_mcp_tool_call_finished, emit_mcp_tool_call_started
from app.orchestrator.executor import MockPlanExecutor, StepContext, StepExecutionError
from app.planner.schema import ToolDescriptor
from app.planner.tools import MCP_TOOL_DESCRIPTORS


class RemoteMCPProvider(Protocol):
    def list_descriptors(self) -> Mapping[str, ToolDescriptor]:
        ...

    def execute_tool_call(
        self,
        *,
        tool_name: str,
        tool_args: Mapping[str, Any] | None,
        context: StepContext,
        step_id: str,
        description: str,
    ) -> Dict[str, Any]:
        ...


@dataclass
class MCPToolProvider:
    """Registry-backed tool provider that executes via existing executor paths."""

    remote_provider: RemoteMCPProvider | None = None

    def list_descriptors(self, tool_settings: Mapping[str, Any] | None = None) -> Dict[str, ToolDescriptor]:
        descriptors = self._list_local_descriptors()
        if _remote_multiplex_enabled(tool_settings) and self.remote_provider is not None:
            try:
                remote = dict(self.remote_provider.list_descriptors())
                descriptors.update(self._filter_supported(remote))
            except Exception:
                # Remote descriptor discovery is best-effort; keep local registry route available.
                pass
        return self._filter_supported(descriptors)

    def get_descriptor(self, tool_name: str, tool_settings: Mapping[str, Any] | None = None) -> ToolDescriptor | None:
        return self.list_descriptors(tool_settings).get(tool_name)

    def execute_tool_call(
        self,
        *,
        tool_name: str,
        tool_args: Mapping[str, Any] | None,
        context: StepContext,
        step_id: str,
        description: str,
        executor: MockPlanExecutor | None = None,
    ) -> Dict[str, Any]:
        route = self._resolve_route(context.tool_settings)
        descriptor = self._resolve_descriptor_for_execution(
            tool_name=tool_name,
            tool_settings=context.tool_settings,
            route=route,
        )
        if descriptor is None:
            raise StepExecutionError(f"unknown MCP tool '{tool_name}'", error_type="invalid_tool")

        active_executor = executor or MockPlanExecutor()
        call_args = dict(tool_args or {})
        # Keep validation aligned to local contract when available.
        local_descriptor = self._filter_supported(self._list_local_descriptors()).get(tool_name)
        validation_descriptor = local_descriptor or descriptor
        active_executor._validate_tool_args(call_args, validation_descriptor.allowed_args)  # noqa: SLF001
        active_executor._validate_required_args(call_args, validation_descriptor.schema.get("required", []))  # noqa: SLF001
        timeout_value = None
        settings = context.tool_settings or {}
        if "tool_timeout_seconds" in settings:
            try:
                timeout_value = float(settings["tool_timeout_seconds"])
            except Exception:
                timeout_value = None

        emit_mcp_tool_call_started(
            plan_id=context.plan_id,
            step_id=step_id,
            tool_name=descriptor.name,
            object_id=context.object_id,
            trace_id=context.trace_id,
            route=route,
        )
        result_payload = self._execute_with_route(
            route=route,
            descriptor=descriptor,
            call_args=call_args,
            context=context,
            step_id=step_id,
            description=description,
            timeout_value=timeout_value,
            executor=active_executor,
        )
        emit_mcp_tool_call_finished(
            plan_id=context.plan_id,
            step_id=step_id,
            tool_name=descriptor.name,
            result=result_payload,
            object_id=context.object_id,
            trace_id=context.trace_id,
            route=route,
        )
        return {"tool": descriptor.name, "result": result_payload}

    def _resolve_descriptor_for_execution(
        self,
        *,
        tool_name: str,
        tool_settings: Mapping[str, Any] | None,
        route: Dict[str, str],
    ) -> ToolDescriptor | None:
        local_descriptors = self._filter_supported(self._list_local_descriptors())
        if route.get("provider_route") != "remote_multiplex" or self.remote_provider is None:
            return local_descriptors.get(tool_name)

        try:
            remote_descriptors = dict(self.remote_provider.list_descriptors())
        except Exception:
            route["provider_route"] = "local_registry"
            route["provider_route_reason"] = "remote_descriptor_list_error"
            route["provider_route_attempted"] = "remote_multiplex"
            return local_descriptors.get(tool_name)

        merged = dict(local_descriptors)
        merged.update(self._filter_supported(remote_descriptors))
        return merged.get(tool_name)

    def _resolve_route(self, tool_settings: Mapping[str, Any] | None) -> Dict[str, str]:
        if not _remote_multiplex_enabled(tool_settings):
            return {"provider_route": "local_registry", "provider_route_reason": "remote_disabled"}
        if self.remote_provider is None:
            return {"provider_route": "local_registry", "provider_route_reason": "remote_unavailable"}
        return {"provider_route": "remote_multiplex"}

    def _execute_with_route(
        self,
        *,
        route: Dict[str, str],
        descriptor: ToolDescriptor,
        call_args: Dict[str, Any],
        context: StepContext,
        step_id: str,
        description: str,
        timeout_value: float | None,
        executor: MockPlanExecutor,
    ) -> Dict[str, Any]:
        if route.get("provider_route") == "remote_multiplex" and self.remote_provider is not None:
            try:
                response = self.remote_provider.execute_tool_call(
                    tool_name=descriptor.name,
                    tool_args=call_args,
                    context=context,
                    step_id=step_id,
                    description=description,
                )
                if isinstance(response, Mapping) and "result" in response:
                    return dict(response["result"])
                return dict(response)
            except Exception:
                route["provider_route"] = "local_registry"
                route["provider_route_reason"] = "remote_provider_error"
                route["provider_route_attempted"] = "remote_multiplex"
                local_descriptor = self._filter_supported(self._list_local_descriptors()).get(descriptor.name)
                if local_descriptor is None:
                    raise StepExecutionError(
                        f"remote provider failed and no local fallback is available for '{descriptor.name}'",
                        error_type="tool_unavailable",
                    ) from None
                descriptor = local_descriptor
                executor._validate_tool_args(call_args, descriptor.allowed_args)  # noqa: SLF001
                executor._validate_required_args(call_args, descriptor.schema.get("required", []))  # noqa: SLF001

        # Always invoke with local descriptor when present to keep local contract semantics.
        local_descriptor = self._filter_supported(self._list_local_descriptors()).get(descriptor.name)
        invoke_descriptor = local_descriptor or descriptor
        return executor._invoke_tool(invoke_descriptor, call_args, context, timeout_value)  # noqa: SLF001

    def _list_local_descriptors(self) -> Dict[str, ToolDescriptor]:
        return _load_registry_descriptors()

    def _filter_supported(self, descriptors: Mapping[str, ToolDescriptor]) -> Dict[str, ToolDescriptor]:
        supported = set(MCP_TOOL_DESCRIPTORS.keys())
        return {name: descriptor for name, descriptor in descriptors.items() if name in supported}


def _load_registry_descriptors() -> Dict[str, ToolDescriptor]:
    registry_tools = load_tools()
    descriptors: Dict[str, ToolDescriptor] = {}
    for tool_name, source in registry_tools.items():
        allowed_args = _extract_allowed_arg_types(source.allowed_args)
        required = _extract_required_args(source.allowed_args)
        descriptors[tool_name] = ToolDescriptor(
            name=tool_name,
            kind=_normalize_kind(source.protocol),
            schema={"type": "object", "required": required},
            allowed_args=allowed_args,
            mock_result=dict(source.mock_result or {"status": "ok"}),
        )
    return descriptors


def _extract_allowed_arg_types(schema: Mapping[str, Any] | None) -> Dict[str, str]:
    if not isinstance(schema, Mapping):
        return {}
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return {}

    result: Dict[str, str] = {}
    for arg_name, arg_schema in properties.items():
        if not isinstance(arg_schema, Mapping):
            continue
        arg_type = arg_schema.get("type")
        if isinstance(arg_type, str) and arg_type:
            result[str(arg_name)] = arg_type
    return result


def _extract_required_args(schema: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(schema, Mapping):
        return []
    required = schema.get("required")
    if not isinstance(required, list):
        return []
    return [str(item) for item in required]


def _normalize_kind(protocol: str) -> str:
    if protocol in {"mcp", "internal", "cli"}:
        return protocol
    return "cli"


def _remote_multiplex_enabled(tool_settings: Mapping[str, Any] | None) -> bool:
    if not isinstance(tool_settings, Mapping):
        return False
    raw = tool_settings.get("mcp_remote_multiplex_enable")
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(raw, (int, float)):
        return raw != 0
    return False


__all__ = ["MCPToolProvider", "RemoteMCPProvider"]
