import textwrap

from app.agents.panel.agent import PanelAgentResult, handle_note_update
from app.agents.panel.parser import parse_panel
from app.settings.panel_actions import PanelActionMapping


def test_panel_agent_removes_completed_action_and_logs():
    old_markdown = textwrap.dedent(
        """
        ## AI-instruktion
        Gör något fint.
        
        ## AI-åtgärder
        - [ ] Gör denna anteckning evergreen
        - [ ] Arkivera den här anteckningen
        """
    )
    new_markdown = textwrap.dedent(
        """
        ## AI-instruktion
        Gör något fint.
        
        ## AI-åtgärder
        - [x] Gör denna anteckning evergreen
        - [ ] Arkivera den här anteckningen
        """
    )

    result = handle_note_update("note-1", old_markdown, new_markdown)

    assert isinstance(result, PanelAgentResult)
    assert [intent.kind for intent in result.intents] == ["action_triggered"]
    action_intent = result.intents[0]
    assert action_intent.action_text == "Gör denna anteckning evergreen"
    assert "- [x] Gör denna anteckning evergreen" not in result.updated_markdown
    assert "- [ ] Arkivera den här anteckningen" in result.updated_markdown
    assert "> [!info]- AI status" in result.updated_markdown
    assert "- ✅ Gör denna anteckning evergreen" in result.updated_markdown
    event_names = [ev.event for ev in result.events]
    assert "panel.intent.created" in event_names
    assert "panel.intent.executed" in event_names


def test_panel_agent_instruction_updates_passthrough_markdown():
    old_markdown = textwrap.dedent(
        """
        ## AI-instruktion
        Gamla instruktionen
        """
    )
    new_markdown = textwrap.dedent(
        """
        ## AI-instruktion
        Nya instruktionen
        """
    )

    result = handle_note_update("note-2", old_markdown, new_markdown)

    assert [intent.kind for intent in result.intents] == ["instruction_updated"]
    assert result.intents[0].instruction_text == "Nya instruktionen"
    assert result.updated_markdown.strip() == new_markdown.strip()
    event_names = [ev.event for ev in result.events]
    assert "panel.intent.created" in event_names
    assert "panel.intent.executed" in event_names


def test_panel_agent_emits_events_for_mapped_actions():
    old_markdown = textwrap.dedent(
        """
        ## AI-instruktion
        Gör något fint.
        
        ## AI-åtgärder
        - [ ] Gör denna anteckning evergreen
        """
    )
    new_markdown = textwrap.dedent(
        """
        ## AI-instruktion
        Gör något fint.
        
        ## AI-åtgärder
        - [x] Gör denna anteckning evergreen
        """
    )
    mappings = {
        "Gör denna anteckning evergreen": PanelActionMapping(
            text="Gör denna anteckning evergreen", event_type="review.promote.evergreen"
        )
    }

    result = handle_note_update("note-3", old_markdown, new_markdown, action_mappings=mappings)

    event_names = {ev.event for ev in result.events}
    assert "review.promote.evergreen" in event_names
    assert "panel.intent.created" in event_names
    assert "panel.intent.executed" in event_names
    promote_events = [ev for ev in result.events if ev.event == "review.promote.evergreen"]
    assert promote_events
    assert promote_events[0].payload["note_id"] == "note-3"
    assert promote_events[0].payload["action_text"] == "Gör denna anteckning evergreen"


def test_panel_parser_accepts_label_sections_and_checkbox_fallback():
    markdown = textwrap.dedent(
        """
        %% AI:Start %%
        Instruction: Please do the thing
        - [x] Make this note evergreen
        %% AI:End %%
        """
    )

    state = parse_panel(markdown)
    assert state.instruction_text.startswith("Please do the thing")
    assert state.actions
    assert state.actions[0].text == "Make this note evergreen"


def test_suggested_actions_preserve_checked_state_and_trigger_intent():
    old_markdown = textwrap.dedent(
        """
        %% AI %%
        ## AI-åtgärder
        <!--ai:suggested_actions:start-->
        - [ ] Make this note evergreen <!--ai:id=651d3ca5-->
        - [ ] Create a separate summary note <!--ai:id=aad175cb-->
        - [ ] Archive this note <!--ai:id=da676f7d-->
        <!--ai:suggested_actions:end-->
        %% AI %%
        """
    )
    new_markdown = textwrap.dedent(
        """
        %% AI %%
        ## AI-åtgärder
        <!--ai:suggested_actions:start-->
        - [x] Make this note evergreen <!--ai:id=651d3ca5-->
        - [ ] Create a separate summary note <!--ai:id=aad175cb-->
        - [ ] Archive this note <!--ai:id=da676f7d-->
        <!--ai:suggested_actions:end-->
        %% AI %%
        """
    )

    result = handle_note_update("note-checked", old_markdown, new_markdown)
    assert any(intent.kind == "action_triggered" and intent.action_text == "Make this note evergreen" for intent in result.intents)
