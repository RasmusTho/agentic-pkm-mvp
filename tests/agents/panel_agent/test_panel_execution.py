"""Issue #979: explicit checked-checkbox actions continue to execute.

Regression coverage to confirm the proposal-vs-execution boundary did not
break the existing checked-checkbox execution path through the real
PanelAgent LangGraph.
"""

from __future__ import annotations

import pytest

from app.agents.panel_agent.graph import run_panel_graph
from app.agents.panel_agent.state import PanelAgentState
from app.components.concurrency import IdempotencyGuard
from app.events.panel import (
    NoteRef,
    PanelActionMapping,
    PanelInfo,
    PanelIntentAction,
    PanelIntentEvent,
    PanelIntentPayload,
)


@pytest.fixture(autouse=True)
def _avoid_wiring_io(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.agents.panel_agent.graph.get_default_action_wiring", lambda: {}
    )


@pytest.fixture(autouse=True)
def _reset_idempotency_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.agents.panel_agent.graph._IDEMPOTENCY_GUARD",
        IdempotencyGuard(ttl_seconds=86400.0),
    )


def test_checked_checkbox_actions_execute() -> None:
    """AC: Explicit checked checkbox actions execute through the existing runtime path."""
    mapping = PanelActionMapping(
        id="promote.evergreen",
        intent_type="promotion",
        trust_verb="APPLY",
        downstream_event="review.promote.evergreen",
        params={"maturity": "evergreen"},
    )
    action = PanelIntentAction(
        id=mapping.id,
        label="Make this note evergreen",
        checked=True,  # human-checked: explicit consent
        mapping=mapping,
    )
    note = NoteRef(
        uuid="panel-checked-00000000-0000-4000-8000-000000000001",
        path="vault/Checked.md",
        origin="vault",
    )
    panel = PanelInfo(panel_id="p1", instruction="Promote.", raw_block=None)
    payload = PanelIntentPayload(note=note, panel=panel, actions=[action])
    intent = PanelIntentEvent(payload=payload, trace_id="trace-#979-checked")
    state = PanelAgentState(
        trace_id=intent.trace_id,
        note=note,
        panel=panel,
        actions=[action],
        intent_event=intent,
    )

    # Rule decider: no LLM, no proposal injection - the human-checked path.
    result = run_panel_graph(state, decider_mode="rule")

    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    assert "promote.intent.created" in event_names
    assert "panel.action.triggered" in event_names
    statuses = {r.id: r.status for r in result.action_results}
    assert statuses["promote.evergreen"] == "triggered"
    # The human-checked action is NOT in proposed_action_ids: it was not an LLM proposal.
    assert "promote.evergreen" not in (result.proposed_action_ids or [])
