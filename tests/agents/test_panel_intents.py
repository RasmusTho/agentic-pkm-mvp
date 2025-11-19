from app.agents.panel.intents import (
    PanelIntent,
    diff_panel_states,
    enrich_panel_intents,
    resolve_action_event_type,
)
from app.agents.panel.schema import PanelAction, PanelState
from app.settings.panel_actions import PanelActionMapping


def make_state(instruction_text: str = "", actions: list[tuple[bool, str]] | None = None) -> PanelState:
    action_objs = [PanelAction(checked=checked, text=text) for checked, text in (actions or [])]
    return PanelState(instruction_text=instruction_text, actions=action_objs)


def test_newly_checked_action_produces_intent():
    old_state = make_state(actions=[(False, "Gör denna anteckning evergreen"), (False, "Arkivera den här anteckningen")])
    new_state = make_state(actions=[(True, "Gör denna anteckning evergreen"), (False, "Arkivera den här anteckningen")])

    intents = diff_panel_states(old_state, new_state)

    assert intents == [
        PanelIntent(kind="action_triggered", action_text="Gör denna anteckning evergreen")
    ]


def test_no_change_produces_no_intent():
    state = make_state(actions=[(False, "A"), (True, "B")])

    intents = diff_panel_states(state, state)

    assert intents == []


def test_instruction_change_emits_intent():
    old_state = make_state(instruction_text="A")
    new_state = make_state(instruction_text="B")

    intents = diff_panel_states(old_state, new_state)

    assert intents == [PanelIntent(kind="instruction_updated", instruction_text="B")]


def test_resolve_action_event_type_matches_mapping():
    mappings = {
        "Gör denna anteckning evergreen": PanelActionMapping(
            text="Gör denna anteckning evergreen", event_type="review.promote.evergreen"
        )
    }
    intent = PanelIntent(kind="action_triggered", action_text="Gör denna anteckning evergreen")

    event_type = resolve_action_event_type(intent, mappings)

    assert event_type == "review.promote.evergreen"


def test_resolve_action_event_type_missing_returns_none():
    mappings = {}
    intent = PanelIntent(kind="action_triggered", action_text="Okänd")

    assert resolve_action_event_type(intent, mappings) is None


def test_enrich_panel_intents_sets_event_type():
    mappings = {
        "Gör denna anteckning evergreen": PanelActionMapping(
            text="Gör denna anteckning evergreen", event_type="review.promote.evergreen"
        )
    }
    intents = [PanelIntent(kind="action_triggered", action_text="Gör denna anteckning evergreen")]

    enriched = enrich_panel_intents(intents, mappings)

    assert enriched[0].event_type == "review.promote.evergreen"
