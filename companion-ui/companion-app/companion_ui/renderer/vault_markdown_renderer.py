"""Server-side Vault Markdown renderer for the Companion UI note surface.

The renderer is deliberately read-only. It consumes parser output plus injected
link/asset resolvers, returns sanitized HTML, and never reads vault files or
calls write endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass
import html
from html.parser import HTMLParser
import re
from typing import Protocol
from urllib.parse import quote

from companion_ui.renderer.asset_resolver import VaultAssetResolver
from companion_ui.renderer.callout_renderer import (
    CALLOUT_HEADER_RE,
    ObsidianCalloutRenderer,
)
from companion_ui.renderer.link_resolver import (
    VaultLinkResolver,
    link_display_label,
    parse_wikilink,
)
from companion_ui.renderer.mermaid_renderer import MermaidBlockRenderer
from companion_ui.renderer.models import (
    MarkdownDiagnostic,
    VaultMarkdownDocument,
)
from companion_ui.renderer.vault_markdown_parser import parse_vault_markdown


_TOKEN_RE = re.compile(r"(`[^`\n]+`|!\[[^\]\n]*\]\([^) \n][^)\n]*\)|!\[\[[^\]\n]+?\]\]|\[\[[^\]\n]+?\]\])")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})\s*([A-Za-z0-9_-]+)?\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$")
_EXPLICIT_ANCHOR_RE = re.compile(r"\s*\{#([A-Za-z0-9_-]+)\}\s*$")
_TASK_RE = re.compile(r"^\s*[-*+]\s+\[([^\]])\]\s+(.*)$")
_UNORDERED_RE = re.compile(r"^\s*[-*+]\s+(.*)$")
_ORDERED_RE = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_CALLOUT_RE = CALLOUT_HEADER_RE
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
_COMMENT_RE = re.compile(r"%%.*?%%", re.DOTALL)
_DIAGNOSTIC_ONLY_LANGUAGES = {"dataview", "dataviewjs", "query"}
_BLOCKED_SRC_SCHEMES = ("file:", "javascript:", "data:")
_ABSOLUTE_PATH_RE = re.compile(r"^(?:/|[A-Za-z]:[\\/])")
_WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
_LOCAL_PATH_PREFIXES = (
    "/Users/",
    "/home/",
    "/private/",
    "/tmp/",
    "/var/",
    "/Volumes/",
)
_CALLOUT_RENDERER = ObsidianCalloutRenderer()


class LinkResolverProtocol(Protocol):
    def resolve(self, *args: object, **kwargs: object) -> object:
        ...


class AssetResolverProtocol(Protocol):
    def resolve(self, *args: object, **kwargs: object) -> object:
        ...


class LinkPreviewProtocol(Protocol):
    def render(self, resolution: object, *, note_path: str = "", depth: int = 0) -> object:
        ...


class _RawHtmlStripper(HTMLParser):
    """Strip raw HTML tags and suppress script/style contents."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._suppressed_tag_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        _ = attrs
        if tag.lower() in {"script", "style"}:
            self._suppressed_tag_stack.append(tag.lower())

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style"} and lowered in self._suppressed_tag_stack:
            self._suppressed_tag_stack.remove(lowered)

    def handle_data(self, data: str) -> None:
        if not self._suppressed_tag_stack:
            self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self._suppressed_tag_stack:
            self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self._suppressed_tag_stack:
            self.parts.append(f"&#{name};")

    def text(self) -> str:
        return "".join(self.parts)


@dataclass(frozen=True)
class RenderedVaultMarkdown:
    """Browser-safe render result for one vault Markdown document."""

    html: str
    document: VaultMarkdownDocument
    diagnostics: tuple[MarkdownDiagnostic, ...]
    write_calls: tuple[str, ...] = ()


@dataclass
class _RenderContext:
    note_path: str
    link_resolver: LinkResolverProtocol
    asset_resolver: AssetResolverProtocol
    mermaid_renderer: MermaidBlockRenderer
    link_preview: LinkPreviewProtocol | None
    preview_depth: int
    diagnostics: list[MarkdownDiagnostic]
    preview_counter: int = 0


