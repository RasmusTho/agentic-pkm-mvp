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


def _proposal_only_catalog() -> PanelActionCatalog:
    """Catalog combining a governance-bearing entry and a proposal-only entry (#982)."""
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
                capability_class="governed_execution",
                authority_class="governed_effect",
                requires_human_gate=True,
                params={"maturity": "evergreen"},
            ),
            PanelActionDescriptor(
                id="proposal.next_actions",
                intent_type="proposal",
                downstream_event="panel.proposal.next_actions",
                labels=["Suggest next actions"],
                description="Propose bounded next-step suggestions.",
                llm_hint="Use for next-step suggestions.",
                capability_class="proposal",
                authority_class="proposal",
                requires_human_gate=False,
            ),
        ]
    )


def test_proposal_only_capabilities_do_not_execute(monkeypatch) -> None:
    """#982 AC: Generated proposal-only capabilities remain non-executable
    unless explicitly checked through an approved runtime path.

    The LLM may freeform-propose a proposal-only capability, but the catalog
    injection still writes it back as an unchecked checkbox. Without an
    explicit human check (or LLM selection arriving with the action already
    checked), the proposal-only action must NOT emit its downstream
    observational event in the same pass.

    This protects the proposal-vs-execution contract end-to-end: the human
    remains the one to confirm even bounded proposal-only moves.
    """
    catalog = _proposal_only_catalog()
    # Build an unchecked proposal-only action that the parser would have seen
    # on a panel where the human did NOT toggle the checkbox.
    from app.events.panel import PanelIntentAction

    descriptor = catalog.get("proposal.next_actions")
    assert descriptor is not None
    mapping = descriptor.to_mapping()
    action = PanelIntentAction(
        id=descriptor.id,
        label=descriptor.labels[0],
        checked=False,
        mapping=mapping,
    )
    note = NoteRef(uuid=TEST_NOTE_UUID, path=TEST_NOTE_PATH, origin="vault")
    panel = PanelInfo(panel_id="p1", instruction="What should I do next?", raw_block=None)
    intent = PanelIntentEvent(
        payload=PanelIntentPayload(note=note, panel=panel, actions=[action]),
        trace_id="trace-#982-proposal-not-executable",
    )
    state = PanelAgentState(
        trace_id=intent.trace_id,
        note=note,
        panel=panel,
        actions=[action],
        intent_event=intent,
        action_catalog=catalog,
    )

    # Rule decider: no LLM override -> the unchecked checkbox stays unchecked.
    result = run_panel_graph(state, decider_mode="rule")

    statuses = {r.id: r.status for r in result.action_results}
    assert statuses["proposal.next_actions"] == "skipped"
    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    # No proposal-only effect fires without explicit confirmation.
    assert "panel.proposal.next_actions" not in event_names
    assert "panel.action.triggered" not in event_names
    assert "proposal.next_actions" not in (result.executed_action_ids or [])


def test_proposal_only_capability_executes_same_pass_when_llm_selects(monkeypatch) -> None:
    """#982 contract: the governance gate must not over-apply.

    An LLM-selected non-governance-bearing proposal (capability_class=proposal,
    authority_class=proposal, requires_human_gate=false) must execute in the
    same pass, because it is the bounded cognitive mediation surface the issue
    introduces. Only governance-bearing capabilities are deferred for human
    confirmation.
    """
    catalog = _proposal_only_catalog()
    note = NoteRef(uuid=TEST_NOTE_UUID, path=TEST_NOTE_PATH, origin="vault")
    panel = PanelInfo(panel_id="p1", instruction="What should I do next?", raw_block=None)
    payload = PanelIntentPayload(note=note, panel=panel, actions=[])
    intent = PanelIntentEvent(payload=payload, trace_id="trace-#982-proposal-same-pass")
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
        lambda: _StubReasoningFacade({"actions": [{"id": "proposal.next_actions"}]}),
    )

    result = run_panel_graph(state, decider_mode="llm")

    statuses = {r.id: r.status for r in result.action_results}
    # Non-governance-bearing proposal executes same pass (status "logged",
    # not "skipped"/"proposal_offered").
    assert statuses["proposal.next_actions"] == "logged"
    assert "proposal.next_actions" in (result.executed_action_ids or [])
    # No governance-bearing downstream event was emitted.
    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    assert "promote.intent.created" not in event_names
    # No proposal_offered gating either: this capability is not governance-bearing.
    proposal_offered = [
        evt
        for evt in result.emitted_events
        if getattr(evt, "event", None) == "panel.action.logged"
        and getattr(evt, "payload", {}).get("reason") == "proposal_offered"
        and getattr(evt, "payload", {}).get("action", {}).get("id") == "proposal.next_actions"
    ]
    assert not proposal_offered, "proposal-only capability must not be gated as a governance-bearing proposal"


def test_governance_gate_is_data_driven_from_catalog(monkeypatch) -> None:
    """#982 AC: the governance gate reads capability_class/authority_class
    from the catalog rather than a hardcoded action-id frozenset.

    Removing capability metadata from a previously-governance-bearing entry
    should drop the gate (proving the gate is no longer pinned to id), while
    a fresh descriptor marked governed_effect/governed_execution should be
    gated even without being in any legacy allowlist.
    """
    from app.agents.panel_agent.graph import _is_governance_bearing
    from app.events.panel import PanelIntentAction

    # Fresh id, never in the legacy hardcoded set, but marked governance-bearing.
    new_catalog = PanelActionCatalog.from_descriptors(
        [
            PanelActionDescriptor(
                id="hypothetical.new.governed",
                intent_type="zone_move",
                downstream_event="hypothetical.new.governed",
                labels=["hypothetical"],
                capability_class="governed_execution",
                authority_class="governed_effect",
                requires_human_gate=True,
            ),
            PanelActionDescriptor(
                id="hypothetical.new.proposal",
                intent_type="proposal",
                downstream_event="panel.proposal.hypothetical",
                labels=["hypothetical proposal"],
                capability_class="proposal",
                authority_class="proposal",
                requires_human_gate=False,
            ),
        ]
    )
    gov_action = PanelIntentAction(
        id="hypothetical.new.governed",
        label="hypothetical",
        checked=False,
        mapping=new_catalog.get("hypothetical.new.governed").to_mapping(),
    )
    prop_action = PanelIntentAction(
        id="hypothetical.new.proposal",
        label="hypothetical proposal",
        checked=False,
        mapping=new_catalog.get("hypothetical.new.proposal").to_mapping(),
    )
    assert _is_governance_bearing(gov_action, new_catalog) is True
    assert _is_governance_bearing(prop_action, new_catalog) is False


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
