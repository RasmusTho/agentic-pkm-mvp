"""Renderer-safe document model for Obsidian-compatible vault Markdown.

These dataclasses are intentionally inert: they describe parsed source text for
later resolver/renderer phases and do not perform navigation, file access, or
vault writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


DiagnosticSeverity = Literal["info", "warning", "error"]
EmbedKind = Literal["image", "note", "pdf", "audio", "video", "canvas", "unknown"]
LinkResolutionKind = Literal["resolved", "missing", "ambiguous"]
AssetResolutionKind = Literal["allowed", "missing", "blocked", "unsupported"]


@dataclass(frozen=True)
class SourceRange:
    """Character range in the original raw Markdown string."""

    start: int
    end: int


@dataclass(frozen=True)
class MarkdownDiagnostic:
    severity: DiagnosticSeverity
    code: str
    message: str
    source_range: SourceRange | None = None


@dataclass(frozen=True)
class HeadingRef:
    level: int
    text: str
    anchor: str
    source_range: SourceRange | None = None


@dataclass(frozen=True)
class BlockIdRef:
    block_id: str
    anchor: str
    source_range: SourceRange | None = None


@dataclass(frozen=True)
class WikiLinkRef:
    raw: str
    target: str
    alias: str | None = None
    heading: str | None = None
    block_id: str | None = None
    local_only: bool = False
    source_range: SourceRange | None = None


@dataclass(frozen=True)
class EmbedRef:
    raw: str
    target: str
    kind: EmbedKind
    width: int | None = None
    height: int | None = None
    heading: str | None = None
    block_id: str | None = None
    fragment: str | None = None
    source_range: SourceRange | None = None


@dataclass(frozen=True)
class AssetRef:
    raw: str
    target: str
    alt: str | None = None
    source_range: SourceRange | None = None


@dataclass(frozen=True)
class ObsidianCommentRef:
    raw: str
    text: str
    suppress_in_reading_view: bool = True
    source_range: SourceRange | None = None


@dataclass(frozen=True)
class LinkResolution:
    kind: LinkResolutionKind
    display_text: str
    note_path: str | None = None
    heading: str | None = None
    block_id: str | None = None
    reason: str | None = None
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssetResolution:
    kind: AssetResolutionKind
    display_name: str
    src: str | None = None
    width: int | None = None
    height: int | None = None
    reason: str | None = None


@dataclass(frozen=True)
class VaultMarkdownDocument:
    raw_markdown: str
    frontmatter: str | None
    body_markdown: str
    diagnostics: list[MarkdownDiagnostic] = field(default_factory=list)
    headings: list[HeadingRef] = field(default_factory=list)
    block_ids: list[BlockIdRef] = field(default_factory=list)
    wikilinks: list[WikiLinkRef] = field(default_factory=list)
    embeds: list[EmbedRef] = field(default_factory=list)
    asset_refs: list[AssetRef] = field(default_factory=list)
    comments: list[ObsidianCommentRef] = field(default_factory=list)