class VaultMarkdownRenderer:
    """Render parsed vault Markdown to sanitized, read-only HTML."""

    def __init__(
        self,
        *,
        link_resolver: LinkResolverProtocol | None = None,
        asset_resolver: AssetResolverProtocol | None = None,
        mermaid_renderer: MermaidBlockRenderer | None = None,
        link_preview: LinkPreviewProtocol | None = None,
    ) -> None:
        self._link_resolver = link_resolver or VaultLinkResolver({})
        self._asset_resolver = asset_resolver or VaultAssetResolver({})
        self._mermaid_renderer = mermaid_renderer or MermaidBlockRenderer()
        self._link_preview = link_preview

    def render(
        self,
        document: VaultMarkdownDocument | str,
        *,
        note_path: str = "",
        preview_depth: int = 0,
    ) -> RenderedVaultMarkdown:
        parsed = parse_vault_markdown(document) if isinstance(document, str) else document
        diagnostics = list(parsed.diagnostics)
        context = _RenderContext(
            note_path=_safe_note_path(note_path),
            link_resolver=self._link_resolver,
            asset_resolver=self._asset_resolver,
            mermaid_renderer=self._mermaid_renderer,
            link_preview=self._link_preview,
            preview_depth=max(0, int(preview_depth)),
            diagnostics=diagnostics,
        )
        body_markdown = _strip_obsidian_comments(parsed.body_markdown)
        body_html = _render_blocks(body_markdown, context)
        diagnostics_html = _render_diagnostics(diagnostics)
        rendered_html = (
            '<article class="vault-markdown-rendered" data-renderer="vault-markdown">'
            f"{diagnostics_html}{body_html}"
            "</article>"
        )
        return RenderedVaultMarkdown(
            html=rendered_html,
            document=parsed,
            diagnostics=tuple(diagnostics),
        )


def render_vault_markdown(
    raw_markdown: VaultMarkdownDocument | str,
    *,
    note_path: str = "",
    link_resolver: LinkResolverProtocol | None = None,
    asset_resolver: AssetResolverProtocol | None = None,
    mermaid_renderer: MermaidBlockRenderer | None = None,
    link_preview: LinkPreviewProtocol | None = None,
) -> RenderedVaultMarkdown:
    """Convenience wrapper for one-shot rendering."""

    return VaultMarkdownRenderer(
        link_resolver=link_resolver,
        asset_resolver=asset_resolver,
        mermaid_renderer=mermaid_renderer,
        link_preview=link_preview,
    ).render(raw_markdown, note_path=note_path)


def _render_blocks(markdown: str, context: _RenderContext) -> str:
    lines = markdown.splitlines()
    parts: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue

        fence = _FENCE_RE.match(line)
        if fence:
            html_block, index = _render_fenced_code(lines, index, fence, context)
            parts.append(html_block)
            continue

        if _CALLOUT_RE.match(line):
            html_block, index = _render_callout(lines, index, context)
            parts.append(html_block)
            continue

        if line.lstrip().startswith(">"):
            html_block, index = _render_blockquote(lines, index, context)
            parts.append(html_block)
            continue

        if _is_table_start(lines, index):
            html_block, index = _render_table(lines, index, context)
            parts.append(html_block)
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            parts.append(_render_heading(heading, context))
            index += 1
            continue

        if _is_thematic_break(line):
            parts.append("<hr>")
            index += 1
            continue

        if _list_kind(line) is not None:
            html_block, index = _render_list_block(lines, index, context)
            parts.append(html_block)
            continue

        html_block, index = _render_paragraph(lines, index, context)
        parts.append(html_block)

    return "".join(parts)


def _next_nonblank_index(lines: list[str], start: int) -> int | None:
    index = start
    while index < len(lines):
        if lines[index].strip():
            return index
        index += 1
    return None


