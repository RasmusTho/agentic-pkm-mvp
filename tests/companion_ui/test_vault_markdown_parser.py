"""Fixture-driven parser coverage for Obsidian-compatible vault Markdown (#1296)."""

from __future__ import annotations

from pathlib import Path

from companion_ui.renderer import parse_vault_markdown


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


def test_raw_markdown_preserved() -> None:
    raw_markdown = _fixture("full-smoke.md")

    document = parse_vault_markdown(raw_markdown)

    assert document.raw_markdown == raw_markdown


def test_frontmatter_extraction() -> None:
    document = parse_vault_markdown(_fixture("frontmatter-properties.md"))

    assert document.frontmatter is not None
    assert "title: Frontmatter Fixture" in document.frontmatter
    assert "tags: [alpha, beta, gamma]" in document.frontmatter
    assert "aliases: [Alt Name, Another Alias]" in document.frontmatter


def test_body_excludes_frontmatter() -> None:
    document = parse_vault_markdown(_fixture("frontmatter-properties.md"))

    assert document.body_markdown.startswith("\nBody text")
    assert "title: Frontmatter Fixture" not in document.body_markdown
    assert "custom_field: some value" not in document.body_markdown


def test_heading_extraction() -> None:
    document = parse_vault_markdown(_fixture("basic.md"))

    assert [(heading.level, heading.text, heading.anchor) for heading in document.headings] == [
        (1, "Heading 1", "heading-1"),
        (2, "Heading 2", "custom-anchor"),
        (3, "Heading 3", "heading-3"),
    ]


def test_block_id_extraction() -> None:
    document = parse_vault_markdown(_fixture("wikilinks.md"))

    assert [(block.block_id, block.anchor) for block in document.block_ids] == [
        ("local-block-id", "local-block-id")
    ]


def test_wikilink_extraction() -> None:
    document = parse_vault_markdown(_fixture("wikilinks.md"))

    links = {link.raw: link for link in document.wikilinks}
    assert links["[[ExistingNote]]"].target == "ExistingNote"
    assert links["[[ExistingNote|Display Alias]]"].alias == "Display Alias"
    assert links["[[ExistingNote#Section Header]]"].heading == "Section Header"
    assert links["[[ExistingNote#Section Header|Alias]]"].alias == "Alias"
    assert links["[[ExistingNote#^abc123]]"].block_id == "abc123"
    assert links["[[#Local Section]]"].local_only is True
    assert links["[[#Local Section]]"].heading == "Local Section"
    assert links["[[^local-block-id]]"].local_only is True
    assert links["[[^local-block-id]]"].block_id == "local-block-id"
    assert links["[[NonExistentNote12345]]"].target == "NonExistentNote12345"
    assert links["[[AmbiguousNote]]"].target == "AmbiguousNote"
    assert len(document.wikilinks) == 9


def test_embed_extraction() -> None:
    document = parse_vault_markdown(_fixture("embeds-images.md"))

    embeds = {embed.raw: embed for embed in document.embeds}
    assert embeds["![[test-image.png]]"].kind == "image"
    assert embeds["![[test-image.png|100]]"].width == 100
    assert embeds["![[test-image.png|100x145]]"].width == 100
    assert embeds["![[test-image.png|100x145]]"].height == 145
    assert embeds["![[SomeNote]]"].kind == "note"
    assert embeds["![[SomeNote#Heading]]"].heading == "Heading"
    assert embeds["![[SomeNote#^blockid]]"].block_id == "blockid"
    assert embeds["![[document.pdf]]"].kind == "pdf"
    assert embeds["![[document.pdf#page=3]]"].fragment == "page=3"
    assert embeds["![[audio.mp3]]"].kind == "audio"
    assert embeds["![[video.mp4]]"].kind == "video"
    assert embeds["![[diagram.canvas]]"].kind == "canvas"
    assert embeds["![[unknown.xyz]]"].kind == "unknown"
    assert document.asset_refs[0].raw == "![Alt text](https://example.com/image.png)"
    assert document.asset_refs[0].alt == "Alt text"
    assert len(document.embeds) == 12


def test_comment_extraction() -> None:
    document = parse_vault_markdown(_fixture("comments-and-html.md"))

    assert len(document.comments) == 2
    assert document.comments[0].raw == "%% This comment should be hidden in Reading View. %%"
    assert document.comments[0].text.strip() == "This comment should be hidden in Reading View."
    assert document.comments[0].suppress_in_reading_view is True
    assert document.comments[1].text.strip() == "Multi-word inline comment"


