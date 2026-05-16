from __future__ import annotations

import json

import pytest

from app.agents.panel_agent.graph import run_panel_graph
from app.agents.panel_agent.state import PanelAgentState
from app.components.concurrency import IdempotencyGuard
from app.components.settings.panel_actions_loader import PanelActionCatalog, PanelActionDescriptor
from app.events.panel import (
    NoteRef,
    PanelActionMapping,
    PanelInfo,
    PanelIntentAction,
    PanelIntentEvent,
    PanelIntentPayload,
    PanelLogEntry,
    PanelRuntimeActionResult,
)

TEST_NOTE_UUID = "panel-test-00000000-0000-4000-8000-000000000001"
TEST_NOTE_PATH = "vault/Note.md"
TEST_NOTE_ORIGIN = "vault"


@pytest.fixture(autouse=True)
def _avoid_wiring_io(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.agents.panel_agent.graph.get_default_action_wiring", lambda: {})


@pytest.fixture(autouse=True)
def _reset_idempotency_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.agents.panel_agent.graph._IDEMPOTENCY_GUARD", IdempotencyGuard(ttl_seconds=86400.0))


class _StubReasoningFacade:
    def __init__(self, response: object | Exception) -> None:
        self._response = response

    def structured(self, messages, schema, *, task_kind: str, trace_id: str | None = None) -> object:
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _intent_event_with_action(action: PanelIntentAction, *, trace_id: str = "trace-graph") -> PanelIntentEvent:
    note = NoteRef(uuid=TEST_NOTE_UUID, path=TEST_NOTE_PATH, origin=TEST_NOTE_ORIGIN)
    panel = PanelInfo(panel_id="panel-1", instruction="Promote please.", raw_block=None)
    payload = PanelIntentPayload(note=note, panel=panel, actions=[action])
    return PanelIntentEvent(payload=payload, trace_id=trace_id)


def _state_from_intent(intent: PanelIntentEvent, catalog: PanelActionCatalog | None = None) -> PanelAgentState:
    return PanelAgentState(
        trace_id=intent.trace_id,
        note=intent.payload.note,
        panel=intent.payload.panel,
        actions=list(intent.payload.actions),
        intent_event=intent,
        action_catalog=catalog,
    )


def test_panel_graph_emits_promotion_and_log_events() -> None:
    label = "Gör denna anteckning evergreen"
    mapping = PanelActionMapping(
        id="promote.evergreen",
        intent_type="promotion",
        trust_verb="APPLY",
        downstream_event="review.promote.evergreen",
        params={"maturity": "evergreen"},
    )
    action = PanelIntentAction(id=mapping.id, label=label, checked=True, mapping=mapping)
    intent = _intent_event_with_action(action, trace_id="trace-graph-promote")
    state = _state_from_intent(intent)

    result = run_panel_graph(state)

    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    assert {"panel.intent.executed", "panel.action.triggered", "promote.intent.created", "panel.log.created"} <= event_names
    assert result.log_entry is not None
    assert isinstance(result.log_entry, PanelLogEntry)
    assert "panel.intent.executed" in result.log_entry.summary
    assert isinstance(result.action_results[0], PanelRuntimeActionResult)


def test_panel_graph_logs_unmapped_actions() -> None:
    action = PanelIntentAction(id="do.nothing", label="Do nothing", checked=True, mapping=None)
    intent = _intent_event_with_action(action, trace_id="trace-graph-unmapped")
    state = _state_from_intent(intent)

    result = run_panel_graph(state)

    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    assert "panel.intent.executed" in event_names
    assert "panel.action.logged" in event_names
    assert "promote.intent.created" not in event_names

    assert result.action_results[0].status == "logged"
    assert result.action_results[0].details.get("reason") == "unmapped_action"


def test_panel_graph_logs_unknown_mapping_as_unresolved() -> None:
    catalog = PanelActionCatalog.from_descriptors(
        [
            PanelActionDescriptor(
                id="promote.evergreen",
                intent_type="promotion",
                trust_verb="APPLY",
                downstream_event="review.promote.evergreen",
                labels=["Promote"],
            )
        ]
    )
    action = PanelIntentAction(
        id="orphan.action",
        label="Orphan",
        checked=True,
        mapping=PanelActionMapping(
            id="orphan.action",
            intent_type="promotion",
            trust_verb="APPLY",
            downstream_event="review.promote.evergreen",
            params={"maturity": "evergreen"},
        ),
    )
    intent = _intent_event_with_action(action, trace_id="trace-graph-unknown-mapping")
    state = _state_from_intent(intent, catalog=catalog)

    result = run_panel_graph(state)

    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    assert "panel.action.logged" in event_names
    assert "promote.intent.created" not in event_names
    assert result.action_results[0].status == "logged"
    assert result.action_results[0].details.get("reason") == "unknown_mapping"


def test_panel_graph_watcher_mode_blocks_manual_only_actions() -> None:
    catalog = PanelActionCatalog.from_descriptors(
        [
            PanelActionDescriptor(
                id="note.archive",
                intent_type="archival",
                downstream_event="note.archive",
                labels=["Archive"],
                manual_only=True,
                watcher_allowed=False,
            )
        ]
    )
    action = PanelIntentAction(
        id="note.archive",
        label="Archive",
        checked=True,
        mapping=PanelActionMapping(
            id="note.archive",
            intent_type="archival",
            downstream_event="note.archive",
            params={},
        ),
    )
    intent = _intent_event_with_action(action, trace_id="trace-graph-watcher-policy")
    state = _state_from_intent(intent, catalog=catalog)
    state.policy_flags["execution_mode"] = "watcher"

    result = run_panel_graph(state)

    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    assert "panel.action.logged" in event_names
    assert "promote.intent.created" not in event_names
    assert result.action_results[0].status == "logged"
    assert result.action_results[0].details.get("reason") == "watcher_not_allowed"


def test_panel_graph_marks_ambiguous_label_as_ambiguous() -> None:
    catalog = PanelActionCatalog.from_descriptors(
        [
            PanelActionDescriptor(
                id="promote.evergreen",
                intent_type="promotion",
                trust_verb="APPLY",
                downstream_event="review.promote.evergreen",
                labels=["Shared Label"],
            ),
            PanelActionDescriptor(
                id="note.archive",
                intent_type="archival",
                downstream_event="note.archive",
                labels=["Shared Label"],
            ),
        ]
    )
    action = PanelIntentAction(id="shared.label", label="Shared Label", checked=True, mapping=None)
    intent = _intent_event_with_action(action, trace_id="trace-graph-ambiguous")
    state = _state_from_intent(intent, catalog=catalog)

    result = run_panel_graph(state)

    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    assert "panel.action.logged" in event_names
    assert "promote.intent.created" not in event_names
    assert result.action_results[0].status == "logged"
    assert result.action_results[0].details.get("reason") == "ambiguous_action"


def test_panel_graph_llm_selects_subset(monkeypatch) -> None:
    promote_mapping = PanelActionMapping(
        id="promote.evergreen",
        intent_type="promotion",
        trust_verb="APPLY",
        downstream_event="review.promote.evergreen",
        params={"maturity": "evergreen"},
    )
    promote = PanelIntentAction(id=promote_mapping.id, label="Promote", checked=True, mapping=promote_mapping)
    other = PanelIntentAction(id="note.archive", label="Archive", checked=True, mapping=None)
    intent = _intent_event_with_action(promote)
    intent.payload.actions.append(other)
    catalog = PanelActionCatalog.from_descriptors(
        [
            PanelActionDescriptor(
                id="promote.evergreen",
                intent_type="promotion",
                trust_verb="APPLY",
                downstream_event="review.promote.evergreen",
                labels=["Gör denna anteckning evergreen", "Promote"],
                description="Promote note to evergreen",
            ),
            PanelActionDescriptor(
                id="note.archive",
                intent_type="archival",
                downstream_event="note.archive",
                labels=["Archive"],
                description="Archive this note",
            ),
        ]
    )
    state = _state_from_intent(intent, catalog=catalog)

    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade",
        lambda: _StubReasoningFacade({"actions": ["promote.evergreen"]}),
    )

    result = run_panel_graph(state, decider_mode="llm")
    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    assert "promote.intent.created" in event_names
    assert "panel.action.triggered" in event_names
    assert "panel.log.created" in event_names
    assert "panel.action.logged" not in event_names

    statuses = {r.id: r.status for r in result.action_results}
    assert statuses["promote.evergreen"] == "triggered"
    assert statuses["note.archive"] == "skipped"