def _render_fenced_code(
    lines: list[str],
    start: int,
    fence: re.Match[str],
    context: _RenderContext,
) -> tuple[str, int]:
    marker = fence.group(1)
    language = (fence.group(2) or "").lower()
    code_lines: list[str] = []
    index = start + 1
    while index < len(lines):
        close = _FENCE_RE.match(lines[index])
        if close and close.group(1).startswith(marker[0]) and len(close.group(1)) >= len(marker):
            index += 1
            break
        code_lines.append(lines[index])
        index += 1

    code = "\n".join(code_lines)
    if language == "mermaid":
        rendered_mermaid = context.mermaid_renderer.render(code)
        context.diagnostics.extend(rendered_mermaid.diagnostics)
        return rendered_mermaid.html, index

    if language in _DIAGNOSTIC_ONLY_LANGUAGES:
        context.diagnostics.append(
            MarkdownDiagnostic(
                severity="info",
                code="unsupported_plugin_block",
                message=f"Fenced {language} block is diagnostic-only and was not executed.",
            )
        )
        return (
            _render_unsupported_diagnostic(
                code="unsupported_plugin_block",
                message=f"{language} block not executed.",
            )
            + _render_code_block(code, language),
            index,
        )
    return _render_code_block(code, language), index


def _render_code_block(code: str, language: str) -> str:
    language_attr = f' data-language="{_e(language)}"' if language else ""
    class_attr = f' class="language-{_e(language)}"' if language else ""
    return (
        f"<pre class=\"vault-code-block\"{language_attr}>"
        f"<code{class_attr}>{_e(code)}</code>"
        "</pre>"
    )


def _render_callout(
    lines: list[str],
    start: int,
    context: _RenderContext,
) -> tuple[str, int]:
    return _CALLOUT_RENDERER.render_from_lines(
        lines,
        start,
        render_body=lambda body_markdown: _render_blocks(body_markdown, context),
        render_title=lambda title: _render_inline(title, context),
    )


def _render_blockquote(
    lines: list[str],
    start: int,
    context: _RenderContext,
) -> tuple[str, int]:
    quote_lines: list[str] = []
    index = start
    while index < len(lines) and lines[index].lstrip().startswith(">"):
        quote_lines.append(lines[index].lstrip()[1:].lstrip())
        index += 1
    content = "<br>".join(_render_inline(line, context) for line in quote_lines)
    return f"<blockquote>{content}</blockquote>", index


def _render_table(
    lines: list[str],
    start: int,
    context: _RenderContext,
) -> tuple[str, int]:
    table_lines: list[str] = []
    expected_columns = len(_split_table_row(lines[start]))
    index = start
    while index < len(lines):
        if not lines[index].strip():
            next_index = _next_nonblank_index(lines, index + 1)
            if next_index is None or not _is_table_row(
                lines[next_index],
                expected_columns=expected_columns,
                require_outer_pipes=True,
            ):
                break
            index = next_index
            continue
        if not _is_table_row(lines[index], expected_columns=expected_columns):
            break
        table_lines.append(lines[index])
        index += 1

    rows = [_split_table_row(line) for line in table_lines]
    header = rows[0]
    body_rows = rows[2:]
    head_html = "".join(f"<th>{_render_inline(cell, context)}</th>" for cell in header)
    body_html = "".join(
        "<tr>" + "".join(f"<td>{_render_inline(cell, context)}</td>" for cell in row) + "</tr>"
        for row in body_rows
    )
    return f"<table><thead><tr>{head_html}</tr></thead><tbody>{body_html}</tbody></table>", index


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [cell.strip() for cell in stripped.split("|")]


def _is_table_row(
    line: str,
    *,
    expected_columns: int,
    require_outer_pipes: bool = False,
) -> bool:
    stripped = line.strip()
    if "|" not in stripped:
        return False
    if require_outer_pipes and not (stripped.startswith("|") and stripped.endswith("|")):
        return False
    return len(_split_table_row(stripped)) == expected_columns


def _render_heading(match: re.Match[str], context: _RenderContext) -> str:
    level = len(match.group(1))
    text, anchor = _heading_text_and_anchor(match.group(2))
    return f'<h{level} id="{_e(anchor)}">{_render_inline(text, context)}</h{level}>'


