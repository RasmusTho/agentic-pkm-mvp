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
    assert 'data-testid="vault-mermaid-diagram"' in rendered.html
    assert 'data-mermaid-state="source-fallback"' in rendered.html
    assert 'data-mermaid-render-mode="source-fallback"' in rendered.html
    assert "graph TD" in rendered.html
    assert not [diagnostic for diagnostic in rendered.diagnostics if diagnostic.severity == "error"]


def test_invalid_diagram_error_ui() -> None:
    rendered = _render_mermaid("this is not valid mermaid syntax @@@")

    assert 'data-testid="vault-mermaid-error"' in rendered.html
    assert 'data-mermaid-state="error"' in rendered.html
    assert 'data-diagnostic-code="invalid_mermaid"' in rendered.html
    assert "this is not valid mermaid syntax @@@" in rendered.html
    assert any(diagnostic.code == "invalid_mermaid" for diagnostic in rendered.diagnostics)


def test_error_boundary() -> None:
    class FailingMermaidRenderer(MermaidBlockRenderer):
        def _render_component(self, source: str) -> str:
            _ = source
            raise RuntimeError("component exploded")

    renderer = FailingMermaidRenderer()
    rendered = renderer.render(MERMAID_SOURCE)

    assert 'data-testid="vault-mermaid-error"' in rendered.html
    assert 'data-mermaid-state="error"' in rendered.html
    assert 'data-diagnostic-code="mermaid_render_error"' in rendered.html
    assert any(diagnostic.code == "mermaid_render_error" for diagnostic in rendered.diagnostics)


def test_source_preserved() -> None:
    source = 'flowchart LR\n    A["<unsafe>"] --> B["done"]'
    rendered = _render_mermaid(source)

    assert 'data-testid="vault-mermaid-source"' in rendered.html
    assert 'data-source-preserved="true"' in rendered.html
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
    assert 'data-testid="vault-mermaid-diagram"' in rendered.html
    assert 'data-diagnostic-code="invalid_mermaid"' in rendered.html
    assert not any(diagnostic.code == "mermaid_render_error" for diagnostic in rendered.diagnostics)
