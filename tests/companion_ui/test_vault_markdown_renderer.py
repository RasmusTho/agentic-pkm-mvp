"""VaultMarkdownRenderer integration coverage for the Obsidian note surface."""

from __future__ import annotations

from pathlib import Path

from companion_ui.renderer import render_vault_markdown
from companion_ui.renderer.asset_resolver import VaultAssetResolver
from companion_ui.renderer.link_resolver import VaultLinkResolver


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


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def _link_resolver() -> VaultLinkResolver:
    return VaultLinkResolver(
        {
            "ExistingNote": "Notes/ExistingNote.md",
            "AmbiguousNote": [
                "Notes/AmbiguousNote.md",
                "Archive/AmbiguousNote.md",
            ],
            "README": [
                "README.md",
                "docs/README.md",
            ],
        }
    )


def _asset_resolver() -> VaultAssetResolver:
    return VaultAssetResolver(
        {
            "test-image.png": "/api/companion/vault-assets/test-image.png",
        }
    )


def test_basic_fixtures() -> None:
    for fixture_name in FIXTURE_NAMES:
        rendered = render_vault_markdown(
            _fixture(fixture_name),
            note_path="Notes/current.md",
            link_resolver=_link_resolver(),
            asset_resolver=_asset_resolver(),
        )

        assert rendered.html
        assert 'class="vault-markdown-rendered"' in rendered.html
        assert "file://" not in rendered.html
        assert "javascript:" not in rendered.html.lower()

    basic = render_vault_markdown(_fixture("basic.md"))
    assert '<h1 id="heading-1">Heading 1</h1>' in basic.html
    assert '<h2 id="custom-anchor">Heading 2</h2>' in basic.html
    assert "<strong>bold</strong>" in basic.html
    assert "<em>italic</em>" in basic.html
    assert "<del>strikethrough</del>" in basic.html
    assert "<table>" in basic.html
    assert 'class="task-list"' in basic.html
    assert 'data-task-state="/"' in basic.html
    assert 'data-language="python"' in basic.html


def test_frontmatter_excluded_from_body() -> None:
    rendered = render_vault_markdown(_fixture("frontmatter-properties.md"))

    assert "Body text that must NOT include" in rendered.html
    assert "custom_field" not in rendered.html
    assert "aliases:" not in rendered.html
    assert rendered.document.frontmatter is not None


def test_internal_links() -> None:
    rendered = render_vault_markdown(
        _fixture("wikilinks.md"),
        note_path="Notes/current.md",
        link_resolver=_link_resolver(),
    )

    assert 'data-link-state="resolved"' in rendered.html
    assert 'data-link-state="missing"' in rendered.html
    assert 'data-link-state="ambiguous"' in rendered.html
    assert "Display Alias" in rendered.html
    assert "NonExistentNote12345" in rendered.html
    assert "ambiguous link" in rendered.html
    assert "Notes/ExistingNote.md" in rendered.html


def test_unresolved_link_partial_emits_title_attr() -> None:
    rendered = render_vault_markdown("[[Missing Note]]", link_resolver=_link_resolver())

    assert (
        '<span class="vault-wikilink vault-wikilink-diagnostic" '
        'data-link-state="missing" title="[[Missing Note]] — not found in vault">'
    ) in rendered.html


def test_image_rendering() -> None:
    rendered = render_vault_markdown(
        _fixture("embeds-images.md"),
        asset_resolver=_asset_resolver(),
    )

    assert '<img class="vault-image"' in rendered.html
    assert 'src="/api/companion/vault-assets/test-image.png"' in rendered.html
    assert 'width="100"' in rendered.html
    assert 'height="145"' in rendered.html
    assert 'data-asset-state="blocked"' in rendered.html
    assert 'data-asset-state="unsupported"' in rendered.html
    assert "file://" not in rendered.html


UAT_IMAGE_PATH = "Attachments/uat_real_image.png"
UAT_IMAGE_SRC = "/api/companion/vault-assets/Attachments%2Fuat_real_image.png"


def _uat_asset_resolver() -> VaultAssetResolver:
    # Mirrors the live resolver boundary: the committed vault asset
    # (vault/9_Extras/Attachments/uat_real_image.png) is exposed as an allowed,
    # browser-safe src. The renderer never touches the filesystem (#1347).
    return VaultAssetResolver({UAT_IMAGE_PATH: UAT_IMAGE_SRC})


def test_existing_image_renders_img() -> None:
    # #1347 AC2 — Markdown image syntax for an existing asset renders to <img>.
    rendered = render_vault_markdown(
        f"![Pattern fixture]({UAT_IMAGE_PATH})",
        note_path="Companion_UI_Markdown_Feature_UAT.md",
        asset_resolver=_uat_asset_resolver(),
    )

    assert '<img class="vault-image"' in rendered.html
    assert 'data-asset-state="allowed"' in rendered.html
    assert f'src="{UAT_IMAGE_SRC}"' in rendered.html
    assert 'alt="Pattern fixture"' in rendered.html
    assert "missing-image" not in rendered.html
    assert "file://" not in rendered.html