def _slugify_anchor(text: str) -> str:
    """Slug used for heading element ids and heading-fragment link hrefs.

    Both sides must agree so that ``[[Note#Heading]]`` navigates to the rendered
    ``<h_ id="...">`` (#1345).
    """
    slug = re.sub(r"-+", "-", "".join(char if char.isalnum() else "-" for char in text.lower()))
    return slug.strip("-")


def _heading_text_and_anchor(raw_text: str) -> tuple[str, str]:
    text = raw_text.strip()
    explicit_anchor = _EXPLICIT_ANCHOR_RE.search(text)
    if explicit_anchor:
        text = text[: explicit_anchor.start()].strip()
        return text, explicit_anchor.group(1)
    text = text.strip(" #\t")
    return text, _slugify_anchor(text)


def _list_kind(line: str) -> str | None:
    """Classify a line as a list item: 'task', 'ol', 'ul', or None.

    Task items (``- [ ]``) are a special case of unordered items and must be
    checked first.
    """
    if _TASK_RE.match(line):
        return "task"
    if _ORDERED_RE.match(line):
        return "ol"
    if _UNORDERED_RE.match(line):
        return "ul"
    return None


def _list_indent(line: str) -> int:
    expanded = line.expandtabs(4)
    return len(expanded) - len(expanded.lstrip(" "))


def _render_list_block(
    lines: list[str],
    start: int,
    context: _RenderContext,
) -> tuple[str, int]:
    """Render a (possibly nested) list block, indentation-aware (#1410).

    Collects consecutive list lines and rebuilds the nesting from their indent
    so nested ordered lists render inside a nested ``<ol>`` (restarting at 1)
    rather than as flattened continuation items.
    """
    entries: list[tuple[int, str, str | None, str]] = []
    index = start
    base_indent = _list_indent(lines[start])
    base_kind = _list_kind(lines[start])
    while index < len(lines):
        if not lines[index].strip():
            next_index = _next_nonblank_index(lines, index + 1)
            next_kind = _list_kind(lines[next_index]) if next_index is not None else None
            if next_index is None or next_kind is None:
                break
            if _list_indent(lines[next_index]) == base_indent and next_kind != base_kind:
                break
            index = next_index
            continue
        kind = _list_kind(lines[index])
        if kind is None:
            break
        indent = _list_indent(lines[index])
        if kind == "task":
            match = _TASK_RE.match(lines[index])
            assert match is not None
            entries.append((indent, "task", match.group(1).strip() or " ", match.group(2)))
        elif kind == "ol":
            match = _ORDERED_RE.match(lines[index])
            assert match is not None
            entries.append((indent, "ol", None, match.group(1)))
        else:
            match = _UNORDERED_RE.match(lines[index])
            assert match is not None
            entries.append((indent, "ul", None, match.group(1)))
        index += 1

    html, _ = _build_list_html(entries, 0, entries[0][0], context)
    return html, index


def _build_list_html(
    entries: list[tuple[int, str, str | None, str]],
    pos: int,
    indent: int,
    context: _RenderContext,
) -> tuple[str, int]:
    list_kind = entries[pos][1]
    items: list[str] = []
    while pos < len(entries) and entries[pos][0] >= indent:
        e_indent, e_kind, e_state, e_content = entries[pos]
        if e_indent > indent:
            # Deeper than expected without a parent item at this level — attach
            # the nested list to the previous item (or open a bare item).
            nested_html, pos = _build_list_html(entries, pos, e_indent, context)
            if items:
                items[-1] = items[-1][: -len("</li>")] + nested_html + "</li>"
            else:
                items.append(f"<li>{nested_html}</li>")
            continue
        pos += 1
        nested_html = ""
        if pos < len(entries) and entries[pos][0] > indent:
            nested_html, pos = _build_list_html(entries, pos, entries[pos][0], context)
        if e_kind == "task":
            checked_attr = " checked" if (e_state or "").lower() == "x" else ""
            items.append(
                '<li class="task-list-item" '
                f'data-task-state="{_e(e_state or " ")}">'
                f'<input type="checkbox" disabled{checked_attr}> '
                f"{_render_inline(e_content, context)}{nested_html}</li>"
            )
        else:
            items.append(f"<li>{_render_inline(e_content, context)}{nested_html}</li>")

    tag = "ol" if list_kind == "ol" else "ul"
    cls = ' class="task-list"' if list_kind == "task" else ""
    return f"<{tag}{cls}>{''.join(items)}</{tag}>", pos


