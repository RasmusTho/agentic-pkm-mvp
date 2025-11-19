import textwrap

from app.agents.panel.parser import parse_panel


def test_parse_panel_empty():
    markdown = """# Title\nSome body text without AI panel."""
    state = parse_panel(markdown)
    assert state.instruction_text == ""
    assert state.actions == []
    assert state.logs == []


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
