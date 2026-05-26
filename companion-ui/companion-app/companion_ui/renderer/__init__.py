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
from companion_ui.renderer.vault_markdown_parser import parse_vault_markdown
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
    "PropertiesRenderer",
    "PropertyField",
    "RenderedProperties",
    "SourceRange",
    "VaultMarkdownDocument",
    "WikiLinkRef",
    "parse_frontmatter_fields",
    "parse_vault_markdown",
    "RenderedVaultMarkdown",
    "VaultMarkdownRenderer",
    "render_vault_markdown",
]