def test_existing_image_embed_renders_img() -> None:
    # #1347 AC3 — Obsidian embed syntax for the same asset renders to <img>.
    rendered = render_vault_markdown(
        f"![[{UAT_IMAGE_PATH}]]",
        note_path="Companion_UI_Markdown_Feature_UAT.md",
        asset_resolver=_uat_asset_resolver(),
    )

    assert '<img class="vault-image"' in rendered.html
    assert 'data-asset-state="allowed"' in rendered.html
    assert f'src="{UAT_IMAGE_SRC}"' in rendered.html
    # Embed has no explicit alt; the resolver display name is used instead.
    assert 'alt="uat_real_image.png"' in rendered.html
    assert "missing-image" not in rendered.html


def test_missing_image_still_uses_partial_alongside_existing_asset() -> None:
    # #1347 AC4 — the missing-asset path is unchanged: an unknown target still
    # degrades to the #1340 missing-image partial even when other assets resolve.
    rendered = render_vault_markdown(
        f"![real]({UAT_IMAGE_PATH})\n\n![gone](Attachments/nonexistent-image.png)",
        note_path="Companion_UI_Markdown_Feature_UAT.md",
        asset_resolver=_uat_asset_resolver(),
    )

    assert '<img class="vault-image"' in rendered.html
    assert 'data-testid="missing-image"' in rendered.html
    assert 'data-asset-state="missing"' in rendered.html
    assert "nonexistent-image.png" in rendered.html


def _wikilink_resolver() -> VaultLinkResolver:
    # Stub resolver seeded with a single existing note (#1345). A real workspace
    # request seeds the same shape from the active-vault link index.
    return VaultLinkResolver({"Existing Note": "Notes/Existing Note.md"})


def test_bare_wikilink_resolves() -> None:
    # #1345 AC1 — a bare wikilink to an existing note navigates.
    rendered = render_vault_markdown("[[Existing Note]]", link_resolver=_wikilink_resolver())

    assert 'class="vault-wikilink"' in rendered.html
    assert 'data-link-state="resolved"' in rendered.html
    assert 'href="?note_path=Notes%2FExisting%20Note.md"' in rendered.html
    assert ">Existing Note</a>" in rendered.html
    assert "vault-wikilink-diagnostic" not in rendered.html


def test_aliased_wikilink_resolves() -> None:
    # #1345 AC2 — aliased link resolves; the alias is the visible text.
    rendered = render_vault_markdown(
        "[[Existing Note|display alias]]", link_resolver=_wikilink_resolver()
    )

    assert 'data-link-state="resolved"' in rendered.html
    assert 'href="?note_path=Notes%2FExisting%20Note.md"' in rendered.html
    assert ">display alias</a>" in rendered.html


def test_heading_fragment_wikilink_resolves() -> None:
    # #1345 AC3 — heading-fragment link resolves; href carries the slug anchor
    # that matches the rendered heading element id so it scrolls into view.
    rendered = render_vault_markdown(
        "[[Existing Note#Some Heading]]", link_resolver=_wikilink_resolver()
    )

    assert 'data-link-state="resolved"' in rendered.html
    assert "?note_path=Notes%2FExisting%20Note.md#some-heading" in rendered.html


def test_block_id_wikilink_resolves() -> None:
    # #1345 AC4 — block-id link resolves; href keeps the literal ^block-id form.
    rendered = render_vault_markdown(
        "[[Existing Note#^block-id]]", link_resolver=_wikilink_resolver()
    )

    assert 'data-link-state="resolved"' in rendered.html
    assert "?note_path=Notes%2FExisting%20Note.md#^block-id" in rendered.html


def test_unresolved_wikilink_unchanged() -> None:
    # #1345 AC5 — an unresolved target keeps the post-#1334 diagnostic shape.
    rendered = render_vault_markdown(
        "[[Definitely Missing]]", link_resolver=_wikilink_resolver()
    )

    assert (
        '<span class="vault-wikilink vault-wikilink-diagnostic" '
        'data-link-state="missing"'
    ) in rendered.html
    assert "Definitely Missing" in rendered.html
    assert 'data-link-state="resolved"' not in rendered.html


def test_unsafe_html_stripped() -> None:
    rendered = render_vault_markdown(_fixture("comments-and-html.md"))
    lowered = rendered.html.lower()

    assert "<script" not in lowered
    assert "onerror" not in lowered
    assert "alert(" not in lowered
    assert "This comment should be hidden" not in rendered.html
    assert "styled text" in rendered.html


def test_no_write_calls() -> None:
    rendered = render_vault_markdown(
        "A [[ExistingNote]] and ![[test-image.png]]",
        note_path="Notes/current.md",
        link_resolver=_link_resolver(),
        asset_resolver=_asset_resolver(),
    )

    assert rendered.write_calls == ()
    assert "POST" not in rendered.html
    assert "PUT" not in rendered.html
    assert "PATCH" not in rendered.html
    assert "DELETE" not in rendered.html

    renderer_source = (
        Path(__file__).resolve().parents[2]
        / "companion-ui"
        / "companion-app"
        / "companion_ui"
        / "renderer"
        / "vault_markdown_renderer.py"
    ).read_text(encoding="utf-8")
    for forbidden_call in ("httpx.", "WorkspaceHttpClient", ".post(", ".put(", ".patch(", ".delete("):
        assert forbidden_call not in renderer_source
