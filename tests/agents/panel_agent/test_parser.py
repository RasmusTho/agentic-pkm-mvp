from __future__ import annotations

from app.agents.panel_agent.parser import find_panels, parse_panel


def _panel_markdown() -> str:
    return """%% AI:Start %%
### AI-instruktion
Gör en sak.

### AI-åtgärder
- [ ] Action label 1
- [x] Action label 2
- [ ] Action label 3

### AI-logg
- tidigare logg
%% AI:End %%
"""


def test_find_single_panel_in_note() -> None:
    markdown = _panel_markdown()
    panels = find_panels(markdown)

    assert len(panels) == 1
    panel = panels[0]
    assert panel.panel_id == "panel-1"
    assert "%% AI:Start %%" in panel.raw_block
    assert "Action label 2" in panel.raw_block


def test_parse_panel_extracts_instruction_and_actions() -> None:
    panel_block = _panel_markdown()
    parsed = parse_panel(panel_block, panel_id="panel-1")

    assert parsed.instruction.strip() == "Gör en sak."
    labels = [a.label for a in parsed.actions]
    states = [a.checked for a in parsed.actions]

    assert labels == ["Action label 1", "Action label 2", "Action label 3"]
    assert states == [False, True, False]
