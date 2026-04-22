from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping

from app.components.settings.tools_loader import load_tools
from app.planner.tools import MCP_TOOL_DESCRIPTORS
from app.orchestrator.executor import MockPlanExecutor, StepContext, StepExecutionError
from app.planner.schema import ToolDescriptor


@dataclass
class MCPToolProvider:
    """Registry-backed tool provider that executes via existing executor paths."""

    def list_descriptors(self) -> Dict[str, ToolDescriptor]:
        descriptors = _load_registry_descriptors()
        supported = set(MCP_TOOL_DESCRIPTORS.keys())
        return {name: descriptor for name, descriptor in descriptors.items() if name in supported}

    def get_descriptor(self, tool_name: str) -> ToolDescriptor | None:
        return self.list_descriptors().get(tool_name)

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
        descriptor = self.get_descriptor(tool_name)
        if descriptor is None:
            raise StepExecutionError(f"unknown MCP tool '{tool_name}'", error_type="invalid_tool")

        active_executor = executor or MockPlanExecutor()
        call_args = dict(tool_args or {})
        active_executor._validate_tool_args(call_args, descriptor.allowed_args)  # noqa: SLF001 - parity with executor
        active_executor._validate_required_args(call_args, descriptor.schema.get("required", []))  # noqa: SLF001
        timeout_value = None
        settings = context.tool_settings or {}
        if "tool_timeout_seconds" in settings:
            try:
                timeout_value = float(settings["tool_timeout_seconds"])
            except Exception:
                timeout_value = None
        result_payload = active_executor._invoke_tool(  # noqa: SLF001 - preserve executor runtime path
            descriptor, call_args, context, timeout_value
        )
        return {"tool": descriptor.name, "result": result_payload}


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


__all__ = ["MCPToolProvider"]
