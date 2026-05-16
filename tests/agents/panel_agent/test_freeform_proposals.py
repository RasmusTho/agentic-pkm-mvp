"""Issue #979: generated proposals are written back as unchecked suggestions."""

from __future__ import annotations

import pytest

from app.agents.panel_agent.graph import run_panel_graph
from app.agents.panel_agent.state import PanelAgentState
from app.components.concurrency import IdempotencyGuard
from app.components.settings.panel_actions_loader import (
    PanelActionCatalog,
    PanelActionDescriptor,
)
from app.events.panel import (
    NoteRef,
    PanelInfo,
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


class _StubReasoningFacade:
    def __init__(self, response: object) -> None:
        self._response = response

    def structured(self, messages, schema, *, task_kind: str, trace_id: str | None = None):
        return self._response


def test_generated_proposals_written_as_unchecked_actions(monkeypatch) -> None:
    """AC: Generated proposals are written back as unchecked suggestions.

    The PanelIntentAction injected by `_inject_catalog_proposals` must
    remain `checked=False` in the final state, so the writeback layer
    emits it as an unchecked checkbox into the vault note.
    """
    catalog = PanelActionCatalog.from_descriptors(
        [
            PanelActionDescriptor(
                id="promote.evergreen",
                intent_type="promotion",
                trust_verb="APPLY",
                downstream_event="review.promote.evergreen",
                labels=["Make this note evergreen"],
                description="Promote to evergreen",
                llm_hint="Use for promotion.",
                params={"maturity": "evergreen"},
            )
        ]
    )
    note = NoteRef(
        uuid="panel-unchecked-00000000-0000-4000-8000-000000000001",
        path="vault/Unchecked.md",
        origin="vault",
    )
    panel = PanelInfo(panel_id="p1", instruction="Make this note evergreen.", raw_block=None)
    payload = PanelIntentPayload(note=note, panel=panel, actions=[])
    intent = PanelIntentEvent(payload=payload, trace_id="trace-#979-unchecked")
    state = PanelAgentState(
        trace_id=intent.trace_id,
        note=note,
        panel=panel,
        actions=[],
        intent_event=intent,
        action_catalog=catalog,
    )

    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade",
        lambda: _StubReasoningFacade({"actions": [{"id": "promote.evergreen"}]}),
    )

    result = run_panel_graph(state, decider_mode="llm")

    # The proposal lives in state.actions as an unchecked PanelIntentAction.
    proposed_actions = [a for a in result.actions if a.id == "promote.evergreen"]
    assert proposed_actions, "expected proposal injected into state.actions"
    assert proposed_actions[0].checked is False
    # And the action_result reports the proposal_offered reason rather than executed.
    proposal_results = [r for r in result.action_results if r.id == "promote.evergreen"]
    assert proposal_results and proposal_results[0].status == "skipped"
    assert proposal_results[0].details.get("reason") == "proposal_offered"
    # The proposal-result reflects the unchecked state, not a forced override.
    assert proposal_results[0].checked is False
