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
            "mcp.unsupported.remote": ToolDescriptor(
                name="mcp.unsupported.remote",
                kind="mcp",
                schema={"type": "object", "required": []},
                allowed_args={},
                mock_result={"status": "remote-unsupported"},
            ),
        }

    def execute_tool_call(self, **_: object) -> dict[str, object]:
        return {"result": {"status": "remote-ok"}}


def test_discovery_diagnostics_reason_codes() -> None:
    provider = MCPToolProvider(remote_provider=_RemoteProviderMixed())

    disabled = provider.get_discovery_diagnostics({})
    assert disabled["reason_code"] == "remote_disabled"

    blocked = provider.get_discovery_diagnostics({"mcp_remote_multiplex_enable": True})
    assert blocked["reason_code"] == "policy_admission_required"
    blocked_reasons = {entry["tool"]: entry["reason_code"] for entry in blocked["rejected"]}
    assert blocked_reasons["mcp.search.objects"] == "policy_admission_required"

    admitted = provider.get_discovery_diagnostics(
        {
            "mcp_remote_multiplex_enable": True,
            "mcp_remote_allowed_providers": ["remote_multiplex"],
        }
    )
    assert admitted["reason_code"] == "ok"
    admitted_tools = {entry["tool"] for entry in admitted["admitted"]}
    assert "mcp.search.objects" in admitted_tools
    rejected_reasons = {entry["tool"]: entry["reason_code"] for entry in admitted["rejected"]}
    assert rejected_reasons["mcp.unsupported.remote"] == "unsupported_tool"
