from __future__ import annotations

import json
from uuid import uuid4

from app.agents.panel_agent.graph import run_panel_graph
from app.agents.panel_agent.state import PanelAgentState
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


class _StubChatClient:
    def __init__(self, response: str) -> None:
        self._response = response

    def chat(self, *args, **kwargs) -> str:
        return self._response


def _intent_event_with_action(action: PanelIntentAction, *, trace_id: str = "trace-graph") -> PanelIntentEvent:
    note = NoteRef(uuid=str(uuid4()), path="vault/Note.md", origin="vault")
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


def test_panel_graph_llm_selects_subset(monkeypatch) -> None:
    promote_mapping = PanelActionMapping(
        id="promote.evergreen",
        intent_type="promotion",
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
        "app.agents.panel_agent.graph.get_chat_client",
        lambda intent: _StubChatClient(json.dumps({"actions": ["promote.evergreen"]})),
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
                downstream_event="review.promote.evergreen",
                labels=["Promote"],
                description="Promote note to evergreen",
            )
        ]
    )
    state = _state_from_intent(intent, catalog=catalog)

    monkeypatch.setattr(
        "app.agents.panel_agent.graph.get_chat_client",
        lambda intent: _StubChatClient("not-json"),
    )

    result = run_panel_graph(state, decider_mode="llm")
    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    assert "promote.intent.created" in event_names
    assert "panel.action.triggered" in event_names


def test_panel_graph_llm_can_select_unchecked(monkeypatch) -> None:
    mapping = PanelActionMapping(
        id="promote.evergreen",
        intent_type="promotion",
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
                downstream_event="review.promote.evergreen",
                labels=["Gör denna anteckning evergreen", "Make evergreen"],
                description="Promote note to evergreen",
            )
        ]
    )
    state = _state_from_intent(intent, catalog=catalog)

    monkeypatch.setattr(
        "app.agents.panel_agent.graph.get_chat_client",
        lambda intent: _StubChatClient(
            json.dumps({"actions": [{"id": "promote.evergreen", "reason": "panel instruction"}]})
        ),
    )

    result = run_panel_graph(state, decider_mode="llm")
    statuses = {r.id: r.status for r in result.action_results}
    assert statuses["promote.evergreen"] == "triggered"
