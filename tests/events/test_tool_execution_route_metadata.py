from __future__ import annotations

import pytest

from app.events.types import MCP_TOOL_CALL_FINISHED, MCP_TOOL_CALL_STARTED
from app.orchestrator.executor import StepContext, StepExecutionError
from app.orchestrator.mcp_tool_provider import MCPToolProvider
from app.planner.schema import PlanMetadata

pytestmark = pytest.mark.not_pg


def _context() -> StepContext:
    return StepContext(
        plan_id="plan-route-metadata",
        object_id="obj-route-metadata",
        trace_id="trace-route-metadata",
        metadata=PlanMetadata(
            goal="test",
            source_object_uuid="obj-route-metadata",
            created_by="tester",
        ),
        results={},
        tool_settings={"mcp_remote_multiplex_enable": True},
        agent_id="ask.v1",
    )


def test_direct_provider_execution_emits_no_route_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[str, dict[str, object]]] = []

    def _fake_audit_log(*, action: str, details: dict, **kwargs: object) -> None:
        captured.append((action, details))

    monkeypatch.setattr("app.orchestrator.events.audit_log", _fake_audit_log)
    provider = MCPToolProvider()

    with pytest.raises(StepExecutionError) as exc_info:
        provider.execute_tool_call(
            tool_name="mcp.search.objects",
            tool_args={"query": "agentic"},
            context=_context(),
            step_id="direct",
            description="Direct provider call",
        )

    assert exc_info.value.error_type == "admission_required"
    actions = [action for action, _ in captured]
    assert MCP_TOOL_CALL_STARTED not in actions
    assert MCP_TOOL_CALL_FINISHED not in actions
