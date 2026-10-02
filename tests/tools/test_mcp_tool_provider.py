from __future__ import annotations

import pytest

from app.orchestrator.executor import StepContext, StepExecutionError
from app.orchestrator.mcp_tool_provider import MCPToolProvider
from app.planner.schema import PlanMetadata, ToolDescriptor

pytestmark = pytest.mark.not_pg


def _context(tool_settings: dict[str, object] | None = None) -> StepContext:
    return StepContext(
        plan_id="plan-provider",
        object_id="obj-provider",
        trace_id="trace-provider",
        metadata=PlanMetadata(
            goal="test", source_object_uuid="obj-provider", created_by="tester"
        ),
        results={},
        tool_settings=tool_settings or {},
        agent_id="ask.v1",
    )


class _RemoteDescriptors:
    def __init__(self) -> None:
        self.executions = 0

    def list_descriptors(self) -> dict[str, ToolDescriptor]:
        return {
            "mcp.search.objects": ToolDescriptor(
                name="mcp.search.objects",
                kind="mcp",
                schema={"type": "object", "required": ["query"]},
                allowed_args={"query": "string"},
                mock_result={"status": "remote-descriptor"},
            ),
            "unknown.remote.tool": ToolDescriptor(
                name="unknown.remote.tool",
                kind="mcp",
            ),
        }

    def execute_tool_call(self, **_: object) -> dict[str, object]:
        self.executions += 1
        return {"status": "unexpected"}


def test_tool_provider_lists_registry_descriptors() -> None:
    provider = MCPToolProvider()

    descriptors = provider.list_descriptors()

    assert "mcp.search.objects" in descriptors
    assert "mcp.vault.append_note" in descriptors
    assert "mcp.builderops.create_worklog" in descriptors
    assert "mcp.builderops.list_records" in descriptors
    assert "vault.read_note.v1" not in descriptors
    assert descriptors["mcp.search.objects"].kind == "mcp"
    assert descriptors["mcp.search.objects"].allowed_args["query"] == "string"


def test_remote_provider_is_used_for_discovery_only() -> None:
    remote = _RemoteDescriptors()
    provider = MCPToolProvider(remote_provider=remote)

    descriptors = provider.list_descriptors({"mcp_remote_multiplex_enable": True})

    assert descriptors["mcp.search.objects"].mock_result == {
        "status": "remote-descriptor"
    }
    assert "unknown.remote.tool" not in descriptors
    assert remote.executions == 0


def test_remote_descriptor_failure_preserves_local_discovery() -> None:
    class _RemoteFailure:
        def list_descriptors(self) -> dict[str, ToolDescriptor]:
            raise RuntimeError("remote discovery unavailable")

        def execute_tool_call(self, **_: object) -> dict[str, object]:
            raise AssertionError("descriptor discovery must not execute a tool")

    descriptors = MCPToolProvider(remote_provider=_RemoteFailure()).list_descriptors(
        {"mcp_remote_multiplex_enable": True}
    )

    assert "mcp.search.objects" in descriptors
    assert "mcp.vault.append_note" in descriptors


def test_direct_provider_execution_refuses_before_effects() -> None:
    remote = _RemoteDescriptors()
    local_calls: list[str] = []

    class _Executor:
        def _invoke_tool(self, *args: object, **kwargs: object) -> dict[str, object]:
            local_calls.append("invoke")
            return {"status": "unexpected"}

    with pytest.raises(StepExecutionError) as exc_info:
        MCPToolProvider(remote_provider=remote).execute_tool_call(
            tool_name="mcp.search.objects",
            tool_args={"query": "agentic"},
            context=_context({"mcp_remote_multiplex_enable": True}),
            step_id="direct",
            description="Direct call",
            executor=_Executor(),  # type: ignore[arg-type]
        )

    assert exc_info.value.error_type == "admission_required"
    assert local_calls == []
    assert remote.executions == 0