def _render_paragraph(
    lines: list[str],
    start: int,
    context: _RenderContext,
) -> tuple[str, int]:
    paragraph_lines: list[str] = []
    index = start
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            break
        if paragraph_lines and _is_block_start(lines, index):
            break
        paragraph_lines.append(line.strip())
        index += 1
    text = " ".join(paragraph_lines)
    return f"<p>{_render_inline(text, context)}</p>", index


def _render_inline(text: str, context: _RenderContext) -> str:
    parts: list[str] = []
    cursor = 0
    for match in _TOKEN_RE.finditer(text):
        if match.start() > cursor:
            parts.append(_render_text_segment(text[cursor : match.start()]))
        token = match.group(0)
        if token.startswith("`") and token.endswith("`"):
            parts.append(f"<code>{_e(token[1:-1])}</code>")
        elif token.startswith("![["):
            parts.append(_render_obsidian_embed(token, context))
        elif token.startswith("!["):
            parts.append(_render_markdown_image(token, context))
        elif token.startswith("[["):
            parts.append(_render_wikilink(token, context))
        cursor = match.end()
    if cursor < len(text):
        parts.append(_render_text_segment(text[cursor:]))
    return "".join(parts)


def _render_text_segment(text: str) -> str:
    clean = _strip_raw_html(text)
    escaped = _e(clean)
    escaped = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", escaped)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", escaped)
    escaped = re.sub(r"~~(.+?)~~", r"<del>\1</del>", escaped)
    return escaped


def _render_wikilink(raw: str, context: _RenderContext) -> str:
    try:
        link = parse_wikilink(raw)
        resolution = context.link_resolver.resolve(link, note_path=context.note_path)
    except Exception as exc:  # Resolver contract says never throw; guard third-party stubs.
        return _render_unresolved_link_partial(raw, "missing", title_raw=raw, reason=str(exc))

    kind = str(getattr(resolution, "kind", "missing"))
    label = link_display_label(resolution) if kind in {"resolved", "missing", "ambiguous"} else raw
    if kind != "resolved":
        trigger_html = _render_unresolved_link_partial(
            label,
            kind,
            title_raw=raw,
            reason=getattr(resolution, "reason", None),
        )
        return _wrap_link_preview(trigger_html, resolution, context)

    note_path = _safe_note_path(str(getattr(resolution, "note_path", "") or ""))
    if not note_path:
        return _render_unresolved_link_partial(
            label,
            "missing",
            title_raw=raw,
            reason="Resolved note path was not browser-safe.",
        )

    href = f"?note_path={quote(note_path, safe='')}"
    fragment = _resolution_fragment(resolution)
    if fragment:
        # Keep ``^`` literal so block-id links read as ``#^block-id`` (#1345 AC4).
        href = f"{href}#{quote(fragment, safe='^')}"
    trigger_html = (
        '<a class="vault-wikilink" '
        'data-link-state="resolved" '
        f'data-note-path="{_e(note_path)}" '
        f'href="{_e(href)}">{_e(str(getattr(resolution, "display_text", label)))}</a>'
    )
    return _wrap_link_preview(trigger_html, resolution, context)


