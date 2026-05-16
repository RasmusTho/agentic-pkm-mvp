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


def test_prior_pass_proposal_marker_still_gates_on_rerun(monkeypatch) -> None:
    """Codex P1 (r3252622154): a proposal that survived writeback as `[ ] <!--ai:proposed=...-->`
    must not be auto-executed on a subsequent pass even though `proposed_action_ids` is empty.

    Simulates: pass 1 wrote the marker; pass 2 parses the panel, the LLM "selects" the still-
    unchecked action; the persistent `proposal_pending` marker must keep the gate engaged.
    """
    from app.events.panel import PanelIntentAction

    catalog = _governed_catalog()
    descriptor = catalog.get("promote.evergreen")
    mapping = descriptor.to_mapping()
    # Action carries proposal_pending=True (parsed from a prior-pass marker), checked=False,
    # proposed_action_ids is empty (this pass is not the one that injected the proposal).
    action = PanelIntentAction(
        id="promote.evergreen",
        label="Make this note evergreen",
        checked=False,
        mapping=mapping,
        proposal_pending=True,
    )
    note = NoteRef(uuid=TEST_NOTE_UUID, path=TEST_NOTE_PATH, origin="vault")
    panel = PanelInfo(panel_id="p1", instruction="continue", raw_block=None)
    intent = PanelIntentEvent(
        payload=PanelIntentPayload(note=note, panel=panel, actions=[action]),
        trace_id="trace-#979-rerun",
    )
    state = PanelAgentState(
        trace_id=intent.trace_id,
        note=note,
        panel=panel,
        actions=[action],
        intent_event=intent,
        action_catalog=catalog,
        proposed_action_ids=[],  # NOT in this-pass proposed_ids; only the marker should gate.
    )
    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade",
        lambda: _StubReasoningFacade({"actions": [{"id": "promote.evergreen"}]}),
    )

    result = run_panel_graph(state, decider_mode="llm")

    statuses = {r.id: r.status for r in result.action_results}
    assert statuses.get("promote.evergreen") == "skipped"
    assert "promote.evergreen" not in (result.executed_action_ids or [])
    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    assert "promote.intent.created" not in event_names
    proposal_logged = [
        evt
        for evt in result.emitted_events
        if getattr(evt, "event", None) == "panel.action.logged"
        and getattr(evt, "payload", {}).get("reason") == "proposal_offered"
    ]
    assert proposal_logged, "expected proposal_offered when prior-pass marker gates a rerun"


def test_human_confirmed_proposal_executes_on_rerun(monkeypatch) -> None:
    """Counterpart to the rerun-gate test: once the human toggles `[ ]` -> `[x]`, the action
    is no longer gated — `checked=True` from the panel parse means the human confirmed it,
    so the governance-bearing capability proceeds even if the proposal_pending marker is
    still on the line.
    """
    from app.events.panel import PanelIntentAction

    catalog = _governed_catalog()
    descriptor = catalog.get("promote.evergreen")
    mapping = descriptor.to_mapping()
    action = PanelIntentAction(
        id="promote.evergreen",
        label="Make this note evergreen",
        checked=True,  # human flipped the checkbox
        mapping=mapping,
        proposal_pending=True,  # marker still present from prior-pass writeback
    )
    note = NoteRef(uuid=TEST_NOTE_UUID, path=TEST_NOTE_PATH, origin="vault")
    panel = PanelInfo(panel_id="p1", instruction="continue", raw_block=None)
    intent = PanelIntentEvent(
        payload=PanelIntentPayload(note=note, panel=panel, actions=[action]),
        trace_id="trace-#979-human-confirm",
    )
    state = PanelAgentState(
        trace_id=intent.trace_id,
        note=note,
        panel=panel,
        actions=[action],
        intent_event=intent,
        action_catalog=catalog,
        proposed_action_ids=[],
    )

    # Rule-mode: selected_ids derived from action.checked, not freeform LLM.
    result = run_panel_graph(state, decider_mode="rule")

    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    assert "promote.intent.created" in event_names, (
        "human-confirmed proposal must execute even with proposal_pending marker present"
    )
