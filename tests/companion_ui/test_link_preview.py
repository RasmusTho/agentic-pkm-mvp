"""Read-only internal-link preview coverage for Companion UI (#1304)."""

from __future__ import annotations

from pathlib import Path

from companion_ui.renderer import LinkPreview, render_vault_markdown
from companion_ui.renderer.link_resolver import VaultLinkResolver


def _resolver() -> VaultLinkResolver:
    return VaultLinkResolver(
        {
            "ExistingNote": "Notes/ExistingNote.md",
            "UnsafeNote": "Notes/UnsafeNote.md",
            "RecursiveNote": "Notes/RecursiveNote.md",
            "AmbiguousNote": ("A/AmbiguousNote.md", "B/AmbiguousNote.md"),
        }
    )


def _preview(*, max_depth: int = 1) -> LinkPreview:
    return LinkPreview(
        {
            "Notes/ExistingNote.md": "# Existing Note\n\nPreview body with **bold** text.",
            "Notes/UnsafeNote.md": "# Unsafe\n\n<script>alert('xss')</script>\n\nSafe text.",
            "Notes/RecursiveNote.md": "# Recursive\n\nNested [[ExistingNote]].",
        },
        link_resolver=_resolver(),
        max_depth=max_depth,
    )


def _render(markdown: str, *, max_depth: int = 1) -> str:
    return render_vault_markdown(
        markdown,
        note_path="Notes/current.md",
        link_resolver=_resolver(),
        link_preview=_preview(max_depth=max_depth),
    ).html


def test_hover_shows_preview() -> None:
    html = _render("See [[ExistingNote]].")

    assert 'data-testid="link-preview"' in html
    assert 'class="link-preview-popover"' in html
    assert 'data-preview-state="resolved"' in html
    assert '<h1 id="existing-note">Existing Note</h1>' in html
    assert "Preview body with <strong>bold</strong> text." in html


def test_preview_read_only() -> None:
    html = _render("See [[ExistingNote]].")

    assert 'data-readonly="true"' in html
    assert "<textarea" not in html
    assert "<button" not in html
    assert "contenteditable" not in html.lower()
    assert "POST" not in html
    assert "PUT" not in html
    assert "PATCH" not in html
    assert "DELETE" not in html


def test_preview_sanitization() -> None:
    html = _render("See [[UnsafeNote]].")
    lowered = html.lower()

    assert 'data-preview-state="resolved"' in html
    assert "Safe text." in html
    assert "<script" not in lowered
    assert "alert(" not in lowered
    assert "javascript:" not in lowered


def test_depth_limit() -> None:
    html = _render("See [[RecursiveNote]].", max_depth=1)

    assert 'data-preview-state="resolved"' in html
    assert 'data-preview-state="depth-limited"' in html
    assert html.count('data-preview-state="resolved"') == 1
    assert "Preview depth limit reached." in html


def test_missing_link_preview() -> None:
    html = _render("Missing [[MissingNote]].")

    assert 'data-link-state="missing"' in html
    assert 'data-preview-state="missing"' in html
    assert "Preview unavailable: missing link." in html


def test_keyboard_accessible() -> None:
    html = _render("See [[ExistingNote]].")

    assert 'tabindex="0"' in html
    assert 'aria-describedby="link-preview-1"' in html
    assert 'id="link-preview-1"' in html
    assert 'role="tooltip"' in html


def test_no_write_calls() -> None:
    rendered = render_vault_markdown(
        "See [[ExistingNote]].",
        note_path="Notes/current.md",
        link_resolver=_resolver(),
        link_preview=_preview(),
    )

    assert rendered.write_calls == ()
    assert rendered.html

    source = (
        Path(__file__).resolve().parents[2]
        / "companion-ui"
        / "companion-app"
        / "companion_ui"
        / "renderer"
        / "link_preview.py"
    ).read_text(encoding="utf-8")
    for forbidden_call in (
        "httpx.",
        "WorkspaceHttpClient",
        "fetch(",
        ".post(",
        ".put(",
        ".patch(",
        ".delete(",
    ):
        assert forbidden_call not in source
