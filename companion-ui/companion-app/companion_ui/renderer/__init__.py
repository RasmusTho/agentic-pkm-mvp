"""Renderer-safe Markdown parsing models for Companion UI."""

from companion_ui.renderer.models import (
    AssetRef,
    AssetResolution,
    BlockIdRef,
    EmbedRef,
    HeadingRef,
    LinkResolution,
    MarkdownDiagnostic,
    ObsidianCommentRef,
    SourceRange,
    VaultMarkdownDocument,
    WikiLinkRef,
)
from companion_ui.renderer.vault_markdown_parser import parse_vault_markdown
from companion_ui.renderer.note_outline import (
    note_outline_css,
    note_outline_script,
    render_note_outline,
)
from companion_ui.renderer.vault_markdown_renderer import (
    RenderedVaultMarkdown,
    VaultMarkdownRenderer,
    render_vault_markdown,
)

__all__ = [
    "AssetRef",
    "AssetResolution",
    "BlockIdRef",
    "EmbedRef",
    "HeadingRef",
    "LinkResolution",
    "MarkdownDiagnostic",
    "ObsidianCommentRef",
    "SourceRange",
    "VaultMarkdownDocument",
    "WikiLinkRef",
    "parse_vault_markdown",
    "note_outline_css",
    "note_outline_script",
    "render_note_outline",
    "RenderedVaultMarkdown",
    "VaultMarkdownRenderer",
    "render_vault_markdown",
]
