"""Safe Mermaid fenced-block rendering for the Companion UI note surface.

The server emits a stable, source-preserving placeholder
(``pre.vault-mermaid > code.language-mermaid``) for well-formed Mermaid source
and hands SVG rendering to a sandboxed client runtime on the workspace dev page
(#1344). Source that fails the server-side safety/shape pre-validation degrades
immediately to the #1340 failed-embed partial; the client runtime degrades to
the same partial when Mermaid throws at render time. The server never executes
Mermaid and never fetches network resources.
"""

from __future__ import annotations

from dataclasses import dataclass
import html
import re

from companion_ui.renderer.models import MarkdownDiagnostic


_MERMAID_START_RE = re.compile(
    r"^(?:"
    r"graph(?:\s+(?:TB|TD|BT|RL|LR))?|"
    r"flowchart(?:\s+(?:TB|TD|BT|RL|LR))?|"
    r"sequenceDiagram|"
    r"classDiagram(?:-v2)?|"
    r"stateDiagram(?:-v2)?|"
    r"erDiagram|"
    r"journey|"
    r"gantt|"
    r"pie(?:\s+showData)?|"
    r"mindmap|"
    r"timeline|"
    r"quadrantChart|"
    r"requirementDiagram|"
    r"gitGraph|"
    r"C4Context|C4Container|C4Component|C4Dynamic"
    r")\b",
    re.IGNORECASE,
)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_INLINE_CONFIG_RE = re.compile(r"%%\{\s*(?:init|initialize)\s*:", re.IGNORECASE)
_MERMAID_LINK_RE = re.compile(r"(?im)^\s*(?:click|href)\s+")
_EXTERNAL_TARGET_RE = re.compile(r"(?i)(?:https?:)?//|file:|javascript:|data:")
_UNSAFE_COMPONENT_RE = re.compile(
    r"(?is)"
    r"<\s*(?:script|iframe|object|embed|link|meta|img)\b|"
    r"\son[a-z]+\s*=|"
    r"(?:href|src)\s*=\s*['\"]?\s*(?:https?:|//|file:|javascript:|data:)"
)


@dataclass(frozen=True)
class MermaidRenderResult:
    """HTML plus diagnostics emitted while rendering a Mermaid fenced block."""

    html: str
    diagnostics: tuple[MarkdownDiagnostic, ...] = ()


class MermaidRenderError(RuntimeError):
    """Raised when the controlled Mermaid component fails its safety boundary."""


class MermaidBlockRenderer:
    """Render Mermaid fences without script execution or external resource access."""

    def render(self, source: str) -> MermaidRenderResult:
        """Render Mermaid source into controlled HTML.

        All exceptions from validation or the component boundary are converted
        into diagnostic HTML so the note surface cannot crash.
        """

        normalized_source = _normalize_source(source)
        try:
            invalid_reason = _invalid_mermaid_reason(normalized_source)
            if invalid_reason:
                return _render_error_result(
                    normalized_source,
                    code="invalid_mermaid",
                    message="Mermaid diagram could not be rendered.",
                    detail=invalid_reason,
                )

            component_html = self._render_component(normalized_source)
            if not component_html:
                raise MermaidRenderError("Mermaid component returned no content.")
            if _UNSAFE_COMPONENT_RE.search(component_html):
                raise MermaidRenderError("Mermaid component returned unsafe markup.")

            diagnostics = _link_policy_diagnostics(normalized_source)
            return MermaidRenderResult(
                html=_render_pending_figure(component_html),
                diagnostics=diagnostics,
            )
        except Exception as exc:
            return _render_error_result(
                normalized_source,
                code="mermaid_render_error",
                message="Mermaid rendering failed and was contained.",
                detail=str(exc),
            )

    def _render_component(self, source: str) -> str:
        return _render_mermaid_placeholder(source)


def _normalize_source(source: str) -> str:
    return str(source or "").replace("\r\n", "\n").replace("\r", "\n").strip("\n")


def _invalid_mermaid_reason(source: str) -> str | None:
    if not source.strip():
        return "Mermaid diagram source is empty."
    if _CONTROL_CHAR_RE.search(source):
        return "Mermaid diagram source contains unsupported control characters."
    if _INLINE_CONFIG_RE.search(source):
        return "Inline Mermaid configuration directives are disabled by policy."

    first_line = _first_meaningful_line(source)
    if not first_line or not _MERMAID_START_RE.match(first_line):
        return "Mermaid diagram source does not start with a supported diagram type."
    return None


def _first_meaningful_line(source: str) -> str:
    for line in source.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("%%"):
            continue
        return stripped
    return ""


def _link_policy_diagnostics(source: str) -> tuple[MarkdownDiagnostic, ...]:
    if not (_MERMAID_LINK_RE.search(source) or _EXTERNAL_TARGET_RE.search(source)):
        return ()
    return (
        MarkdownDiagnostic(
            severity="warning",
            code="mermaid_link_policy",
            message=(
                "Mermaid link directives are rendered as inert source and do not "
                "bypass Companion UI link policy."
            ),
        ),
    )


def _render_mermaid_placeholder(source: str) -> str:
    """Stable client-render placeholder carrying the verbatim (escaped) source.

    The client runtime (#1344) selects ``pre.vault-mermaid > code.language-mermaid``,
    reads ``textContent`` as the Mermaid source, and replaces the node with SVG.
    """
    return (
        '<pre class="vault-mermaid" data-testid="vault-mermaid">'
        f'<code class="language-mermaid">{_e(source)}</code>'
        "</pre>"
    )


def _render_error_result(
    source: str,
    *,
    code: str,
    message: str,
    detail: str,
) -> MermaidRenderResult:
    diagnostic = MarkdownDiagnostic(
        severity="error",
        code=code,
        message=f"{message} {detail}".strip(),
    )
    return MermaidRenderResult(
        html=_render_failed_embed_partial(source, code=code),
        diagnostics=(diagnostic,),
    )


def _render_pending_figure(body_html: str) -> str:
    return (
        '<figure class="vault-mermaid-block" '
        'data-testid="vault-mermaid-block" '
        'data-mermaid-state="pending" '
        'data-source-preserved="true" '
        'data-network-policy="blocked">'
        f"{body_html}"
        "</figure>"
    )


def _render_source_details(source: str) -> str:
    return (
        '<details class="vault-mermaid-source" '
        'data-testid="vault-mermaid-source" '
        ">"
        "<summary>view source</summary>"
        '<pre class="vault-code-block vault-mermaid-source-code" data-language="mermaid">'
        f'<code class="language-mermaid">{_e(source)}</code>'
        "</pre>"
        "</details>"
    )


def _render_failed_embed_partial(source: str, *, code: str) -> str:
    return (
        '<figure class="vault-mermaid-block failed-embed failed-embed--mermaid" '
        'data-testid="failed-embed" '
        'data-kind="mermaid" '
        f'data-diagnostic-code="{_e(code)}" '
        'data-embed-state="failed" '
        'data-source-preserved="true" '
        'data-network-policy="blocked">'
        '<div class="failed-embed-main">'
        '<span class="failed-embed-tag">MERMAID</span>'
        '<span class="failed-embed-message">'
        "Diagram source available &mdash; interactive render unavailable in this view."
        "</span>"
        "</div>"
        f"{_render_source_details(source)}"
        "</figure>"
    )


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)
