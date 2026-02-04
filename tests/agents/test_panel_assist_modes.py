from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from app.agents.panel.agent import handle_note_update

pytestmark = pytest.mark.not_pg


def test_engage_on_request_adds_proposals_and_question(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PANEL_PROACTIVE_ASSIST", "1")
    note_path = tmp_path / "note.md"
    markdown = dedent(
        """\
        ---
        title: Help me
        ---

        %% AI:Start %%
        Instruction: help me
        %% AI:End %%
        """
    )

    result = handle_note_update("NOTE-1", markdown, markdown, note_path=str(note_path))
    assert "<!--ai:suggested_actions:start-->" in result.updated_markdown
    assert "<!--ai:assist:start-->" in result.updated_markdown
    assert "❓" in result.updated_markdown
    assert not [ev for ev in result.events if ev.event == "promote.intent.created"]


def test_proactive_assist_creates_panel_for_eligible_note(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PANEL_PROACTIVE_ASSIST", "1")
    note_path = tmp_path / "eligible.md"
    markdown = dedent(
        """\
        ---
        title: Eligible
        ---
        Plain note with no panel yet.
        """
    )

    result = handle_note_update("NOTE-1", markdown, markdown, note_path=str(note_path), proactive_assist=True)
    assert "%% AI %%" in result.updated_markdown
    assert "<!--ai:suggested_actions:start-->" in result.updated_markdown
    assert "<!--ai:assist:start-->" in result.updated_markdown


def test_proactive_assist_is_idempotent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PANEL_PROACTIVE_ASSIST", "1")
    note_path = tmp_path / "eligible.md"
    markdown = dedent(
        """\
        ---
        title: Eligible
        ---
        Plain note with no panel yet.
        """
    )

    first = handle_note_update("NOTE-1", markdown, markdown, note_path=str(note_path), proactive_assist=True)
    second = handle_note_update(
        "NOTE-1", first.updated_markdown, first.updated_markdown, note_path=str(note_path), proactive_assist=True
    )
    assert second.updated_markdown.count("%% AI %%") == 2
    assert second.updated_markdown.count("<!--ai:assist:start-->") == 1
    assert second.updated_markdown.count("<!--ai:suggested_actions:start-->") == 1


def test_proactive_assist_skips_ineligible_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PANEL_PROACTIVE_ASSIST", "1")
    note_path = tmp_path / ".obsidian" / "settings.md"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    markdown = dedent(
        """\
        ---
        title: Ineligible
        ---
        """
    )

    result = handle_note_update("NOTE-1", markdown, markdown, note_path=str(note_path), proactive_assist=True)
    assert "%% AI %%" not in result.updated_markdown
    assert "<!--ai:assist:start-->" not in result.updated_markdown
