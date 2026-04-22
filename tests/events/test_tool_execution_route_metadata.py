from __future__ import annotations

import pytest

from app.events.types import MCP_TOOL_CALL_FINISHED, MCP_TOOL_CALL_STARTED
from app.orchestrator.executor import StepContext
from app.orchestrator.mcp_tool_provider import MCPToolProvider
from app.planner.schema import PlanMetadata, ToolDescriptor

pytestmark = pytest.mark.not_pg


def _context(tool_settings: dict[str, object] | None = None) -> StepContext:
    return StepContext(
        plan_id="plan-route-metadata",
        object_id="obj-route-metadata",
        trace_id="trace-route-metadata",
        metadata=PlanMetadata(goal="test", source_object_uuid="obj-route-metadata", created_by="tester"),
        results={},
        tool_settings=tool_settings or {},
        agent_id="ask.v1",
    )


class _RemoteProviderOK:
    def list_descriptors(self) -> dict[str, ToolDescriptor]:
        return {
            "mcp.search.objects": ToolDescriptor(
                name="mcp.search.objects",
                kind="mcp",
                schema={"type": "object", "required": ["query"]},
                allowed_args={"query": "string"},
                mock_result={"status": "ok"},
            )
        }

    def execute_tool_call(self, **_: object) -> dict[str, object]:
        return {"tool": "mcp.search.objects", "result": {"status": "remote-ok"}}


def test_tool_execution_records_provider_route(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[str, dict[str, object]]] = []

    def _fake_audit_log(*, action: str, details: dict, **kwargs: object) -> None:
        captured.append((action, details))

    monkeypatch.setattr("app.orchestrator.events.audit_log", _fake_audit_log)

    provider = MCPToolProvider(remote_provider=_RemoteProviderOK())
    provider.execute_tool_call(
        tool_name="mcp.search.objects",
        tool_args={"query": "agentic"},
        context=_context({"mcp_remote_multiplex_enable": True}),
        step_id="s-route",
        description="Route metadata",
    )

    started = [details for action, details in captured if action == MCP_TOOL_CALL_STARTED]
    finished = [details for action, details in captured if action == MCP_TOOL_CALL_FINISHED]
    assert started
    assert finished
    assert started[-1]["provider_route"] == "remote_multiplex"
    assert finished[-1]["provider_route"] == "remote_multiplex"
