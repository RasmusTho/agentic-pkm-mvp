from app.agents.panel.events import panel_intent_to_event
from app.agents.panel.intents import PanelIntent
from app.settings.panel_actions import PanelActionMapping


def _mapping() -> dict[str, PanelActionMapping]:
    return {
        "Gör denna anteckning evergreen": PanelActionMapping(
            text="Gör denna anteckning evergreen",
            event_type="review.promote.evergreen",
        )
    }


def test_panel_intent_to_event_with_known_mapping():
    mappings = _mapping()
    intent = PanelIntent(kind="action_triggered", action_text="Gör denna anteckning evergreen")

    event = panel_intent_to_event(intent, mappings, note_id="note-123", instruction_text="Behåll fokus")

    assert event is not None
    assert event.event_type == "review.promote.evergreen"
    assert event.payload["note_id"] == "note-123"
    assert event.payload["action_text"] == "Gör denna anteckning evergreen"
    assert event.payload["instruction_text"] == "Behåll fokus"


def test_panel_intent_to_event_unknown_mapping_returns_none():
    intent = PanelIntent(kind="action_triggered", action_text="Okänd")

    event = panel_intent_to_event(intent, {}, note_id="note-123")

    assert event is None


def test_panel_intent_to_event_ignores_non_action_intents():
    intent = PanelIntent(kind="instruction_updated", instruction_text="Ny instruktion")

    event = panel_intent_to_event(intent, _mapping(), note_id="note-123")

    assert event is None
