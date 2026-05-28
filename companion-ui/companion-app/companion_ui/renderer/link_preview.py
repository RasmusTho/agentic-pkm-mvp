"""Read-only hover/focus previews for internal vault links.

Preview content is supplied by the caller as vault-relative note bodies. This
renderer never reads vault files, never calls HTTP clients, and never exposes
filesystem paths.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import html
import re

from companion_ui.renderer.asset_resolver import VaultAssetResolver
from companion_ui.renderer.link_resolver import VaultLinkResolver
from companion_ui.renderer.mermaid_renderer import MermaidBlockRenderer
from companion_ui.renderer.models import MarkdownDiagnostic


_ABSOLUTE_PATH_RE = re.compile(r"^(?:/|[A-Za-z]:[\\/])")
_DEFAULT_MAX_DEPTH = 1
_DEFAULT_MAX_SOURCE_CHARS = 4_000


@dataclass(frozen=True)
class RenderedLinkPreview:
    """HTML and diagnostics for one internal-link preview popover."""

    html: str
    diagnostics: tuple[MarkdownDiagnostic, ...] = ()
    write_calls: tuple[str, ...] = ()


class LinkPreview:
    """Render bounded, sanitized previews for already-resolved internal links."""

    def __init__(
        self,
        note_sources: Mapping[str, str] | None = None,
        *,
        link_resolver: object | None = None,
        asset_resolver: object | None = None,
        mermaid_renderer: MermaidBlockRenderer | None = None,
        max_depth: int = _DEFAULT_MAX_DEPTH,
        max_source_chars: int = _DEFAULT_MAX_SOURCE_CHARS,
    ) -> None:
        self._note_sources = {
            _safe_note_path(path): body
            for path, body in dict(note_sources or {}).items()
            if _safe_note_path(path)
        }
        self._link_resolver = link_resolver or VaultLinkResolver({})
        self._asset_resolver = asset_resolver or VaultAssetResolver({})
        self._mermaid_renderer = mermaid_renderer or MermaidBlockRenderer()
        self._max_depth = max(0, int(max_depth))
        self._max_source_chars = max(1, int(max_source_chars))

    def render(
        self,
        resolution: object,
        *,
        note_path: str = "",
        depth: int = 0,
    ) -> RenderedLinkPreview:
        """Render one preview without mutating vault or renderer state."""

        _ = note_path
        state = str(getattr(resolution, "kind", "missing") or "missing")
        display_text = str(getattr(resolution, "display_text", "") or "link")

        if depth >= self._max_depth:
            return _diagnostic_preview(
                state="depth-limited",
                title=display_text,
                message="Preview depth limit reached.",
            )

        if state == "missing":
            reason = str(getattr(resolution, "reason", "") or "missing link")
            return _diagnostic_preview(
                state="missing",
                title=display_text,
                message="Preview unavailable: missing link.",
                detail=reason,
            )
        if state == "ambiguous":
            candidates = tuple(
                str(candidate)
                for candidate in getattr(resolution, "candidates", ()) or ()
            )
            return _diagnostic_preview(
                state="ambiguous",
                title=display_text,
                message="Preview unavailable: ambiguous link.",
                detail=", ".join(candidates) if candidates else "Multiple targets match this link.",
            )
        if state != "resolved":
            return _diagnostic_preview(
                state="missing",
                title=display_text,
                message="Preview unavailable: unresolved link.",
            )

        target_path = _safe_note_path(str(getattr(resolution, "note_path", "") or ""))
        if not target_path:
            return _diagnostic_preview(
                state="missing",
                title=display_text,
                message="Preview unavailable: unsafe target path.",
            )

        source = self._note_sources.get(target_path)
        if source is None:
            return _diagnostic_preview(
                state="missing",
                title=display_text,
                message="Preview unavailable: target content was not supplied.",
            )

        diagnostics: list[MarkdownDiagnostic] = []
        if len(source) > self._max_source_chars:
            source = source[: self._max_source_chars]
            diagnostics.append(
                MarkdownDiagnostic(
                    severity="info",
                    code="link_preview_truncated",
                    message="Preview source was truncated to the configured size limit.",
                )
            )

        from companion_ui.renderer.vault_markdown_renderer import VaultMarkdownRenderer

        rendered = VaultMarkdownRenderer(
            link_resolver=self._link_resolver,
            asset_resolver=self._asset_resolver,
            mermaid_renderer=self._mermaid_renderer,
            link_preview=self,
        ).render(source, note_path=target_path, preview_depth=depth + 1)
        diagnostics.extend(rendered.diagnostics)
        diagnostic_html = _preview_diagnostics(diagnostics)
        return RenderedLinkPreview(
            html=(
                '<section class="link-preview-card" '
                'data-preview-state="resolved" '
                'data-readonly="true">'
                f'<div class="link-preview-title">{_e(display_text)}</div>'
                f"{diagnostic_html}{rendered.html}"
                "</section>"
            ),
            diagnostics=tuple(diagnostics),
        )


def link_preview_css() -> str:
    """CSS for CSS-only hover/focus preview popovers."""

    return """
    .vault-link-preview-host {
      display: inline-block;
      position: relative;
    }
    .vault-link-preview-host:focus {
      outline: 2px solid var(--cyan);
      outline-offset: 2px;
    }
    .link-preview-popover {
      background: rgba(7,11,18,0.96);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      box-shadow: 0 18px 48px rgba(0,0,0,0.35);
      color: var(--fg-1);
      display: none;
      font-family: var(--font-ui);
      left: 0;
      max-height: min(420px, 70vh);
      max-width: min(520px, 88vw);
      min-width: 280px;
      overflow: auto;
      padding: 14px;
      position: absolute;
      top: calc(100% + 8px);
      width: max-content;
      z-index: 30;
    }
    .vault-link-preview-host:hover .link-preview-popover,
    .vault-link-preview-host:focus-within .link-preview-popover,
    .vault-link-preview-host:focus .link-preview-popover {
      display: block;
    }
    .link-preview-card {
      display: block;
    }
    .link-preview-title {
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      letter-spacing: 0.08em;
      margin-bottom: 8px;
      text-transform: uppercase;
    }
    .link-preview-diagnostic,
    .link-preview-diagnostics {
      background: rgba(212,168,67,0.12);
      border: 1px solid rgba(212,168,67,0.35);
      border-radius: var(--radius-sm);
      color: var(--accent);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      margin: 0;
      padding: 8px 10px;
    }
    """


def _diagnostic_preview(
    *,
    state: str,
    title: str,
    message: str,
    detail: str = "",
) -> RenderedLinkPreview:
    detail_html = f'<div class="link-preview-detail">{_e(detail)}</div>' if detail else ""
    return RenderedLinkPreview(
        html=(
            '<section class="link-preview-card link-preview-diagnostic" '
            f'data-preview-state="{_e(state)}" '
            'data-readonly="true">'
            f'<div class="link-preview-title">{_e(title)}</div>'
            f'<div class="link-preview-message">{_e(message)}</div>'
            f"{detail_html}"
            "</section>"
        )
    )


def _preview_diagnostics(diagnostics: list[MarkdownDiagnostic]) -> str:
    if not diagnostics:
        return ""
    items = "".join(
        '<li class="link-preview-diagnostic-item" '
        f'data-diagnostic-code="{_e(diagnostic.code)}" '
        f'data-diagnostic-severity="{_e(diagnostic.severity)}">'
        f"{_e(diagnostic.message)}</li>"
        for diagnostic in diagnostics
    )
    return f'<ul class="link-preview-diagnostics">{items}</ul>'


def _safe_note_path(note_path: str) -> str:
    normalized = str(note_path or "").strip().replace("\\", "/").removeprefix("./")
    if not normalized or _ABSOLUTE_PATH_RE.match(normalized):
        return ""
    return normalized


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)
