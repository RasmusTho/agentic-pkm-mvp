from __future__ import annotations

from pathlib import Path

from companion_ui.renderer.link_resolver import (
    VaultLinkResolver,
    link_display_label,
    parse_wikilink,
    parse_wikilinks,
)


FIXTURE_DIR = (
    Path(__file__).resolve().parents[2]
    / "companion-ui"
    / "companion-app"
    / "tests"
    / "fixtures"
    / "obsidian-renderer"
)


def test_wikilink_variants() -> None:
    cases = [
        (
            "[[Note]]",
            {
                "raw_target": "Note",
                "target": "Note",
                "alias": None,
                "heading": None,
                "block_id": None,
                "local_only": False,
            },
        ),
        (
            "[[Note.md]]",
            {
                "raw_target": "Note.md",
                "target": "Note.md",
                "alias": None,
                "heading": None,
                "block_id": None,
                "local_only": False,
            },
        ),
        (
            "[[Note|Alias]]",
            {
                "raw_target": "Note",
                "target": "Note",
                "alias": "Alias",
                "heading": None,
                "block_id": None,
                "local_only": False,
            },
        ),
        (
            "[[Note#Heading]]",
            {
                "raw_target": "Note#Heading",
                "target": "Note",
                "alias": None,
                "heading": "Heading",
                "block_id": None,
                "local_only": False,
            },
        ),
        (
            "[[Note#Heading|Alias]]",
            {
                "raw_target": "Note#Heading",
                "target": "Note",
                "alias": "Alias",
                "heading": "Heading",
                "block_id": None,
                "local_only": False,
            },
        ),
        (
            "[[Note#^block-id]]",
            {
                "raw_target": "Note#^block-id",
                "target": "Note",
                "alias": None,
                "heading": None,
                "block_id": "block-id",
                "local_only": False,
            },
        ),
        (
            "[[#Local heading]]",
            {
                "raw_target": "#Local heading",
                "target": "",
                "alias": None,
                "heading": "Local heading",
                "block_id": None,
                "local_only": True,
            },
        ),
        (
            "[[^local-block]]",
            {
                "raw_target": "^local-block",
                "target": "",
                "alias": None,
                "heading": None,
                "block_id": "local-block",
                "local_only": True,
            },
        ),
    ]

    for raw, expected in cases:
        link = parse_wikilink(raw)
        assert link.raw == raw
        assert link.raw_target == expected["raw_target"]
        assert link.target == expected["target"]
        assert link.alias == expected["alias"]
        assert link.heading == expected["heading"]
        assert link.block_id == expected["block_id"]
        assert link.local_only is expected["local_only"]

    parsed = parse_wikilinks("embed: ![[image.png]] link: [[Note]]")
    assert [link.raw for link in parsed] == ["[[Note]]"]


def test_missing_link_display() -> None:
    resolver = VaultLinkResolver(
        {
            "ExistingNote": "notes/ExistingNote.md",
            "AmbiguousNote": ("a/AmbiguousNote.md", "b/AmbiguousNote.md"),
        }
    )

    missing = resolver.resolve(
        parse_wikilink("[[NonExistentNote12345]]"),
        note_path="current.md",
    )
    assert missing.kind == "missing"
    assert link_display_label(missing) == "NonExistentNote12345 (missing link)"

    ambiguous = resolver.resolve(
        parse_wikilink("[[AmbiguousNote]]"),
        note_path="current.md",
    )
    assert ambiguous.kind == "ambiguous"
    assert link_display_label(ambiguous) == "AmbiguousNote (ambiguous link)"


def test_wikilinks_fixture() -> None:
    raw_markdown = (FIXTURE_DIR / "wikilinks.md").read_text(encoding="utf-8")

    links = parse_wikilinks(raw_markdown)

    assert [link.raw for link in links] == [
        "[[ExistingNote]]",
        "[[ExistingNote|Display Alias]]",
        "[[ExistingNote#Section Header]]",
        "[[ExistingNote#Section Header|Alias]]",
        "[[ExistingNote#^abc123]]",
        "[[#Local Section]]",
        "[[^local-block-id]]",
        "[[NonExistentNote12345]]",
        "[[AmbiguousNote]]",
    ]
    assert links[3].alias == "Alias"
    assert links[4].block_id == "abc123"
    assert links[5].local_only is True
    assert links[5].heading == "Local Section"
    assert links[6].local_only is True
    assert links[6].block_id == "local-block-id"
