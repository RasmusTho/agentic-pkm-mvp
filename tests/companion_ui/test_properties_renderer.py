"""Read-only PropertiesRenderer coverage for Companion UI frontmatter (#1302)."""

from __future__ import annotations

from pathlib import Path

from companion_ui.renderer import (
    PropertiesRenderer,
    RenderedProperties,
    RenderedVaultMarkdown,
    render_vault_markdown,
)


FIXTURE_DIR = (
    Path(__file__).resolve().parents[2]
    / "companion-ui"
    / "companion-app"
    / "tests"
    / "fixtures"
    / "obsidian-renderer"
)


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def _render_properties(raw_markdown: str) -> tuple[RenderedVaultMarkdown, RenderedProperties]:
    rendered = render_vault_markdown(raw_markdown, note_path="Notes/current.md")
    properties = PropertiesRenderer().render(rendered.document)
    return rendered, properties


def test_frontmatter_display() -> None:
    _rendered, properties = _render_properties(_fixture("frontmatter-properties.md"))

    assert 'class="vault-properties"' in properties.html
    assert 'data-frontmatter-present="true"' in properties.html
    assert 'data-frontmatter-valid="true"' in properties.html
    assert 'data-readonly="true"' in properties.html
    assert 'data-property-key="title"' in properties.html
    assert "Frontmatter Fixture" in properties.html
    assert 'data-property-key="custom_field"' in properties.html
    assert "some value" in properties.html
    assert "<textarea" not in properties.html
    assert "<button" not in properties.html


def test_body_excludes_frontmatter() -> None:
    rendered, _properties = _render_properties(_fixture("frontmatter-properties.md"))

    assert "Body text that must NOT include" in rendered.html
    assert "title: Frontmatter Fixture" not in rendered.html
    assert "custom_field" not in rendered.html
    assert "aliases:" not in rendered.html
    assert "tags: [alpha, beta, gamma]" not in rendered.html


def test_tags_display() -> None:
    _rendered, properties = _render_properties(
        "---\n"
        "tags:\n"
        "  - companion-ui\n"
        "  - renderer\n"
        "---\n"
        "\n"
        "Body.\n"
    )

    assert 'data-property-key="tags"' in properties.html
    assert 'data-property-type="tags"' in properties.html
    assert properties.html.count('class="vault-property-tag"') == 2
    assert "companion-ui" in properties.html
    assert "renderer" in properties.html


def test_aliases_display() -> None:
    _rendered, properties = _render_properties(_fixture("frontmatter-properties.md"))

    assert 'data-property-key="aliases"' in properties.html
    assert 'data-property-type="aliases"' in properties.html
    assert "Alt Name" in properties.html
    assert "Another Alias" in properties.html
    assert 'class="vault-property-value"' in properties.html


def test_malformed_frontmatter_diagnostic() -> None:
    rendered, properties = _render_properties(_fixture("malformed-frontmatter.md"))

    assert 'data-frontmatter-valid="false"' in properties.html
    assert 'data-diagnostic-code="frontmatter_parse_error"' in properties.html
    assert "Frontmatter could not be parsed as simple YAML." in properties.html
    assert "Body text should still be returned" in rendered.html
    assert '<h2 id="recoverable-body-section">Recoverable Body Section</h2>' in rendered.html


def test_no_write_calls() -> None:
    _rendered, properties = _render_properties(_fixture("frontmatter-properties.md"))

    assert properties.write_calls == ()
    assert "POST" not in properties.html
    assert "PUT" not in properties.html
    assert "PATCH" not in properties.html
    assert "DELETE" not in properties.html

    source = (
        Path(__file__).resolve().parents[2]
        / "companion-ui"
        / "companion-app"
        / "companion_ui"
        / "renderer"
        / "properties_renderer.py"
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


def test_frontmatter_fixture() -> None:
    for fixture_name in ("frontmatter-properties.md", "malformed-frontmatter.md"):
        rendered, properties = _render_properties(_fixture(fixture_name))

        assert rendered.html
        assert properties.html
        assert properties.write_calls == ()


def test_properties_disclosure_has_no_readonly_badge() -> None:
    """#2526 AC1 — the properties disclosure renders no `read-only` badge.

    The note body is always directly editable (the misleading note-body
    read-only pill was removed in #1447). The per-note properties-disclosure
    badge claimed read-only unconditionally next to a working Edit button; it
    is a false trust signal and is removed. The inert `data-readonly="true"`
    projection attribute (a machine attribute, not a human-visible badge) is
    retained.
    """
    from tests.companion_ui._visible_text import visible_text

    # Valid frontmatter path and malformed-diagnostic path both render the
    # properties header; neither must carry the visible badge.
    for fixture_name in ("frontmatter-properties.md", "malformed-frontmatter.md"):
        _rendered, properties = _render_properties(_fixture(fixture_name))

        # The badge markup is gone entirely (class + visible value).
        assert 'class="vault-properties-mode"' not in properties.html
        assert ">read-only</span>" not in properties.html
        assert "read-only" not in visible_text(properties.html)

        # The inert projection attribute is preserved (not a visible badge).
        assert 'data-readonly="true"' in properties.html
