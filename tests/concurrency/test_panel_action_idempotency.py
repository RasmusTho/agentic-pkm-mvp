import pytest

from app.agents.panel_agent.graph import _handle_action
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
def _reset_idempotency_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.agents.panel_agent.graph._IDEMPOTENCY_GUARD", IdempotencyGuard(ttl_seconds=86400.0))


def test_panel_action_idempotency_ai_id() -> None:
    note = NoteRef(uuid="note-idempotency")
    panel = PanelInfo(panel_id="panel-1", instruction="Do it")
    mapping = PanelActionMapping(
        id="promote.evergreen",
        intent_type="promotion",
        downstream_event="promote.intent.created",
        params={},
    )
    action = PanelIntentAction(id="ai-123", label="Promote", checked=True, mapping=mapping)
    payload = PanelIntentPayload(note=note, panel=panel, actions=[action])
    intent_event = PanelIntentEvent(payload=payload)
    state = PanelAgentState(
        trace_id=intent_event.trace_id,
        note=intent_event.payload.note,
        panel=intent_event.payload.panel,
        actions=[action],
        intent_event=intent_event,
    )

    first_result, first_emitted = _handle_action(state, action, action_wiring={})
    second_result, second_emitted = _handle_action(state, action, action_wiring={})

    assert first_result.status in {"triggered", "logged"}
    assert first_emitted
    assert second_result.status == "skipped"
    assert second_emitted == []
