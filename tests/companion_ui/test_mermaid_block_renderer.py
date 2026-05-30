"""Mermaid fenced-block rendering coverage for the Companion UI note surface."""

from __future__ import annotations

from pathlib import Path

from companion_ui.renderer import render_vault_markdown
from companion_ui.renderer.mermaid_renderer import MermaidBlockRenderer


FIXTURE_DIR = (
    Path(__file__).resolve().parents[2]
    / "companion-ui"
    / "companion-app"
    / "tests"
    / "fixtures"
    / "obsidian-renderer"
)
MERMAID_SOURCE = """graph TD
    A[Start] --> B{Is it?}
    B -- Yes --> C[OK]
"""


def _render_mermaid(source: str):
    return render_vault_markdown(f"```mermaid\n{source}\n```")


def test_valid_diagram() -> None:
    rendered = _render_mermaid(MERMAID_SOURCE)

    assert 'data-testid="vault-mermaid-block"' in rendered.html
    assert 'data-mermaid-state="pending"' in rendered.html
    assert '<pre class="vault-mermaid"' in rendered.html
    assert '<code class="language-mermaid">' in rendered.html
    assert "graph TD" in rendered.html
    assert "failed-embed" not in rendered.html
    assert not [diagnostic for diagnostic in rendered.diagnostics if diagnostic.severity == "error"]


def test_emits_stable_selector() -> None:
    # #1344 AC1 — a Mermaid fence produces pre.vault-mermaid > code.language-mermaid
    # whose textContent is exactly the (escaped) source.
    source = "sequenceDiagram\n    Alice->>Bob: Hi"
    rendered = _render_mermaid(source)

    assert (
        '<pre class="vault-mermaid" data-testid="vault-mermaid">'
        '<code class="language-mermaid">sequenceDiagram\n    Alice-&gt;&gt;Bob: Hi</code>'
        "</pre>"
    ) in rendered.html


def test_invalid_diagram_uses_failed_embed() -> None:
    # #1344 AC3 (server-side pre-validation branch) — clearly invalid source
    # degrades to the #1340 failed-embed partial, not a parallel error shape.
    rendered = _render_mermaid("this is not valid mermaid syntax @@@")

    assert 'data-testid="failed-embed"' in rendered.html
    assert 'data-kind="mermaid"' in rendered.html
    assert 'data-diagnostic-code="invalid_mermaid"' in rendered.html
    assert "this is not valid mermaid syntax @@@" in rendered.html
    assert "vault-mermaid-error" not in rendered.html
    assert any(diagnostic.code == "invalid_mermaid" for diagnostic in rendered.diagnostics)


def test_error_boundary() -> None:
    class FailingMermaidRenderer(MermaidBlockRenderer):
        def _render_component(self, source: str) -> str:
            _ = source
            raise RuntimeError("component exploded")

    renderer = FailingMermaidRenderer()
    rendered = renderer.render(MERMAID_SOURCE)

    assert 'data-testid="failed-embed"' in rendered.html
    assert 'data-kind="mermaid"' in rendered.html
    assert 'data-diagnostic-code="mermaid_render_error"' in rendered.html
    assert any(diagnostic.code == "mermaid_render_error" for diagnostic in rendered.diagnostics)


def test_source_preserved() -> None:
    source = 'flowchart LR\n    A["<unsafe>"] --> B["done"]'
    rendered = _render_mermaid(source)

    assert 'data-source-preserved="true"' in rendered.html
    assert '<pre class="vault-mermaid"' in rendered.html
    assert "flowchart LR" in rendered.html
    assert "A[&quot;&lt;unsafe&gt;&quot;] --&gt; B" in rendered.html
    assert "<unsafe>" not in rendered.html


def test_no_external_network() -> None:
    source = 'flowchart LR\n    A --> B\n    click A "https://example.com" "external"'
    rendered = _render_mermaid(source)
    module_source = (
        Path(__file__).resolve().parents[2]
        / "companion-ui"
        / "companion-app"
        / "companion_ui"
        / "renderer"
        / "mermaid_renderer.py"
    ).read_text(encoding="utf-8")

    assert "<script" not in rendered.html.lower()
    assert "<a " not in rendered.html.lower()
    assert "href=" not in rendered.html.lower()
    assert "src=" not in rendered.html.lower()
    assert any(diagnostic.code == "mermaid_link_policy" for diagnostic in rendered.diagnostics)
    for forbidden in ("httpx", "requests", "urlopen", "fetch(", "XMLHttpRequest", "subprocess"):
        assert forbidden not in module_source


def test_mermaid_fixture() -> None:
    rendered = render_vault_markdown((FIXTURE_DIR / "mermaid.md").read_text(encoding="utf-8"))

    assert rendered.html
    # The valid fences emit the client-render placeholder...
    assert 'data-testid="vault-mermaid"' in rendered.html
    assert '<pre class="vault-mermaid"' in rendered.html
    # ...and the intentionally-broken fence degrades to the failed-embed partial.
    assert 'data-testid="failed-embed"' in rendered.html
    assert 'data-kind="mermaid"' in rendered.html
    assert 'data-diagnostic-code="invalid_mermaid"' in rendered.html
    assert not any(diagnostic.code == "mermaid_render_error" for diagnostic in rendered.diagnostics)