def test_panel_graph_llm_falls_back_on_malformed(monkeypatch) -> None:
    mapping = PanelActionMapping(
        id="promote.evergreen",
        intent_type="promotion",
        trust_verb="APPLY",
        downstream_event="review.promote.evergreen",
        params={"maturity": "evergreen"},
    )
    action = PanelIntentAction(id=mapping.id, label="Promote", checked=True, mapping=mapping)
    intent = _intent_event_with_action(action)
    catalog = PanelActionCatalog.from_descriptors(
        [
            PanelActionDescriptor(
                id="promote.evergreen",
                intent_type="promotion",
                trust_verb="APPLY",
                downstream_event="review.promote.evergreen",
                labels=["Promote"],
                description="Promote note to evergreen",
            )
        ]
    )
    state = _state_from_intent(intent, catalog=catalog)

    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade",
        lambda: _StubReasoningFacade(json.JSONDecodeError("Expecting value", "not-json", 0)),
    )

    result = run_panel_graph(state, decider_mode="llm")
    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    assert "promote.intent.created" in event_names
    assert "panel.action.triggered" in event_names


def test_panel_graph_llm_can_select_unchecked(monkeypatch) -> None:
    mapping = PanelActionMapping(
        id="promote.evergreen",
        intent_type="promotion",
        trust_verb="APPLY",
        downstream_event="review.promote.evergreen",
        params={"maturity": "evergreen"},
    )
    action = PanelIntentAction(id=mapping.id, label="Make evergreen", checked=False, mapping=mapping)
    intent = _intent_event_with_action(action)
    catalog = PanelActionCatalog.from_descriptors(
        [
            PanelActionDescriptor(
                id="promote.evergreen",
                intent_type="promotion",
                trust_verb="APPLY",
                downstream_event="review.promote.evergreen",
                labels=["Gör denna anteckning evergreen", "Make evergreen"],
                description="Promote note to evergreen",
            )
        ]
    )
    state = _state_from_intent(intent, catalog=catalog)

    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade",
        lambda: _StubReasoningFacade(
            {"actions": [{"id": "promote.evergreen", "reason": "panel instruction"}]}
        ),
    )

    result = run_panel_graph(state, decider_mode="llm")
    statuses = {r.id: r.status for r in result.action_results}
    assert statuses["promote.evergreen"] == "triggered"