def test_comment_bodies_are_not_parsed_as_active_references() -> None:
    document = parse_vault_markdown(
        "Visible [[LiveNote]]\n\n"
        "%% hidden [[DraftOnly]] ![[hidden.png]] ^hidden-block %%\n\n"
        "After [[AfterNote]]\n"
    )

    assert [link.target for link in document.wikilinks] == ["LiveNote", "AfterNote"]
    assert document.embeds == []
    assert document.block_ids == []
    assert len(document.comments) == 1


def test_malformed_frontmatter_diagnostic() -> None:
    document = parse_vault_markdown(_fixture("malformed-frontmatter.md"))

    assert document.frontmatter is not None
    assert document.body_markdown.startswith("\nBody text should still be returned")
    assert any(
        diagnostic.code == "frontmatter_parse_error"
        and diagnostic.severity in {"warning", "error"}
        for diagnostic in document.diagnostics
    )


def test_apostrophe_value_no_parse_error() -> None:
    document = parse_vault_markdown(
        "---\n"
        "title: Rasmus's note\n"
        "---\n"
        "Body text.\n"
    )

    assert document.frontmatter is not None
    assert not any(
        diagnostic.code == "frontmatter_parse_error"
        for diagnostic in document.diagnostics
    )


def test_unterminated_quoted_scalar_still_malformed() -> None:
    document = parse_vault_markdown(
        "---\n"
        'title: "oops\n'
        "---\n"
        "Body text.\n"
    )

    assert any(
        diagnostic.code == "frontmatter_parse_error"
        for diagnostic in document.diagnostics
    )


def test_apostrophe_led_token_after_space_no_parse_error() -> None:
    # #2181 — an apostrophe-led token following an internal space is a valid
    # unquoted scalar, not an unterminated quoted scalar.
    for value in ("The week 'twas before", "the 'thing", "Reading 'The Hobbit' notes"):
        document = parse_vault_markdown(f"---\ntitle: {value}\n---\nBody.\n")
        assert not any(
            diagnostic.code == "frontmatter_parse_error"
            for diagnostic in document.diagnostics
        ), f"valid frontmatter value {value!r} must not be flagged malformed"


def test_unterminated_list_item_scalar_still_malformed() -> None:
    # #2181 — detection must survive for indented list items: an unterminated
    # quoted scalar after "- " is still flagged, like the key/value case.
    document = parse_vault_markdown('---\ntags:\n  - "oops\n---\nBody.\n')

    assert any(
        diagnostic.code == "frontmatter_parse_error"
        for diagnostic in document.diagnostics
    )


def test_hyphen_led_scalar_is_not_a_list_marker() -> None:
    # #2181 — a hyphen is a list marker only when followed by whitespace.
    # "title: -'foo" and "- -'foo" are valid plain scalars, not list items, so
    # the quote must not be treated as an opening delimiter.
    for body in ("title: -'foo", "tags:\n  - -'foo"):
        document = parse_vault_markdown(f"---\n{body}\n---\nBody.\n")
        assert not any(
            diagnostic.code == "frontmatter_parse_error"
            for diagnostic in document.diagnostics
        ), f"valid hyphen-led scalar {body!r} must not be flagged malformed"


def test_unterminated_flow_list_scalar_still_malformed() -> None:
    # #2181 — an unterminated quoted scalar inside a flow-style array is flagged.
    document = parse_vault_markdown('---\ntags: [alpha, "oops]\n---\nBody.\n')

    assert any(
        diagnostic.code == "frontmatter_parse_error"
        for diagnostic in document.diagnostics
    )


def test_valid_flow_lists_are_not_flagged() -> None:
    # #2181 — well-formed flow arrays (plain and quoted entries) parse cleanly.
    for value in ("[alpha, beta, gamma]", "['a', 'b']", '["x", "y"]'):
        document = parse_vault_markdown(f"---\ntags: {value}\n---\nBody.\n")
        assert not any(
            diagnostic.code == "frontmatter_parse_error"
            for diagnostic in document.diagnostics
        ), f"valid flow list {value!r} must not be flagged malformed"


def test_long_fence_keeps_inner_shorter_fence_literal() -> None:
    document = parse_vault_markdown(
        "````markdown\n"
        "```python\n"
        "[[NotAnActiveLink]]\n"
        "![[not-active.png]]\n"
        "```\n"
        "````\n\n"
        "[[ActiveLink]]\n"
    )

    assert [link.target for link in document.wikilinks] == ["ActiveLink"]
    assert document.embeds == []
