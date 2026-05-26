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
from companion_ui.renderer.properties_renderer import (
    PropertiesRenderer,
    PropertyField,
    RenderedProperties,
    parse_frontmatter_fields,
)
from companion_ui.renderer.mermaid_renderer import (
    MermaidBlockRenderer,
    MermaidRenderError,
    MermaidRenderResult,
)
from companion_ui.renderer.link_preview import (
    LinkPreview,
    RenderedLinkPreview,
    link_preview_css,
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
    "LinkPreview",
    "MarkdownDiagnostic",
    "MermaidBlockRenderer",
    "MermaidRenderError",
    "MermaidRenderResult",
    "ObsidianCommentRef",
    "PropertiesRenderer",
    "PropertyField",
    "RenderedProperties",
    "RenderedLinkPreview",
    "SourceRange",
    "VaultMarkdownDocument",
    "WikiLinkRef",
    "parse_frontmatter_fields",
    "link_preview_css",
    "parse_vault_markdown",
    "note_outline_css",
    "note_outline_script",
    "render_note_outline",
    "RenderedVaultMarkdown",
    "VaultMarkdownRenderer",
    "render_vault_markdown",
]