def test_panel_graph_llm_empty_selection_uses_instruction_hint_for_single_promotion(monkeypatch) -> None:
    mapping = PanelActionMapping(
        id="promote.evergreen",
        intent_type="promotion",
        trust_verb="APPLY",
        downstream_event="review.promote.evergreen",
        params={"maturity": "evergreen"},
    )
    action = PanelIntentAction(id=mapping.id, label="Make this note evergreen", checked=True, mapping=mapping)
    note = NoteRef(uuid=TEST_NOTE_UUID, path=TEST_NOTE_PATH, origin=TEST_NOTE_ORIGIN)
    panel = PanelInfo(
        panel_id="panel-1",
        instruction="Make this note evergreen. Do not summarize; just promote it.",
        raw_block=None,
    )
    payload = PanelIntentPayload(note=note, panel=panel, actions=[action])
    intent = PanelIntentEvent(payload=payload, trace_id="trace-graph-llm-empty-promotion")
    catalog = PanelActionCatalog.from_descriptors(
        [
            PanelActionDescriptor(
                id="promote.evergreen",
                intent_type="promotion",
                trust_verb="APPLY",
                downstream_event="review.promote.evergreen",
                labels=["Make this note evergreen", "Promote to evergreen"],
                description="Promote note to evergreen",
                llm_hint="Choose this when the instruction explicitly asks to promote or make the note evergreen.",
            )
        ]
    )
    state = _state_from_intent(intent, catalog=catalog)

    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade",
        lambda: _StubReasoningFacade({"actions": []}),
    )

    result = run_panel_graph(state, decider_mode="llm")
    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    assert "promote.intent.created" in event_names
    statuses = {r.id: r.status for r in result.action_results}
    assert statuses["promote.evergreen"] == "triggered"


