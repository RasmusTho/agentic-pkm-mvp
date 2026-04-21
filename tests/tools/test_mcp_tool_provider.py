from __future__ import annotations

from pathlib import Path

import pytest

from app.orchestrator.executor import MockPlanExecutor, StepContext, StepExecutionError
from app.orchestrator.mcp_tool_provider import MCPToolProvider
from app.planner.schema import PlanMetadata, PlanStep

pytestmark = pytest.mark.not_pg


def _context(tool_settings: dict[str, object] | None = None) -> StepContext:
    return StepContext(
        plan_id="plan-provider",
        object_id="obj-provider",
        trace_id="trace-provider",
        metadata=PlanMetadata(goal="test", source_object_uuid="obj-provider", created_by="tester"),
        results={},
        tool_settings=tool_settings or {},
        agent_id="ask.v1",
    )


def test_tool_provider_lists_registry_descriptors() -> None:
    provider = MCPToolProvider()

    descriptors = provider.list_descriptors()

    assert "mcp.search.objects" in descriptors
    assert "mcp.vault.append_note" in descriptors
    assert descriptors["mcp.search.objects"].kind == "mcp"
    assert descriptors["mcp.search.objects"].allowed_args["query"] == "string"


def test_tool_provider_mock_execution_matches_descriptor_executor() -> None:
    provider = MCPToolProvider()
    executor = MockPlanExecutor()
    step = PlanStep(
        id="s1",
        kind="tool_call",
        description="Search",
        tool="mcp.search.objects",
        tool_args={"query": "agentic"},
    )
    context = _context()

    expected = executor.execute_step(step, context)
    actual = provider.execute_tool_call(
        tool_name="mcp.search.objects",
        tool_args={"query": "agentic"},
        context=context,
        step_id="s1",
        description="Search",
        executor=executor,
    )
    assert actual == expected

    with pytest.raises(StepExecutionError) as provider_exc:
        provider.execute_tool_call(
            tool_name="mcp.search.objects",
            tool_args={"query": 123},
            context=context,
            step_id="s2",
            description="Bad search",
            executor=executor,
        )
    with pytest.raises(StepExecutionError) as direct_exc:
        executor.execute_step(
            PlanStep(
                id="s2",
                kind="tool_call",
                description="Bad search",
                tool="mcp.search.objects",
                tool_args={"query": 123},
            ),
            context,
        )

    assert provider_exc.value.error_type == direct_exc.value.error_type == "invalid_tool_args"


def test_tool_provider_vault_append_respects_existing_gates(tmp_path: Path) -> None:
    provider = MCPToolProvider()
    executor = MockPlanExecutor()

    denied_result = provider.execute_tool_call(
        tool_name="mcp.vault.append_note",
        tool_args={"title": "A", "body": "B"},
        context=_context(
            {
                "mcp_vault_enable": True,
                "allowed_mcp_tools": ["mcp.search.objects"],
                "vault_root": tmp_path,
            }
        ),
        step_id="s3",
        description="Denied append",
        executor=executor,
    )
    assert denied_result["result"]["note_path"] == "vault/_mcp/mock-note.md"
    assert not any(tmp_path.rglob("*.md"))

    allowed_result = provider.execute_tool_call(
        tool_name="mcp.vault.append_note",
        tool_args={"title": "C", "body": "D"},
        context=_context(
            {
                "mcp_vault_enable": True,
                "allowed_mcp_tools": ["mcp.vault.append_note"],
                "vault_root": tmp_path,
            }
        ),
        step_id="s4",
        description="Allowed append",
        executor=executor,
    )
    assert allowed_result["result"]["note_path"] != "vault/_mcp/mock-note.md"
    assert any(tmp_path.rglob("*.md"))
