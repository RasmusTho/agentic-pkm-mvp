"""Obsidian callout rendering coverage for the Companion UI note surface."""

from __future__ import annotations

import re
from pathlib import Path

from companion_ui.renderer import render_vault_markdown
from companion_ui.renderer.link_resolver import VaultLinkResolver


FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]
    / "companion-ui"
    / "companion-app"
    / "tests"
    / "fixtures"
    / "obsidian-renderer"
    / "callouts.md"
)


def _fixture() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


def _render_fixture(raw_markdown: str | None = None) -> str:
    rendered = render_vault_markdown(
        _fixture() if raw_markdown is None else raw_markdown,
        note_path="Notes/current.md",
        link_resolver=VaultLinkResolver({"WikiLink": "Notes/WikiLink.md"}),
    )
    assert rendered.write_calls == ()
    return rendered.html


def test_basic_callout() -> None:
    html = _render_fixture()

    assert 'data-callout-type="note"' in html
    assert 'class="vault-callout vault-callout--note vault-callout-source--note"' in html
    assert '<span class="vault-callout-title">Note</span>' in html
    assert "Basic note callout body." in html


def test_callout_allows_blank_spacer_between_header_and_body() -> None:
    html = _render_fixture("> [!note]\n\n> Body stays inside the callout.\n")

    fragment = _callout_fragment(html, "note")
    assert '<div class="vault-callout-body">' in fragment
    assert "Body stays inside the callout." in fragment
    assert "<blockquote>Body stays inside" not in html


def test_custom_title() -> None:
    html = _render_fixture()

    assert 'data-callout-type="warning"' in html
    assert 'data-callout-visual-type="warning"' in html
    assert '<span class="vault-callout-title">Custom Title Here</span>' in html
    assert "Warning with custom title." in html


def test_foldable_collapsed() -> None:
    html = _render_fixture()

    assert re.search(
        r"<details [^>]*data-callout-type=\"tip\"[^>]*data-callout-fold=\"collapsed\"",
        html,
    )
    assert not re.search(
        r"<details [^>]*data-callout-type=\"tip\"[^>]*open",
        html,
    )
    assert "Foldable callout collapsed by default." in html


def test_foldable_expanded() -> None:
    html = _render_fixture()

    assert re.search(
        r"<details [^>]*data-callout-type=\"faq\"[^>]*data-callout-fold=\"expanded\"[^>]*open",
        html,
    )
    assert 'data-callout-visual-type="question"' in html
    assert "Foldable callout expanded by default." in html


def test_title_only() -> None:
    raw_markdown = _fixture().replace(
        "> [!abstract]\n> Title-only callout - no body line",
        "> [!abstract] Title-only callout - no body line",
    )
    html = _render_fixture(raw_markdown)

    assert 'data-callout-type="abstract"' in html
    assert '<span class="vault-callout-title">Title-only callout - no body line</span>' in html
    assert "vault-callout-body" not in _callout_fragment(html, "abstract")


def test_nested_callout() -> None:
    html = _render_fixture()

    assert re.search(
        r'data-callout-type="info".*data-callout-type="note".*'
        r"Nested callout inside outer callout\.",
        html,
        re.DOTALL,
    )


def test_unsupported_type_fallback() -> None:
    html = _render_fixture()

    fragment = _callout_fragment(html, "custom-type")
    assert 'data-callout-type="custom-type"' in fragment
    assert 'data-callout-visual-type="note"' in fragment
    assert 'data-callout-supported="false"' in fragment
    assert "vault-callout--note" in fragment
    assert "Unsupported/custom type should default to note-like treatment." in fragment
    assert "unsupported_callout" not in html


def test_fold_no_mutation() -> None:
    rendered = render_vault_markdown(_fixture(), note_path="Notes/current.md")
    source_paths = [
        Path(__file__).resolve().parents[2]
        / "companion-ui"
        / "companion-app"
        / "companion_ui"
        / "renderer"
        / "callout_renderer.py",
        Path(__file__).resolve().parents[2]
        / "companion-ui"
        / "companion-app"
        / "companion_ui"
        / "renderer"
        / "vault_markdown_renderer.py",
    ]
    source_text = "\n".join(path.read_text(encoding="utf-8") for path in source_paths)

    assert rendered.write_calls == ()
    assert "<details" in rendered.html
    for forbidden in ("fetch(", "httpx.", ".post(", ".put(", ".patch(", ".delete("):
        assert forbidden not in source_text


def test_callouts_fixture() -> None:
    html = _render_fixture()

    assert html
    assert html.count('data-callout-type="') == 8
    assert "<strong>bold</strong>" in html
    assert 'class="vault-wikilink" data-link-state="resolved"' in html
    assert "Notes/WikiLink.md" in html
    assert "unsupported_callout" not in html


def _callout_fragment(html: str, callout_type: str) -> str:
    data_start = html.index(f'data-callout-type="{callout_type}"')
    section_start = html.rfind("<section", 0, data_start)
    details_start = html.rfind("<details", 0, data_start)
    start = max(section_start, details_start)
    next_section = html.find("<section", data_start + 1)
    next_details = html.find("<details", data_start + 1)
    candidates = [index for index in (next_section, next_details) if index != -1]
    end = min(candidates) if candidates else len(html)
    return html[start:end]
