import textwrap

from app.agents.panel.agent import PanelAgentResult, handle_note_update
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
    assert result.events == []


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
    assert result.events == []


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

    assert len(result.events) == 1
    event = result.events[0]
    assert event.event_type == "review.promote.evergreen"
    assert event.payload["note_id"] == "note-3"
    assert event.payload["action_text"] == "Gör denna anteckning evergreen"
