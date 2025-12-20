from __future__ import annotations

import pytest

from app.components.settings.agents_loader import load_agents
from app.components.settings.graphs_loader import load_graph_registry, load_graphs

pytestmark = pytest.mark.not_pg


def test_graph_registry_loads() -> None:
    reg = load_graph_registry()
    assert reg.version >= 1
    ids = {g.id for g in reg.graphs}
    assert "ask.graph.v1" in ids
    assert "panel.graph.v5" in ids


def test_graphs_load_and_match_manifest() -> None:
    graphs = load_graphs()
    assert graphs["ask.graph.v1"].id == "ask.graph.v1"
    assert graphs["panel.graph.v5"].id == "panel.graph.v5"
    assert graphs["ask.graph.v1"].entrypoint
    assert graphs["panel.graph.v5"].entrypoint


def test_graph_agent_id_exists_in_agent_registry() -> None:
    agents = load_agents()
    agent_ids = set(agents.keys())

    graphs = load_graphs()
    for gid, g in graphs.items():
        assert g.agent_id in agent_ids, f"{gid} references unknown agent_id: {g.agent_id}"
