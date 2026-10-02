from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Protocol

from app.components.settings.tools_loader import load_tools
from app.orchestrator.executor import MockPlanExecutor, StepContext, StepExecutionError
from app.planner.tools import MCP_TOOL_DESCRIPTORS
from app.planner.schema import ToolDescriptor


class RemoteMCPProvider(Protocol):
    def list_descriptors(self) -> Mapping[str, ToolDescriptor]:
        ...


@dataclass
class MCPToolProvider:
    """Descriptor discovery for the dormant MCP execution adapter.

    Descriptor listing remains available for planning. Execution is intentionally
    fail-closed until this provider is connected to an admission-derived runtime
    path; plan fields and direct calls do not establish that authority.
    """

    remote_provider: RemoteMCPProvider | None = None

    def list_descriptors(
        self, tool_settings: Mapping[str, Any] | None = None
    ) -> Dict[str, ToolDescriptor]:
        descriptors = self._list_local_descriptors()
        if _remote_multiplex_enabled(tool_settings) and self.remote_provider is not None:
            try:
                remote = dict(self.remote_provider.list_descriptors())
                descriptors.update(remote)
            except Exception:
                # Remote descriptor discovery is best-effort; keep the local registry available.
                pass
        return self._filter_supported(descriptors)

    def get_descriptor(
        self,
        tool_name: str,
        tool_settings: Mapping[str, Any] | None = None,
    ) -> ToolDescriptor | None:
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
        """Refuse direct execution before local or remote tool code can run."""
        raise StepExecutionError(
            "MCP tool execution requires an admission-derived orchestrator path",
            error_type="admission_required",
        )

    def _list_local_descriptors(self) -> Dict[str, ToolDescriptor]:
        return _load_registry_descriptors()

    def _filter_supported(self, descriptors: Mapping[str, Any]) -> Dict[str, ToolDescriptor]:
        supported = set(MCP_TOOL_DESCRIPTORS.keys())
        return {
            name: descriptor
            for name, descriptor in descriptors.items()
            if name in supported and isinstance(descriptor, ToolDescriptor)
        }


def _load_registry_descriptors() -> Dict[str, ToolDescriptor]:
    registry_tools = load_tools()
    descriptors: Dict[str, ToolDescriptor] = {}
    for tool_name, source in registry_tools.items():
        canonical = MCP_TOOL_DESCRIPTORS.get(tool_name)
        allowed_args = _extract_allowed_arg_types(source.allowed_args)
        required = _extract_required_args(source.allowed_args)
        mock_result = dict(source.mock_result or {"status": "ok"})
        # Keep descriptor parity with MockPlanExecutor/get_tool_descriptor.
        if canonical is not None and isinstance(canonical.mock_result, Mapping):
            mock_result = dict(canonical.mock_result)
        descriptors[tool_name] = ToolDescriptor(
            name=tool_name,
            kind=_normalize_kind(source.protocol),
            schema={"type": "object", "required": required},
            allowed_args=allowed_args,
            mock_result=mock_result,
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
            continue
        if isinstance(arg_type, list):
            union_types = [str(item) for item in arg_type if isinstance(item, str) and item]
            if union_types:
                result[str(arg_name)] = "|".join(sorted(dict.fromkeys(union_types)))
            continue
        one_of = arg_schema.get("oneOf")
        if isinstance(one_of, list):
            union_types = [
                str(option_type)
                for option in one_of
                if isinstance(option, Mapping)
                for option_type in [option.get("type")]
                if isinstance(option_type, str) and option_type
            ]
            if union_types:
                result[str(arg_name)] = "|".join(sorted(dict.fromkeys(union_types)))
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
