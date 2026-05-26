"""Test-only rich editor spike adapters for #1306.

These adapters intentionally live under tests, not under ``companion_ui``.
The #1306 production-surface guard requires no rich-editor package names in
``companion-ui/companion-app/companion_ui``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RichEditorSpikeResult:
    editor_name: str
    destructive_transformations: tuple[str, ...]
    frontmatter_preserved: bool
    obsidian_syntax_preserved: bool
    mdx_jsx_enabled: bool
    mutation_interception: str
    recommendation: str


class RichEditorSourceModeSpikeAdapter:
    """Raw-source adapter used to compare rich editor adoption boundaries."""

    autosave_enabled = False
    production_wired = False

    def __init__(self, editor_name: str, *, mdx_jsx_enabled: bool = False) -> None:
        self.editor_name = editor_name
        self.mdx_jsx_enabled = mdx_jsx_enabled
        self._markdown = ""
        self._write_calls: tuple[str, ...] = ()

    @property
    def write_calls(self) -> tuple[str, ...]:
        return self._write_calls

    def getMarkdown(self) -> str:
        return self._markdown

    def setMarkdown(self, markdown: str) -> None:
        self._markdown = str(markdown)

    def result(self) -> RichEditorSpikeResult:
        return RichEditorSpikeResult(
            editor_name=self.editor_name,
            destructive_transformations=(),
            frontmatter_preserved=True,
            obsidian_syntax_preserved=True,
            mdx_jsx_enabled=self.mdx_jsx_enabled,
            mutation_interception=(
                "No production mutation path. Future adoption must intercept all "
                "changes and route governed patches through Panel/Canvas."
            ),
            recommendation="defer",
        )


def milkdown_spike_adapter() -> RichEditorSourceModeSpikeAdapter:
    return RichEditorSourceModeSpikeAdapter("Milkdown", mdx_jsx_enabled=False)


def mdxeditor_spike_adapter() -> RichEditorSourceModeSpikeAdapter:
    return RichEditorSourceModeSpikeAdapter("MDXEditor", mdx_jsx_enabled=False)
