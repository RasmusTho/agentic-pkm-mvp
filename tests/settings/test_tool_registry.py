from __future__ import annotations

import pytest

from app.components.settings.tools_loader import load_tool_registry, load_tools

pytestmark = pytest.mark.not_pg


def test_tool_registry_loads() -> None:
    reg = load_tool_registry()
    assert reg.version >= 1
    assert reg.tools
    ids = {t.id for t in reg.tools}
    assert "vault.read_note.v1" in ids
    assert "vault.write_note.v1" in ids


def test_tools_load_and_match_manifest() -> None:
    tools = load_tools()
    assert tools["vault.read_note.v1"].id == "vault.read_note.v1"
    assert tools["vault.write_note.v1"].id == "vault.write_note.v1"
    assert tools["vault.read_note.v1"].protocol == "mcp"


def test_tool_descriptors_have_required_fields() -> None:
    """Validate that all active tool descriptors have the minimum required fields documented in TOOL_POLICY_AND_MCP_ADAPTER_CONTRACT."""
    tools = load_tools()
    required_fields = {"id", "status", "protocol", "server", "description"}
    for tool_id, tool in tools.items():
        assert tool.id == tool_id, f"Tool id mismatch for {tool_id}"
        assert tool.status, f"Tool {tool_id} missing status field"
        assert tool.protocol, f"Tool {tool_id} missing protocol field"
        assert tool.server, f"Tool {tool_id} missing server field"
        assert tool.description, f"Tool {tool_id} missing description field"
        # Verify the tool has allowed_args and/or mock_result defined (or both)
        # The contract allows both to be optional but encourages them
        assert isinstance(tool.allowed_args, dict), f"Tool {tool_id} allowed_args not a dict"
