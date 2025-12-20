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