def test_panel_graph_llm_empty_selection_does_not_force_non_promotion(monkeypatch) -> None:
    action = PanelIntentAction(id="panel.reply", label="Reflect only, no promotion", checked=True, mapping=None)
    note = NoteRef(uuid=TEST_NOTE_UUID, path=TEST_NOTE_PATH, origin=TEST_NOTE_ORIGIN)
    panel = PanelInfo(panel_id="panel-1", instruction="Reflect only, no promotion.", raw_block=None)
    payload = PanelIntentPayload(note=note, panel=panel, actions=[action])
    intent = PanelIntentEvent(payload=payload, trace_id="trace-graph-llm-empty-chat")
    catalog = PanelActionCatalog.from_descriptors(
        [
            PanelActionDescriptor(
                id="panel.reply",
                intent_type="chat",
                downstream_event="panel.reply.created",
                labels=["Reflect only, no promotion"],
                description="Leave a brief reply in the panel log.",
            )
        ]
    )
    state = _state_from_intent(intent, catalog=catalog)

    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade",
        lambda: _StubReasoningFacade({"actions": []}),
    )

    result = run_panel_graph(state, decider_mode="llm")
    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    assert "promote.intent.created" not in event_names
    statuses = {r.id: r.status for r in result.action_results}
    assert statuses["panel.reply"] == "skipped"


def test_panel_graph_llm_empty_selection_honors_negated_promotion_instruction(monkeypatch) -> None:
    mapping = PanelActionMapping(
        id="promote.evergreen",
        intent_type="promotion",
        trust_verb="APPLY",
        downstream_event="review.promote.evergreen",
        params={"maturity": "evergreen"},
    )
    action = PanelIntentAction(id=mapping.id, label="Make this note evergreen", checked=True, mapping=mapping)
    note = NoteRef(uuid=TEST_NOTE_UUID, path=TEST_NOTE_PATH, origin=TEST_NOTE_ORIGIN)
    panel = PanelInfo(
        panel_id="panel-1",
        instruction="Do not promote this note yet. Reflect only, no promotion.",
        raw_block=None,
    )
    payload = PanelIntentPayload(note=note, panel=panel, actions=[action])
    intent = PanelIntentEvent(payload=payload, trace_id="trace-graph-llm-negated-promotion")
    catalog = PanelActionCatalog.from_descriptors(
        [
            PanelActionDescriptor(
                id="promote.evergreen",
                intent_type="promotion",
                trust_verb="APPLY",
                downstream_event="review.promote.evergreen",
                labels=["Make this note evergreen", "Promote to evergreen"],
                description="Promote note to evergreen",
                llm_hint="Choose this when the instruction explicitly asks to promote or make the note evergreen.",
            )
        ]
    )
    state = _state_from_intent(intent, catalog=catalog)

    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade",
        lambda: _StubReasoningFacade({"actions": []}),
    )

    result = run_panel_graph(state, decider_mode="llm")
    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    assert "promote.intent.created" not in event_names
    statuses = {r.id: r.status for r in result.action_results}
    assert statuses["promote.evergreen"] == "skipped"


