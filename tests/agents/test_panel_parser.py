import textwrap

from app.agents.panel.parser import parse_panel


def test_parse_panel_empty():
    markdown = """# Title\nSome body text without AI panel."""
    state = parse_panel(markdown)
    assert state.instruction_text == ""
    assert state.actions == []
    assert state.logs == []
    assert state.spans == []
    assert state.fenced is False


def test_parse_panel_instruction_only():
    markdown = textwrap.dedent(
        """
        ## AI-instruktion
        
        Detta är min intention.
        Mer text här.
        
        ## Något annat
        Innehåll som inte ska påverka panelen.
        """
    )
    state = parse_panel(markdown)
    assert state.instruction_text == "Detta är min intention.\nMer text här."
    assert state.actions == []
    assert state.logs == []
    assert state.spans != []
    assert state.fenced is False


def test_parse_panel_actions_only():
    markdown = textwrap.dedent(
        """
        ## AI-åtgärder
        
        - [ ] Gör denna anteckning evergreen
        - [x] Arkivera den här anteckningen
        - [ ] Skapa en separat sammanfattningsanteckning
        """
    )
    state = parse_panel(markdown)
    assert [action.checked for action in state.actions] == [False, True, False]
    assert [action.text for action in state.actions] == [
        "Gör denna anteckning evergreen",
        "Arkivera den här anteckningen",
        "Skapa en separat sammanfattningsanteckning",
    ]
    assert state.spans != []
    assert state.fenced is False


def test_parse_panel_full_with_log():
    markdown = textwrap.dedent(
        """
        ## Introduktion
        Innehåll innan panelen.
        
        ## AI-instruktion
        Snälla, gör följande.\nPrioritera evergreen-status.
        
        ## AI-åtgärder
        - [ ] Gör denna anteckning evergreen
        - [x] Arkivera den här anteckningen
        
        ## AI-logg
        - 2025-11-19 22:05 – Gjorde: "Gör denna anteckning evergreen"
        - 2025-11-20 08:10 – Gjorde: "Arkivera den här anteckningen"
        """
    )
    state = parse_panel(markdown)
    assert state.instruction_text == "Snälla, gör följande.\nPrioritera evergreen-status."
    assert [action.checked for action in state.actions] == [False, True]
    assert [action.text for action in state.actions] == [
        "Gör denna anteckning evergreen",
        "Arkivera den här anteckningen",
    ]
    assert [entry.raw for entry in state.logs] == [
        '- 2025-11-19 22:05 – Gjorde: "Gör denna anteckning evergreen"',
        '- 2025-11-20 08:10 – Gjorde: "Arkivera den här anteckningen"',
    ]
    assert state.spans != []
    assert state.fenced is False


def test_parse_panel_with_fences():
    markdown = textwrap.dedent(
        """
        # Note with fenced panel

        %% AI:Start %%
        ## AI-instruktion
        Detta är min intention.

        ## AI-åtgärder
        - [ ] Gör denna anteckning evergreen

        %% ai slut %%
        """
    )
    state = parse_panel(markdown)
    assert state.instruction_text == "Detta är min intention."
    assert [a.text for a in state.actions] == ["Gör denna anteckning evergreen"]
    assert state.fenced is True
    assert len(state.spans) == 1
    start, end = state.spans[0]
    assert start < end


def test_parse_panel_tolerant_ai_fences():
    markdown = textwrap.dedent(
        """
        %%AI panel%%
        ## AI-instruktion
        Gör saker.
        ## AI-åtgärder
        - [ ] Förslag 1
        %%   ai   %%
        """
    )
    state = parse_panel(markdown)
    assert state.fenced is True
    assert len(state.spans) == 1
    assert state.instruction_text.startswith("Gör saker")
    assert [a.text for a in state.actions] == ["Förslag 1"]

def test_parse_panel_action_with_ai_id_comment():
    markdown = textwrap.dedent(
        """
        ## AI-åtgärder
        - [x] Make this note evergreen <!--ai:id=promote.evergreen-->
        """
    )
    state = parse_panel(markdown)
    assert len(state.actions) == 1
    action = state.actions[0]
    assert action.action_id == "promote.evergreen"
    assert action.checked is True
    assert action.text == "Make this note evergreen"
