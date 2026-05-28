"""Renderer degraded-state coverage for failed embed partials."""

from __future__ import annotations

from companion_ui.renderer import render_vault_markdown


def test_failed_mermaid_renders_dashed_container() -> None:
    rendered = render_vault_markdown(
        "\n".join(
            [
                "```mermaid",
                "this is not a supported mermaid diagram",
                "```",
            ]
        )
    )

    assert 'data-testid="failed-embed"' in rendered.html
    assert "failed-embed--mermaid" in rendered.html
    assert "<details" in rendered.html
    assert "view source" in rendered.html
    assert "this is not a supported mermaid diagram" in rendered.html


def test_body_continues_after_failure() -> None:
    rendered = render_vault_markdown(
        "\n".join(
            [
                "Before the failed embed.",
                "",
                "```mermaid",
                "this is not a supported mermaid diagram",
                "```",
                "",
                "After the failed embed.",
            ]
        )
    )

    assert "<p>Before the failed embed.</p>" in rendered.html
    assert 'data-testid="failed-embed"' in rendered.html
    assert "<p>After the failed embed.</p>" in rendered.html