def _state_no_actions(instruction: str, catalog: PanelActionCatalog | None = None) -> PanelAgentState:
    """Build a PanelAgentState with no checkbox actions (freeform-only panel)."""
    note = NoteRef(uuid=TEST_NOTE_UUID, path=TEST_NOTE_PATH, origin=TEST_NOTE_ORIGIN)
    panel = PanelInfo(panel_id="panel-1", instruction=instruction, raw_block=None)
    payload = PanelIntentPayload(note=note, panel=panel, actions=[])
    intent = PanelIntentEvent(payload=payload, trace_id="trace-freeform")
    return PanelAgentState(
        trace_id=intent.trace_id,
        note=intent.payload.note,
        panel=intent.payload.panel,
        actions=[],
        intent_event=intent,
        action_catalog=catalog,
    )


def test_panel_graph_freeform_proposes_catalog_action_without_checkboxes(monkeypatch) -> None:
    """Freeform path: instruction alone drives catalog discovery when no checkboxes are present."""
    catalog = PanelActionCatalog.from_descriptors(
        [
            PanelActionDescriptor(
                id="promote.evergreen",
                intent_type="promotion",
                trust_verb="APPLY",
                downstream_event="review.promote.evergreen",
                labels=["Make this note evergreen"],
                description="Promote note to evergreen",
                llm_hint="Choose this when the instruction asks to promote or make the note evergreen.",
                params={"maturity": "evergreen"},
            )
        ]
    )
    state = _state_no_actions("Make this note evergreen.", catalog=catalog)

    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade",
        lambda: _StubReasoningFacade({"actions": [{"id": "promote.evergreen", "reason": "instruction match"}]}),
    )

    result = run_panel_graph(state, decider_mode="llm")
    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    # Proposal vs execution boundary (#979):
    # A freeform LLM proposal for a governance-bearing capability
    # (`promote.evergreen`, capability_class: governed_execution) must not
    # execute same-pass. It is surfaced as an unchecked proposal via a
    # `panel.action.logged` proposal_offered signal; the governed
    # `promote.intent.created` event only fires after explicit human
    # confirmation.
    assert "promote.intent.created" not in event_names
    assert "panel.action.triggered" not in event_names
    assert "panel.action.logged" in event_names
    statuses = {r.id: r.status for r in result.action_results}
    assert statuses["promote.evergreen"] == "skipped"
    reasons = {r.id: r.details.get("reason") for r in result.action_results}
    assert reasons["promote.evergreen"] == "proposal_offered"
    assert "promote.evergreen" in result.proposed_action_ids
    # The action is selected (LLM chose it) but written back as unchecked.
    assert result.selected_action_ids == ["promote.evergreen"]
    proposed_action = next(a for a in result.actions if a.id == "promote.evergreen")
    assert proposed_action.checked is False


def test_panel_graph_freeform_rejects_out_of_catalog_id(monkeypatch) -> None:
    """Freeform path: LLM proposals not in the active catalog are silently dropped."""
    catalog = PanelActionCatalog.from_descriptors(
        [
            PanelActionDescriptor(
                id="promote.evergreen",
                intent_type="promotion",
                trust_verb="APPLY",
                downstream_event="review.promote.evergreen",
                labels=["Make this note evergreen"],
                description="Promote note to evergreen",
            )
        ]
    )
    state = _state_no_actions("Make this note evergreen.", catalog=catalog)

    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade",
        lambda: _StubReasoningFacade({"actions": [{"id": "invented.action"}]}),
    )

    result = run_panel_graph(state, decider_mode="llm")
    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    assert "promote.intent.created" not in event_names
    assert result.action_results == []


def test_panel_graph_freeform_empty_catalog_no_actions(monkeypatch) -> None:
    """Freeform path: empty catalog gracefully produces no proposals."""
    catalog = PanelActionCatalog.from_descriptors([])
    state = _state_no_actions("Make this note evergreen.", catalog=catalog)

    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade",
        lambda: _StubReasoningFacade({"actions": [{"id": "promote.evergreen"}]}),
    )

    result = run_panel_graph(state, decider_mode="llm")
    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    assert "promote.intent.created" not in event_names
    assert result.action_results == []


