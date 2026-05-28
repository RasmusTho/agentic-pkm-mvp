"""Parser-level smoke coverage across the Obsidian compatibility fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from companion_ui.renderer import parse_vault_markdown, render_vault_markdown


FIXTURE_DIR = (
    Path(__file__).resolve().parents[2]
    / "companion-ui"
    / "companion-app"
    / "tests"
    / "fixtures"
    / "obsidian-renderer"
)

FIXTURE_NAMES = [
    "basic.md",
    "frontmatter-properties.md",
    "malformed-frontmatter.md",
    "wikilinks.md",
    "embeds-images.md",
    "callouts.md",
    "mermaid.md",
    "comments-and-html.md",
    "missing-links-assets.md",
    "full-smoke.md",
]


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_obsidian_fixture_raw_markdown_round_trips(fixture_name: str) -> None:
    raw_markdown = (FIXTURE_DIR / fixture_name).read_text(encoding="utf-8")

    document = parse_vault_markdown(raw_markdown)

    assert document.raw_markdown == raw_markdown
    assert isinstance(document.body_markdown, str)


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_obsidian_fixture_renders_without_crash(fixture_name: str) -> None:
    raw_markdown = (FIXTURE_DIR / fixture_name).read_text(encoding="utf-8")

    rendered = render_vault_markdown(raw_markdown, note_path="Notes/current.md")

    assert rendered.html
    assert 'class="vault-markdown-rendered"' in rendered.html


def test_full_smoke_fixture_extracts_all_parser_reference_types() -> None:
    document = parse_vault_markdown((FIXTURE_DIR / "full-smoke.md").read_text(encoding="utf-8"))

    assert document.frontmatter is not None
    assert len(document.headings) == 3
    assert len(document.block_ids) == 1
    assert len(document.wikilinks) == 7
    assert len(document.embeds) == 3
    assert len(document.comments) == 1
    assert {asset.target for asset in document.asset_refs} == set()
    assert any(diagnostic.code == "diagnostic_only_code_block" for diagnostic in document.diagnostics)


def test_missing_links_assets_fixture_keeps_unresolved_targets_unresolved() -> None:
    document = parse_vault_markdown(
        (FIXTURE_DIR / "missing-links-assets.md").read_text(encoding="utf-8")
    )

    assert {link.target for link in document.wikilinks} == {
        "ZZZ_NONEXISTENT_NOTE_ZZZ",
        "README",
    }
    assert {embed.target for embed in document.embeds} == {
        "zzz_nonexistent_image_zzz.png",
        "https://external.example.com/file.png",
    }
    assert document.asset_refs[0].target == "zzz_missing.png"
