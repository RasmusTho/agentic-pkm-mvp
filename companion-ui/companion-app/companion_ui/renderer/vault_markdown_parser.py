"""Parse vault Markdown into renderer-safe references.

The parser is deliberately read-only and text-only. It preserves the raw source
verbatim, extracts references needed by later renderer/resolver phases, and
does not resolve links, assets, or paths.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator

from companion_ui.renderer.models import (
    AssetRef,
    BlockIdRef,
    EmbedRef,
    HeadingRef,
    MarkdownDiagnostic,
    ObsidianCommentRef,
    SourceRange,
    VaultMarkdownDocument,
    WikiLinkRef,
)


_FENCE_RE = re.compile(r"^\s*(?:>\s*)*(`{3,}|~{3,})\s*([A-Za-z0-9_-]+)?")
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$")
_EXPLICIT_ANCHOR_RE = re.compile(r"\s*\{#([A-Za-z0-9_-]+)\}\s*$")
_BLOCK_ID_RE = re.compile(r"(?<!\S)\^([A-Za-z0-9_-]+)")
_WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\]\r\n]+?)\]\]")
_EMBED_RE = re.compile(r"!\[\[([^\]\r\n]+?)\]\]")
_ASSET_RE = re.compile(r"!\[([^\]\r\n]*)\]\(([^)\r\n]+)\)")
_COMMENT_RE = re.compile(r"%%(.*?)%%", re.DOTALL)

_IMAGE_EXTENSIONS = {"avif", "bmp", "gif", "jpeg", "jpg", "png", "svg", "webp"}
_AUDIO_EXTENSIONS = {"aac", "flac", "m4a", "mp3", "ogg", "wav"}
_VIDEO_EXTENSIONS = {"avi", "m4v", "mkv", "mov", "mp4", "webm"}
_DIAGNOSTIC_ONLY_EMBED_KINDS = {"note", "pdf", "audio", "video", "canvas"}
_DIAGNOSTIC_ONLY_CODE_BLOCKS = {"dataview", "dataviewjs", "query"}


def parse_vault_markdown(raw_markdown: str) -> VaultMarkdownDocument:
    """Parse raw Markdown without mutating it or resolving external targets."""

    frontmatter, body_markdown, body_offset, diagnostics = _split_frontmatter(raw_markdown)
    if frontmatter is not None:
        diagnostics.extend(_validate_frontmatter(frontmatter, raw_markdown))

    non_fenced_spans = list(_iter_non_fenced_spans(body_markdown, body_offset))
    reference_spans = list(_iter_comment_suppressed_spans(non_fenced_spans))
    fenced_diagnostics = _detect_diagnostic_only_code_blocks(body_markdown, body_offset)

    headings = _extract_headings(body_markdown, body_offset)
    block_ids = _extract_block_ids(reference_spans)
    wikilinks = _extract_wikilinks(reference_spans)
    embeds, embed_diagnostics = _extract_embeds(reference_spans)
    asset_refs = _extract_asset_refs(reference_spans)
    comments = _extract_comments(non_fenced_spans)

    return VaultMarkdownDocument(
        raw_markdown=raw_markdown,
        frontmatter=frontmatter,
        body_markdown=body_markdown,
        diagnostics=[*diagnostics, *embed_diagnostics, *fenced_diagnostics],
        headings=headings,
        block_ids=block_ids,
        wikilinks=wikilinks,
        embeds=embeds,
        asset_refs=asset_refs,
        comments=comments,
    )


def _split_frontmatter(
    raw_markdown: str,
) -> tuple[str | None, str, int, list[MarkdownDiagnostic]]:
    lines = raw_markdown.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None, raw_markdown, 0, []

    cursor = len(lines[0])
    for line in lines[1:]:
        if line.strip() == "---":
            closing_end = cursor + len(line)
            frontmatter = raw_markdown[len(lines[0]) : cursor]
            return frontmatter, raw_markdown[closing_end:], closing_end, []
        cursor += len(line)

    diagnostic = MarkdownDiagnostic(
        severity="error",
        code="frontmatter_unterminated",
        message="Opening frontmatter delimiter has no closing delimiter.",
        source_range=SourceRange(0, len(lines[0])),
    )
    return None, raw_markdown, 0, [diagnostic]


def _validate_frontmatter(frontmatter: str, raw_markdown: str) -> list[MarkdownDiagnostic]:
    if not _frontmatter_looks_malformed(frontmatter):
        return []
    start = raw_markdown.find(frontmatter) if frontmatter else 0
    if start < 0:
        start = 0
    return [
        MarkdownDiagnostic(
            severity="warning",
            code="frontmatter_parse_error",
            message="Frontmatter could not be parsed as simple YAML.",
            source_range=SourceRange(start, start + len(frontmatter)),
        )
    ]


def _frontmatter_looks_malformed(frontmatter: str) -> bool:
    stack: list[str] = []
    quote: str | None = None
    bracket_pairs = {"]": "[", "}": "{"}

    for line in frontmatter.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not line.startswith((" ", "\t", "-")) and ":" not in line:
            return True
        for char in line:
            if quote:
                if char == quote:
                    quote = None
                continue
            if char in {"'", '"'}:
                quote = char
            elif char in {"[", "{"}:
                stack.append(char)
            elif char in bracket_pairs:
                if not stack or stack[-1] != bracket_pairs[char]:
                    return True
                stack.pop()

    return bool(stack or quote)


def _iter_non_fenced_spans(body_markdown: str, body_offset: int) -> Iterator[tuple[str, int]]:
    span_parts: list[str] = []
    span_start: int | None = None
    cursor = 0
    in_fence = False
    fence_marker: str | None = None

    for line in body_markdown.splitlines(keepends=True):
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            if not in_fence:
                if span_parts and span_start is not None:
                    yield "".join(span_parts), body_offset + span_start
                span_parts = []
                span_start = None
                in_fence = True
                fence_marker = fence_match.group(1)
            elif _is_closing_fence(fence_marker, fence_match.group(1)):
                in_fence = False
                fence_marker = None
            cursor += len(line)
            continue

        if not in_fence:
            if span_start is None:
                span_start = cursor
            span_parts.append(line)
        cursor += len(line)

    if span_parts and span_start is not None:
        yield "".join(span_parts), body_offset + span_start


def _iter_comment_suppressed_spans(
    spans: Iterable[tuple[str, int]],
) -> Iterator[tuple[str, int]]:
    for text, source_offset in spans:
        cursor = 0
        for match in _COMMENT_RE.finditer(text):
            if match.start() > cursor:
                yield text[cursor : match.start()], source_offset + cursor
            cursor = match.end()
        if cursor < len(text):
            yield text[cursor:], source_offset + cursor


def _is_closing_fence(open_marker: str | None, candidate: str) -> bool:
    if not open_marker:
        return False
    return candidate[0] == open_marker[0] and len(candidate) >= len(open_marker)


def _detect_diagnostic_only_code_blocks(
    body_markdown: str,
    body_offset: int,
) -> list[MarkdownDiagnostic]:
    diagnostics: list[MarkdownDiagnostic] = []
    cursor = 0
    in_fence = False
    fence_marker: str | None = None

    for line in body_markdown.splitlines(keepends=True):
        match = _FENCE_RE.match(line)
        if not match:
            cursor += len(line)
            continue

        marker, language = match.group(1), (match.group(2) or "").lower()
        if not in_fence:
            in_fence = True
            fence_marker = marker
            if language in _DIAGNOSTIC_ONLY_CODE_BLOCKS:
                diagnostics.append(
                    MarkdownDiagnostic(
                        severity="info",
                        code="diagnostic_only_code_block",
                        message=f"Fenced {language} block is parsed for diagnostics only.",
                        source_range=SourceRange(
                            body_offset + cursor,
                            body_offset + cursor + len(line),
                        ),
                    )
                )
        elif _is_closing_fence(fence_marker, marker):
            in_fence = False
            fence_marker = None
        cursor += len(line)

    return diagnostics


def _extract_headings(body_markdown: str, body_offset: int) -> list[HeadingRef]:
    headings: list[HeadingRef] = []
    cursor = 0
    in_fence = False
    fence_marker: str | None = None

    for line in body_markdown.splitlines(keepends=True):
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif _is_closing_fence(fence_marker, marker):
                in_fence = False
                fence_marker = None
            cursor += len(line)
            continue

        if not in_fence:
            line_without_newline = line.rstrip("\r\n")
            match = _HEADING_RE.match(line_without_newline)
            if match:
                level = len(match.group(1))
                text, anchor = _heading_text_and_anchor(match.group(2))
                headings.append(
                    HeadingRef(
                        level=level,
                        text=text,
                        anchor=anchor,
                        source_range=SourceRange(
                            body_offset + cursor,
                            body_offset + cursor + len(line_without_newline),
                        ),
                    )
                )
        cursor += len(line)

    return headings


def _heading_text_and_anchor(raw_text: str) -> tuple[str, str]:
    text = raw_text.strip()
    explicit_anchor = _EXPLICIT_ANCHOR_RE.search(text)
    if explicit_anchor:
        text = _plain_heading_text(text[: explicit_anchor.start()])
        return text, explicit_anchor.group(1)
    text = _plain_heading_text(text)
    return text, _slugify_heading(text)


def _plain_heading_text(text: str) -> str:
    text = text.strip(" #\t")
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _slugify_heading(text: str) -> str:
    lowered = text.lower()
    kept = [char if char.isalnum() else "-" for char in lowered]
    slug = re.sub(r"-+", "-", "".join(kept)).strip("-")
    return slug


def _extract_block_ids(spans: Iterable[tuple[str, int]]) -> list[BlockIdRef]:
    refs: list[BlockIdRef] = []
    for text, source_offset in spans:
        for match in _BLOCK_ID_RE.finditer(text):
            block_id = match.group(1)
            refs.append(
                BlockIdRef(
                    block_id=block_id,
                    anchor=block_id,
                    source_range=SourceRange(
                        source_offset + match.start(),
                        source_offset + match.end(),
                    ),
                )
            )
    return refs


def _extract_wikilinks(spans: Iterable[tuple[str, int]]) -> list[WikiLinkRef]:
    refs: list[WikiLinkRef] = []
    for text, source_offset in spans:
        for match in _WIKILINK_RE.finditer(text):
            raw = match.group(0)
            target_text = match.group(1)
            parsed = _parse_wikilink_target(target_text)
            refs.append(
                WikiLinkRef(
                    raw=raw,
                    target=parsed["target"],
                    alias=parsed["alias"],
                    heading=parsed["heading"],
                    block_id=parsed["block_id"],
                    local_only=parsed["local_only"],
                    source_range=SourceRange(
                        source_offset + match.start(),
                        source_offset + match.end(),
                    ),
                )
            )
    return refs


def _parse_wikilink_target(text: str) -> dict[str, str | bool | None]:
    target_part, alias = _split_once(text, "|")
    target = target_part
    heading: str | None = None
    block_id: str | None = None
    local_only = False

    if target_part.startswith("#^"):
        target = ""
        block_id = target_part[2:]
        local_only = True
    elif target_part.startswith("^"):
        target = ""
        block_id = target_part[1:]
        local_only = True
    elif target_part.startswith("#"):
        target = ""
        heading = target_part[1:]
        local_only = True
    elif "#^" in target_part:
        target, block_id = target_part.split("#^", 1)
    elif "#" in target_part:
        target, heading = target_part.split("#", 1)

    return {
        "target": target.strip(),
        "alias": alias.strip() if alias else None,
        "heading": heading.strip() if heading else None,
        "block_id": block_id.strip() if block_id else None,
        "local_only": local_only,
    }


def _extract_embeds(
    spans: Iterable[tuple[str, int]],
) -> tuple[list[EmbedRef], list[MarkdownDiagnostic]]:
    refs: list[EmbedRef] = []
    diagnostics: list[MarkdownDiagnostic] = []
    for text, source_offset in spans:
        for match in _EMBED_RE.finditer(text):
            raw = match.group(0)
            ref = _parse_embed(
                raw,
                match.group(1),
                source_offset + match.start(),
                source_offset + match.end(),
            )
            refs.append(ref)
            if ref.kind == "unknown":
                diagnostics.append(
                    MarkdownDiagnostic(
                        severity="warning",
                        code="unknown_embed_type",
                        message=f"Embed target has an unsupported type: {ref.target}",
                        source_range=ref.source_range,
                    )
                )
            elif ref.kind in _DIAGNOSTIC_ONLY_EMBED_KINDS:
                diagnostics.append(
                    MarkdownDiagnostic(
                        severity="info",
                        code="diagnostic_only_embed",
                        message=f"{ref.kind} embeds are parsed but not rendered by this parser.",
                        source_range=ref.source_range,
                    )
                )
    return refs, diagnostics


def _parse_embed(raw: str, text: str, start: int, end: int) -> EmbedRef:
    target_with_fragment, size_hint = _split_once(text, "|")
    target, heading, block_id, fragment = _split_embed_fragment(target_with_fragment)
    width, height = _parse_size_hint(size_hint)
    kind = _classify_embed_kind(target)
    return EmbedRef(
        raw=raw,
        target=target.strip(),
        kind=kind,
        width=width,
        height=height,
        heading=heading,
        block_id=block_id,
        fragment=fragment,
        source_range=SourceRange(start, end),
    )


def _split_embed_fragment(target_text: str) -> tuple[str, str | None, str | None, str | None]:
    target = target_text
    heading: str | None = None
    block_id: str | None = None
    fragment: str | None = None

    if "#^" in target_text:
        target, block_id = target_text.split("#^", 1)
    elif "#" in target_text:
        target, fragment = target_text.split("#", 1)
        if not _looks_like_asset_target(target):
            heading = fragment
            fragment = None

    return (
        target.strip(),
        heading.strip() if heading else None,
        block_id.strip() if block_id else None,
        fragment.strip() if fragment else None,
    )


def _parse_size_hint(size_hint: str | None) -> tuple[int | None, int | None]:
    if not size_hint:
        return None, None
    normalized = size_hint.strip().lower()
    if "x" in normalized:
        width_text, height_text = normalized.split("x", 1)
        return _parse_positive_int(width_text), _parse_positive_int(height_text)
    return _parse_positive_int(normalized), None


def _parse_positive_int(text: str) -> int | None:
    try:
        value = int(text.strip())
    except ValueError:
        return None
    return value if value > 0 else None


def _classify_embed_kind(target: str) -> str:
    extension = _target_extension(target)
    if not extension:
        return "note"
    if extension in _IMAGE_EXTENSIONS:
        return "image"
    if extension == "pdf":
        return "pdf"
    if extension in _AUDIO_EXTENSIONS:
        return "audio"
    if extension in _VIDEO_EXTENSIONS:
        return "video"
    if extension == "canvas":
        return "canvas"
    return "unknown"


def _looks_like_asset_target(target: str) -> bool:
    return bool(_target_extension(target))


def _target_extension(target: str) -> str:
    path = target.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    last_segment = path.rsplit("/", 1)[-1]
    if "." not in last_segment:
        return ""
    return last_segment.rsplit(".", 1)[-1].lower()


def _extract_asset_refs(spans: Iterable[tuple[str, int]]) -> list[AssetRef]:
    refs: list[AssetRef] = []
    for text, source_offset in spans:
        for match in _ASSET_RE.finditer(text):
            refs.append(
                AssetRef(
                    raw=match.group(0),
                    alt=match.group(1),
                    target=match.group(2).strip(),
                    source_range=SourceRange(
                        source_offset + match.start(),
                        source_offset + match.end(),
                    ),
                )
            )
    return refs


def _extract_comments(spans: Iterable[tuple[str, int]]) -> list[ObsidianCommentRef]:
    comments: list[ObsidianCommentRef] = []
    for text, source_offset in spans:
        for match in _COMMENT_RE.finditer(text):
            comments.append(
                ObsidianCommentRef(
                    raw=match.group(0),
                    text=match.group(1),
                    suppress_in_reading_view=True,
                    source_range=SourceRange(
                        source_offset + match.start(),
                        source_offset + match.end(),
                    ),
                )
            )
    return comments


def _split_once(text: str, separator: str) -> tuple[str, str | None]:
    if separator not in text:
        return text, None
    left, right = text.split(separator, 1)
    return left, right
