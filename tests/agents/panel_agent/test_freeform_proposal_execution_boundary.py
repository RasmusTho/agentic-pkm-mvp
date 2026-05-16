"""Issue #979: proposal-vs-execution boundary for freeform LLM proposals.

These tests exercise the real PanelAgent LangGraph (no graph mocking) to
confirm that freeform LLM-proposed actions for governance-bearing
capabilities (capability_class: governed_execution / authority_class:
governed_effect per docs/CAPABILITY_CONTRACT_MODEL.md) do NOT execute in
the same runtime pass. They must be written back as unchecked proposals and
surface a `proposal_offered` signal instead.
"""

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

TEST_NOTE_UUID = "panel-boundary-00000000-0000-4000-8000-000000000001"
TEST_NOTE_PATH = "vault/Boundary.md"


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


def _freeform_state(catalog: PanelActionCatalog) -> PanelAgentState:
    note = NoteRef(uuid=TEST_NOTE_UUID, path=TEST_NOTE_PATH, origin="vault")
    panel = PanelInfo(panel_id="p1", instruction="Make this note evergreen.", raw_block=None)
    payload = PanelIntentPayload(note=note, panel=panel, actions=[])
    intent = PanelIntentEvent(payload=payload, trace_id="trace-#979")
    return PanelAgentState(
        trace_id=intent.trace_id,
        note=note,
        panel=panel,
        actions=[],
        intent_event=intent,
        action_catalog=catalog,
    )


def _governed_catalog() -> PanelActionCatalog:
    return PanelActionCatalog.from_descriptors(
        [
            PanelActionDescriptor(
                id="promote.evergreen",
                intent_type="promotion",
                trust_verb="APPLY",
                downstream_event="review.promote.evergreen",
                labels=["Make this note evergreen"],
                description="Promote note to evergreen",
                llm_hint="Use for promotion to evergreen.",
                params={"maturity": "evergreen"},
            )
        ]
    )


def test_freeform_generated_proposals_do_not_execute_same_run(monkeypatch) -> None:
    """AC: Generated freeform proposals remain unchecked and non-executable during the same cycle."""
    state = _freeform_state(_governed_catalog())
    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade",
        lambda: _StubReasoningFacade({"actions": [{"id": "promote.evergreen"}]}),
    )

    result = run_panel_graph(state, decider_mode="llm")

    statuses = {r.id: r.status for r in result.action_results}
    assert statuses["promote.evergreen"] == "skipped"
    # Action is still selected by the LLM, but written back unchecked.
    assert "promote.evergreen" in result.selected_action_ids
    assert "promote.evergreen" in result.proposed_action_ids
    proposed = next(a for a in result.actions if a.id == "promote.evergreen")
    assert proposed.checked is False
    # Crucially: it is NOT recorded as executed, so a future human check still runs it.
    assert "promote.evergreen" not in (result.executed_action_ids or [])


def test_freeform_proposals_do_not_emit_governance_events(monkeypatch) -> None:
    """AC: No downstream governance-bearing event is emitted from proposal generation alone."""
    state = _freeform_state(_governed_catalog())
    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade",
        lambda: _StubReasoningFacade({"actions": [{"id": "promote.evergreen"}]}),
    )

    result = run_panel_graph(state, decider_mode="llm")

    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    # Governance-bearing effect must NOT fire from a freeform proposal.
    assert "promote.intent.created" not in event_names
    assert "panel.action.triggered" not in event_names
    # A proposal_offered signal IS emitted so consumers see the proposal surfaced.
    assert "panel.action.logged" in event_names
    proposal_logged = [
        evt
        for evt in result.emitted_events
        if getattr(evt, "event", None) == "panel.action.logged"
        and getattr(evt, "payload", {}).get("reason") == "proposal_offered"
    ]
    assert proposal_logged, "expected a proposal_offered panel.action.logged event"
