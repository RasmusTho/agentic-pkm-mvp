from __future__ import annotations

from pathlib import Path

import pytest

from app.components.settings.agents_loader import load_agent_registry, load_agents
from app.components.settings.tools_loader import load_tools

pytestmark = pytest.mark.not_pg


def test_agent_registry_loads() -> None:
    reg = load_agent_registry()
    assert reg.version >= 1
    ids = {a.id for a in reg.agents}
    assert "ask.v1" in ids
    assert "panel_agent.v5" in ids


def test_agents_load_and_match_manifest() -> None:
    agents = load_agents()
    assert agents["ask.v1"].id == "ask.v1"
    assert agents["panel_agent.v5"].id == "panel_agent.v5"
    assert agents["ask.v1"].kind == "langgraph"


def test_agent_allowed_tools_exist_in_tool_registry() -> None:
    tools = load_tools()
    tool_ids = set(tools.keys())

    agents = load_agents()
    for aid, agent in agents.items():
        for tid in agent.allowed_tools:
            assert tid in tool_ids, f"{aid} references unknown tool id: {tid}"


def test_agent_settings_refs_exist() -> None:
    agents = load_agents()
    for aid, agent in agents.items():
        for ref in agent.settings_refs:
            assert Path(ref).exists(), f"{aid} references missing settings ref: {ref}"
