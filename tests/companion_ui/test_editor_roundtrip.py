"""Editor adapter fixture round-trip tests for Obsidian compatibility spikes."""

from __future__ import annotations

from pathlib import Path

from companion_ui.spikes.codemirror_adapter import CodeMirrorNoteEditorAdapter


FIXTURE_DIR = (
    Path(__file__).resolve().parents[2]
    / "companion-ui"
    / "companion-app"
    / "tests"
    / "fixtures"
    / "obsidian-renderer"
)


def _fixtures() -> list[Path]:
    return sorted(FIXTURE_DIR.glob("*.md"))


def test_codemirror_roundtrip() -> None:
    assert _fixtures(), "Expected obsidian-renderer fixtures"

    for fixture_path in _fixtures():
        raw_markdown = fixture_path.read_text(encoding="utf-8")
        adapter = CodeMirrorNoteEditorAdapter()

        adapter.setMarkdown(raw_markdown)

        assert adapter.getMarkdown() == raw_markdown, fixture_path.name


def test_obsidian_syntax_preserved() -> None:
    raw_markdown = (FIXTURE_DIR / "full-smoke.md").read_text(encoding="utf-8")
    adapter = CodeMirrorNoteEditorAdapter(raw_markdown)
    round_tripped = adapter.getMarkdown()

    for token in (
        "[[ExistingNote|Display Alias]]",
        "![[test-image.png|100x145]]",
        "> [!warning] Custom Title",
        "```mermaid",
        "%% hidden %%",
        "```dataview",
        "<script>alert('xss')</script>",
        "---\n",
    ):
        assert token in round_tripped
    assert round_tripped == raw_markdown
