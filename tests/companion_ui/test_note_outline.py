"""NoteOutline coverage for the Companion UI note surface (#1303)."""

from __future__ import annotations

from pathlib import Path

from companion_ui.renderer import parse_vault_markdown
from companion_ui.renderer.note_outline import (
    note_outline_css,
    note_outline_script,
    render_note_outline,
)
from companion_ui.workspace.serve_dev_page import render_index_html


def _workspace_html(body: str) -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/Outline.md",
        fields={
            "title": "Outline",
            "note_path": "Notes/Outline.md",
            "artifact_id": "artifact-outline",
            "artifact_kind": "human_note",
            "artifact_identity_source": "frontmatter.uuid",
            "artifact_identity_state": "resolved",
            "artifact_companion_of": None,
            "artifact_owns_identity": True,
            "content_hash": "sha256-outline",
            "body": body,
            "panel_rail": "Panel / agent rail placeholder",
            "runtime_environment_label": "dev",
            "runtime_api_base_url_label": "local-dev",
            "runtime_trace_id": "trace-outline",
            "runtime_vault_name": "vault/dev",
            "runtime_vault_channel": "local-dev",
            "runtime_vault_provenance": "resolved",
            "guard_writeguard_status": "ok",
            "guard_canvas_enabled": True,
            "guard_degraded": False,
            "guard_workspace_update_available": False,
            "guard_update_flow_available": False,
        },
    )


def test_headings_extracted() -> None:
    document = parse_vault_markdown(
        "# Alpha\n\n"
        "Body.\n\n"
        "## Beta {#custom-beta}\n\n"
        "### Gamma\n"
    )

    outline = render_note_outline(document)

    assert 'data-testid="note-outline"' in outline
    assert 'data-outline-heading-count="3"' in outline
    assert 'data-heading-level="1"' in outline
    assert 'href="#alpha"' in outline
    assert "Alpha" in outline
    assert 'data-heading-level="2"' in outline
    assert 'href="#custom-beta"' in outline
    assert "Beta" in outline
    assert 'data-heading-level="3"' in outline
    assert 'href="#gamma"' in outline
    assert "Gamma" in outline


def test_heading_navigation() -> None:
    html = _workspace_html("# Alpha\n\nBody.\n\n## Beta\n\nMore body.")

    assert 'data-testid="note-outline-link"' in html
    assert 'href="#beta"' in html
    assert 'data-scroll-target="beta"' in html
    assert '<h2 id="beta">Beta</h2>' in html
    assert 'data-note-outline-script="true"' in html
    assert "scrollIntoView" in html
    assert "focus({ preventScroll: true })" in html
    assert "document.getElementById(targetId)" in html


def test_keyboard_accessible() -> None:
    outline = render_note_outline(parse_vault_markdown("# Alpha\n\n## Beta"))
    script = note_outline_script()

    assert "<nav" in outline
    assert 'aria-label="Note outline"' in outline
    assert '<a class="note-outline-link"' in outline
    assert 'data-note-outline-link="true"' in outline
    assert 'aria-label="Jump to heading: Alpha"' in outline
    assert "event.key !== ' '" in script
    assert "link.click()" in script


def test_portrait_viewport() -> None:
    html = _workspace_html("# Alpha\n\nBody.")
    css = note_outline_css()

    assert 'data-testid="workspace-note-reading-layout"' in html
    assert 'data-layout-desktop="side-panel"' in html
    assert 'data-layout-portrait="inline"' in html
    assert "@media (max-width: 899px)" in css
    assert ".note-reading-layout" in css
    assert "grid-template-columns: minmax(176px, 232px) minmax(0, 1fr);" in css
    assert "flex-direction: column;" in css
    assert "max-height: none;" in css
    assert "overflow: visible;" in css


def test_no_write_calls() -> None:
    outline = render_note_outline(parse_vault_markdown("# Alpha\n\n## Beta"))
    script = note_outline_script()
    module_source = (
        Path(__file__).resolve().parents[2]
        / "companion-ui"
        / "companion-app"
        / "companion_ui"
        / "renderer"
        / "note_outline.py"
    ).read_text(encoding="utf-8")

    forbidden = (
        "WorkspaceHttpClient",
        "fetch(",
        "XMLHttpRequest",
        "httpx.",
        ".post(",
        ".put(",
        ".patch(",
        ".delete(",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
    )
    for token in forbidden:
        assert token not in outline
        assert token not in script
        assert token not in module_source
