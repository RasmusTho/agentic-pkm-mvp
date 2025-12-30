from app.agents.panel_agent.graph import _handle_action
from app.events.panel import (
    NoteRef,
    PanelActionMapping,
    PanelInfo,
    PanelIntentAction,
    PanelIntentEvent,
    PanelIntentPayload,
)


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

    first_result, first_emitted = _handle_action(intent_event, action, action_wiring={})
    second_result, second_emitted = _handle_action(intent_event, action, action_wiring={})

    assert first_result.status in {"triggered", "logged"}
    assert first_emitted
    assert second_result.status == "skipped"
    assert second_emitted == []
