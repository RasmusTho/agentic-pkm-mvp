from __future__ import annotations

from pathlib import Path

import pytest

from app.orchestrator.executor import MockPlanExecutor, StepContext, StepExecutionError
from app.orchestrator.mcp_tool_provider import MCPToolProvider
from app.planner.schema import PlanMetadata, PlanStep, ToolDescriptor

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
    assert "vault.read_note.v1" not in descriptors
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


def test_tool_provider_rejects_registry_only_tool_not_in_supported_allowlist() -> None:
    provider = MCPToolProvider()
    context = _context()

    with pytest.raises(StepExecutionError) as exc:
        provider.execute_tool_call(
            tool_name="vault.read_note.v1",
            tool_args={"path": "x.md"},
            context=context,
            step_id="s-unsupported",
            description="Unsupported tool",
        )

    assert exc.value.error_type == "invalid_tool"


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
        return {"tool": "mcp.search.objects", "result": {"status": "remote-ok", "route": "remote"}}


class _RemoteProviderError(_RemoteProviderOK):
    def execute_tool_call(self, **_: object) -> dict[str, object]:
        raise RuntimeError("remote unavailable")


class _RemoteProviderListError(_RemoteProviderError):
    def list_descriptors(self) -> dict[str, ToolDescriptor]:
        raise RuntimeError("remote descriptor lookup failed")


class _RemoteProviderMismatchedDescriptor(_RemoteProviderError):
    def list_descriptors(self) -> dict[str, ToolDescriptor]:
        return {
            "mcp.search.objects": ToolDescriptor(
                name="mcp.search.objects",
                kind="mcp",
                schema={"type": "object", "required": ["query", "tenant"]},
                allowed_args={"query": "string", "tenant": "string"},
                mock_result={"status": "remote-schema"},
            )
        }


def test_remote_multiplex_path_flagged() -> None:
    provider = MCPToolProvider(remote_provider=_RemoteProviderOK())
    executor = MockPlanExecutor()
    context = _context(
        {
            "mcp_remote_multiplex_enable": True,
            "mcp_remote_allowed_providers": ["remote_multiplex"],
        }
    )

    result = provider.execute_tool_call(
        tool_name="mcp.search.objects",
        tool_args={"query": "agentic"},
        context=context,
        step_id="s-remote",
        description="Remote path",
        executor=executor,
    )

    assert result["result"]["status"] == "remote-ok"
    assert result["result"]["route"] == "remote"


def test_remote_multiplex_fallback_on_provider_error() -> None:
    provider = MCPToolProvider(remote_provider=_RemoteProviderError())
    executor = MockPlanExecutor()
    context = _context(
        {
            "mcp_remote_multiplex_enable": True,
            "mcp_remote_allowed_providers": ["remote_multiplex"],
        }
    )

    result = provider.execute_tool_call(
        tool_name="mcp.search.objects",
        tool_args={"query": "agentic"},
        context=context,
        step_id="s-fallback",
        description="Fallback path",
        executor=executor,
    )

    assert result["tool"] == "mcp.search.objects"
    assert result["result"]["status"] == "ok"


def test_remote_descriptor_list_error_falls_back_to_local_registry() -> None:
    provider = MCPToolProvider(remote_provider=_RemoteProviderListError())
    context = _context(
        {
            "mcp_remote_multiplex_enable": True,
            "mcp_remote_allowed_providers": ["remote_multiplex"],
        }
    )

    result = provider.execute_tool_call(
        tool_name="mcp.search.objects",
        tool_args={"query": "agentic"},
        context=context,
        step_id="s-fallback-descriptor",
        description="Fallback path when descriptor lookup fails",
    )

    assert result["tool"] == "mcp.search.objects"
    assert result["result"]["status"] == "ok"


def test_remote_error_fallback_re_resolves_local_descriptor() -> None:
    provider = MCPToolProvider(remote_provider=_RemoteProviderMismatchedDescriptor())
    context = _context(
        {
            "mcp_remote_multiplex_enable": True,
            "mcp_remote_allowed_providers": ["remote_multiplex"],
        }
    )

    result = provider.execute_tool_call(
        tool_name="mcp.search.objects",
        tool_args={"query": "agentic"},
        context=context,
        step_id="s-fallback-local-descriptor",
        description="Fallback should use local descriptor semantics",
    )

    assert result["tool"] == "mcp.search.objects"
    assert result["result"]["status"] == "ok"


def test_remote_error_without_local_descriptor_raises_tool_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.orchestrator.mcp_tool_provider._load_registry_descriptors", lambda: {})
    provider = MCPToolProvider(remote_provider=_RemoteProviderMismatchedDescriptor())
    context = _context(
        {
            "mcp_remote_multiplex_enable": True,
            "mcp_remote_allowed_providers": ["remote_multiplex"],
        }
    )

    with pytest.raises(StepExecutionError) as exc:
        provider.execute_tool_call(
            tool_name="mcp.search.objects",
            tool_args={"query": "agentic", "tenant": "t1"},
            context=context,
            step_id="s-no-local-fallback",
            description="No local descriptor available",
        )

    assert exc.value.error_type == "tool_unavailable"
