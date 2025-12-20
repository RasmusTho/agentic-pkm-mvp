from __future__ import annotations

import pytest

from app.components.settings.events_loader import load_event_registry, load_events
from app.components.settings.graphs_loader import load_graphs

pytestmark = pytest.mark.not_pg


def test_event_registry_loads() -> None:
    reg = load_event_registry()
    assert reg.version >= 1
    ids = {e.id for e in reg.events}
    assert "ask.requested" in ids
    assert "panel.intent.created" in ids


def test_events_load_and_match_manifest() -> None:
    events = load_events()
    assert events["ask.requested"].id == "ask.requested"
    assert events["ask.requested"].version >= 1


def test_graph_events_exist_in_event_registry() -> None:
    events = load_events()
    event_ids = set(events.keys())

    graphs = load_graphs()
    for gid, g in graphs.items():
        for ev in g.input_events + g.output_events:
            assert ev in event_ids, f"{gid} references unknown event id: {ev}"