def _wrap_link_preview(trigger_html: str, resolution: object, context: _RenderContext) -> str:
    if context.link_preview is None:
        return trigger_html

    context.preview_counter += 1
    preview_id = (
        f"link-preview-{context.preview_counter}"
        if context.preview_depth == 0
        else f"link-preview-{context.preview_depth + 1}-{context.preview_counter}"
    )
    try:
        preview = context.link_preview.render(
            resolution,
            note_path=context.note_path,
            depth=context.preview_depth,
        )
        preview_html = str(getattr(preview, "html", "") or "")
    except Exception as exc:  # Preview must never crash the note surface.
        preview_html = _render_link_preview_exception(str(exc))

    if not preview_html:
        return trigger_html
    return (
        '<span class="vault-link-preview-host" '
        'data-testid="link-preview" '
        f'data-preview-depth="{context.preview_depth}" '
        'tabindex="0" '
        f'aria-describedby="{_e(preview_id)}">'
        f"{trigger_html}"
        f'<span id="{_e(preview_id)}" class="link-preview-popover" role="tooltip">'
        f"{preview_html}</span>"
        "</span>"
    )


def _render_link_preview_exception(message: str) -> str:
    return (
        '<section class="link-preview-card link-preview-diagnostic" '
        'data-preview-state="missing" data-readonly="true">'
        '<div class="link-preview-title">Preview unavailable</div>'
        f'<div class="link-preview-message">{_e(message)}</div>'
        "</section>"
    )


def _render_unresolved_link_partial(
    label: str,
    kind: str,
    *,
    title_raw: str,
    reason: str | None,
) -> str:
    missing_title = f"{title_raw} \u2014 not found in vault"
    title = missing_title if kind == "missing" else (reason or missing_title)
    return (
        '<span class="vault-wikilink vault-wikilink-diagnostic" '
        f'data-link-state="{_e(kind)}" '
        f'title="{_e(title)}">'
        f"{_e(label)}</span>"
    )


def _resolution_fragment(resolution: object) -> str:
    block_id = getattr(resolution, "block_id", None)
    if block_id:
        return f"^{block_id}"
    heading = getattr(resolution, "heading", None)
    if heading:
        # Match the slugified heading element id so the link scrolls to it.
        return _slugify_anchor(str(heading))
    return ""


def _render_obsidian_embed(raw: str, context: _RenderContext) -> str:
    return _render_asset(raw, context, kind="obsidian-embed", alt=None)


def _render_markdown_image(raw: str, context: _RenderContext) -> str:
    match = re.match(r"!\[([^\]\n]*)\]\(([^)\n]+)\)", raw)
    if not match:
        return _e(raw)
    return _render_asset(match.group(2).strip(), context, kind="markdown-image", alt=match.group(1))


def _render_asset(
    raw_target: str,
    context: _RenderContext,
    *,
    kind: str,
    alt: str | None,
) -> str:
    try:
        resolution = context.asset_resolver.resolve(
            {
                "notePath": context.note_path,
                "rawTarget": raw_target,
                "kind": kind,
            }
        )
    except Exception as exc:  # Resolver contract says never throw; guard third-party stubs.
        return _render_missing_image_partial(
            display_name=raw_target,
            target=raw_target,
            state="missing",
            reason=str(exc),
            alt=alt,
        )

    state = str(getattr(resolution, "kind", "missing"))
    display_name = str(
        getattr(resolution, "display_name", None)
        or getattr(resolution, "displayName", "")
        or raw_target
    )
    if state != "allowed":
        reason = str(getattr(resolution, "reason", "") or "")
        if state == "missing":
            return _render_missing_image_partial(
                display_name=display_name,
                target=raw_target,
                state=state,
                reason=reason,
                alt=alt,
            )
        return _render_asset_diagnostic(display_name, state, reason)

    src = str(getattr(resolution, "src", "") or "")
    if not _is_browser_safe_src(src):
        return _render_asset_diagnostic(display_name, "blocked", "Resolved image source was not browser-safe.")

    width = getattr(resolution, "width", None)
    height = getattr(resolution, "height", None)
    width_attr = f' width="{int(width)}"' if isinstance(width, int) else ""
    height_attr = f' height="{int(height)}"' if isinstance(height, int) else ""
    alt_text = alt if alt is not None else display_name
    return (
        '<img class="vault-image" data-asset-state="allowed" '
        f'src="{_e(src)}" alt="{_e(alt_text)}"{width_attr}{height_attr}>'
    )


