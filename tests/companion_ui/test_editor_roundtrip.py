"""Editor adapter fixture round-trip tests for Obsidian compatibility spikes."""

from __future__ import annotations

from pathlib import Path

from companion_ui.spikes.codemirror_adapter import CodeMirrorNoteEditorAdapter
from tests.companion_ui.rich_editor_spike_adapters import (
    RichEditorSourceModeSpikeAdapter,
    mdxeditor_spike_adapter,
    milkdown_spike_adapter,
)


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


def test_milkdown_roundtrip() -> None:
    _assert_roundtrip(milkdown_spike_adapter())


def test_mdxeditor_roundtrip() -> None:
    _assert_roundtrip(mdxeditor_spike_adapter())


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


def test_rich_editor_spike_adapters_are_inert() -> None:
    for adapter in (milkdown_spike_adapter(), mdxeditor_spike_adapter()):
        adapter.setMarkdown("Body")
        result = adapter.result()

        assert adapter.getMarkdown() == "Body"
        assert adapter.autosave_enabled is False
        assert adapter.production_wired is False
        assert adapter.write_calls == ()
        assert result.destructive_transformations == ()
        assert result.frontmatter_preserved is True
        assert result.obsidian_syntax_preserved is True
        assert result.recommendation == "defer"

    assert mdxeditor_spike_adapter().result().mdx_jsx_enabled is False


def _assert_roundtrip(adapter: RichEditorSourceModeSpikeAdapter) -> None:
    assert _fixtures(), "Expected obsidian-renderer fixtures"

    for fixture_path in _fixtures():
        raw_markdown = fixture_path.read_text(encoding="utf-8")

        adapter.setMarkdown(raw_markdown)

        assert adapter.getMarkdown() == raw_markdown, (
            f"{adapter.editor_name}: {fixture_path.name}"
        )
