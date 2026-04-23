from __future__ import annotations

import pytest

from app.orchestrator.mcp_tool_provider import MCPToolProvider
from app.planner.schema import ToolDescriptor

pytestmark = pytest.mark.not_pg


class _RemoteProviderMixed:
    def list_descriptors(self) -> dict[str, ToolDescriptor]:
        return {
            "mcp.search.objects": ToolDescriptor(
                name="mcp.search.objects",
                kind="mcp",
                schema={"type": "object", "required": ["query"]},
                allowed_args={"query": "string"},
                mock_result={"status": "remote-ok"},
            ),
            "mcp.unknown.tool": ToolDescriptor(
                name="mcp.unknown.tool",
                kind="mcp",
                schema={"type": "object", "required": []},
                allowed_args={},
                mock_result={"status": "unknown"},
            ),
        }

    def execute_tool_call(self, **_: object) -> dict[str, object]:
        return {"result": {"status": "remote-ok"}}


def test_discovery_enumerates_providers_when_enabled() -> None:
    provider = MCPToolProvider(remote_provider=_RemoteProviderMixed())

    diagnostics = provider.get_discovery_diagnostics(
        {
            "mcp_remote_multiplex_enable": True,
            "mcp_remote_allowed_providers": ["remote_multiplex"],
        }
    )

    assert diagnostics["enabled"] is True
    assert diagnostics["reason_code"] == "ok"
    discovered_tools = {entry["tool"] for entry in diagnostics["discovered"]}
    assert "mcp.search.objects" in discovered_tools
    assert "mcp.unknown.tool" in discovered_tools


def test_discovered_provider_requires_policy_admission() -> None:
    provider = MCPToolProvider(remote_provider=_RemoteProviderMixed())

    diagnostics = provider.get_discovery_diagnostics({"mcp_remote_multiplex_enable": True})
    assert diagnostics["reason_code"] == "policy_admission_required"
    rejected = {entry["tool"]: entry["reason_code"] for entry in diagnostics["rejected"]}
    assert rejected["mcp.search.objects"] == "policy_admission_required"

    descriptors = provider.list_descriptors({"mcp_remote_multiplex_enable": True})
    assert "mcp.search.objects" in descriptors
    assert descriptors["mcp.search.objects"].mock_result.get("status") == "ok"