def _render_missing_image_partial(
    *,
    display_name: str,
    target: str,
    state: str,
    reason: str,
    alt: str | None,
) -> str:
    title_attr = f' title="{_e(reason)}"' if reason else ""
    alt_html = (
        f'<figcaption class="missing-image-alt">{_e(alt)}</figcaption>'
        if alt
        else ""
    )
    return (
        '<figure class="vault-asset-diagnostic missing-image" '
        'data-testid="missing-image" '
        f'data-asset-state="{_e(state)}"{title_attr}>'
        '<div class="missing-image-box">'
        '<span class="missing-image-icon" aria-hidden="true"></span>'
        '<span class="missing-image-caption">'
        f"<code>{_e(display_name)}</code> &mdash; not found at <code>{_e(target)}</code>"
        "</span>"
        "</div>"
        f"{alt_html}"
        "</figure>"
    )


def _render_asset_diagnostic(label: str, state: str, reason: str) -> str:
    reason_attr = f' title="{_e(reason)}"' if reason else ""
    return (
        '<span class="vault-asset-diagnostic" '
        f'data-asset-state="{_e(state)}"{reason_attr}>'
        f"{_e(label)} ({_e(state)} asset)</span>"
    )


def _render_diagnostics(diagnostics: list[MarkdownDiagnostic]) -> str:
    if not diagnostics:
        return ""
    items = "".join(
        '<li class="vault-diagnostic" '
        f'data-diagnostic-code="{_e(diagnostic.code)}" '
        f'data-diagnostic-severity="{_e(diagnostic.severity)}">'
        f"{_e(diagnostic.message)}</li>"
        for diagnostic in diagnostics
    )
    return f'<aside class="vault-diagnostics" aria-label="Markdown diagnostics"><ul>{items}</ul></aside>'


def _render_unsupported_diagnostic(*, code: str, message: str) -> str:
    return (
        '<div class="unsupported-block-diagnostic" '
        f'data-diagnostic-code="{_e(code)}">{_e(message)}</div>'
    )


def _is_table_start(lines: list[str], index: int) -> bool:
    separator_index = _next_nonblank_index(lines, index + 1)
    return bool(
        separator_index is not None
        and "|" in lines[index]
        and bool(_TABLE_SEPARATOR_RE.match(lines[separator_index]))
    )


def _is_thematic_break(line: str) -> bool:
    stripped = line.strip()
    return stripped in {"---", "***", "___"}


def _is_block_start(lines: list[str], index: int) -> bool:
    line = lines[index]
    return bool(
        _FENCE_RE.match(line)
        or _HEADING_RE.match(line)
        or _CALLOUT_RE.match(line)
        or line.lstrip().startswith(">")
        or _TASK_RE.match(line)
        or _UNORDERED_RE.match(line)
        or _ORDERED_RE.match(line)
        or _is_thematic_break(line)
        or _is_table_start(lines, index)
    )


def _strip_obsidian_comments(text: str) -> str:
    return _COMMENT_RE.sub("", text)


def _strip_raw_html(text: str) -> str:
    stripper = _RawHtmlStripper()
    stripper.feed(text)
    stripper.close()
    return stripper.text()


def _safe_note_path(note_path: str) -> str:
    normalized = str(note_path or "").strip().replace("\\", "/").removeprefix("./")
    if not normalized or _ABSOLUTE_PATH_RE.match(normalized):
        return ""
    return normalized


def _is_browser_safe_src(src: str) -> bool:
    normalized = str(src or "").strip()
    lowered = normalized.lower()
    if not normalized or lowered.startswith(_BLOCKED_SRC_SCHEMES):
        return False
    if _WINDOWS_ABSOLUTE_PATH_RE.match(normalized):
        return False
    if normalized.startswith("/") and not normalized.startswith("/api/"):
        return False
    return not normalized.startswith(_LOCAL_PATH_PREFIXES)


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)