def test_panel_graph_freeform_falls_back_to_rule_on_llm_error(monkeypatch) -> None:
    """Freeform path: LLM failure falls back to rule mode (which is a no-op for no-checkbox panels)."""
    catalog = PanelActionCatalog.from_descriptors(
        [
            PanelActionDescriptor(
                id="promote.evergreen",
                intent_type="promotion",
                trust_verb="APPLY",
                downstream_event="review.promote.evergreen",
                labels=["Make this note evergreen"],
                description="Promote note to evergreen",
            )
        ]
    )
    state = _state_no_actions("Make this note evergreen.", catalog=catalog)

    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade",
        lambda: _StubReasoningFacade(RuntimeError("LLM unavailable")),
    )

    result = run_panel_graph(state, decider_mode="llm")
    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    assert "promote.intent.created" not in event_names
    assert result.action_results == []


def test_panel_graph_skips_idempotent_duplicate() -> None:
    mapping = PanelActionMapping(
        id="promote.evergreen",
        intent_type="promotion",
        trust_verb="APPLY",
        downstream_event="review.promote.evergreen",
        params={"maturity": "evergreen"},
    )
    action = PanelIntentAction(id=mapping.id, label="Promote", checked=True, mapping=mapping)
    intent = _intent_event_with_action(action, trace_id="trace-graph-idem")

    first = run_panel_graph(_state_from_intent(intent))
    first_events = {getattr(evt, "event", None) for evt in first.emitted_events}
    assert "promote.intent.created" in first_events
    executed = next(evt for evt in first.emitted_events if getattr(evt, "event", None) == "panel.intent.executed")
    assert action.id in (executed.payload.executed_action_ids or [])

    second = run_panel_graph(_state_from_intent(intent))
    second_events = {getattr(evt, "event", None) for evt in second.emitted_events}
    assert "promote.intent.created" not in second_events
    assert second.action_results[0].status == "skipped"
    assert second.action_results[0].details.get("reason") == "idempotent_duplicate"


def test_panel_graph_cognition_mode_in_emitted_events_rule() -> None:
    """cognition_mode='rule' is surfaced in panel.intent.executed and panel.log.created."""
    mapping = PanelActionMapping(
        id="promote.evergreen",
        intent_type="promotion",
        trust_verb="APPLY",
        downstream_event="review.promote.evergreen",
        params={"maturity": "evergreen"},
    )
    action = PanelIntentAction(id=mapping.id, label="Promote", checked=True, mapping=mapping)
    intent = _intent_event_with_action(action, trace_id="trace-cognition-rule")
    state = _state_from_intent(intent)

    result = run_panel_graph(state, decider_mode="rule")

    executed = next(
        evt for evt in result.emitted_events if getattr(evt, "event", None) == "panel.intent.executed"
    )
    assert executed.payload.cognition_mode == "rule"

    log_evt = next(
        evt for evt in result.emitted_events if getattr(evt, "event", None) == "panel.log.created"
    )
    assert log_evt.payload.cognition_mode == "rule"


def test_panel_graph_cognition_mode_in_emitted_events_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """cognition_mode='llm' is surfaced in emitted events when LLM backend is active."""
    mapping = PanelActionMapping(
        id="promote.evergreen",
        intent_type="promotion",
        trust_verb="APPLY",
        downstream_event="review.promote.evergreen",
        params={"maturity": "evergreen"},
    )
    action = PanelIntentAction(id=mapping.id, label="Promote", checked=True, mapping=mapping)
    intent = _intent_event_with_action(action, trace_id="trace-cognition-llm")
    state = _state_from_intent(intent)

    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade",
        lambda: _StubReasoningFacade({"actions": [{"id": "promote.evergreen", "reason": "llm_selected"}]}),
    )

    result = run_panel_graph(state, decider_mode="llm")

    executed = next(
        evt for evt in result.emitted_events if getattr(evt, "event", None) == "panel.intent.executed"
    )
    assert executed.payload.cognition_mode == "llm"

    log_evt = next(
        evt for evt in result.emitted_events if getattr(evt, "event", None) == "panel.log.created"
    )
    assert log_evt.payload.cognition_mode == "llm"
