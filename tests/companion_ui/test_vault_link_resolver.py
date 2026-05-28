from __future__ import annotations

from companion_ui.renderer.link_resolver import (
    VaultLinkResolver,
    emit_navigation_intent,
    parse_wikilink,
)


def _resolver() -> VaultLinkResolver:
    return VaultLinkResolver(
        {
            "ExistingNote": "notes/ExistingNote.md",
            "AmbiguousNote": ("areas/a/AmbiguousNote.md", "areas/b/AmbiguousNote.md"),
        }
    )


def test_resolved() -> None:
    link = parse_wikilink("[[ExistingNote#Section Header|Display Alias]]")

    resolution = _resolver().resolve(link, note_path="current.md")
    params_resolution = _resolver().resolve(
        {
            "notePath": "current.md",
            "rawTarget": "ExistingNote#Section Header",
            "alias": "Display Alias",
        }
    )

    assert resolution.kind == "resolved"
    assert resolution.note_path == "notes/ExistingNote.md"
    assert resolution.display_text == "Display Alias"
    assert resolution.heading == "Section Header"
    assert resolution.block_id is None
    assert params_resolution == resolution


def test_missing() -> None:
    link = parse_wikilink("[[NonExistentNote12345]]")

    resolution = _resolver().resolve(link, note_path="current.md")

    assert resolution.kind == "missing"
    assert resolution.display_text == "NonExistentNote12345"
    assert "No note matches" in (resolution.reason or "")
    assert resolution.candidates == ()


def test_ambiguous() -> None:
    link = parse_wikilink("[[AmbiguousNote]]")

    resolution = _resolver().resolve(link, note_path="current.md")

    assert resolution.kind == "ambiguous"
    assert resolution.display_text == "AmbiguousNote"
    assert resolution.candidates == ("areas/a/AmbiguousNote.md", "areas/b/AmbiguousNote.md")
    assert resolution.note_path is None


def test_no_mutation_on_navigate() -> None:
    link = parse_wikilink("[[ExistingNote#^abc123]]")
    mutation_calls: list[str] = []

    resolution = _resolver().resolve(link, note_path="current.md")
    intent = emit_navigation_intent(resolution)

    assert resolution.kind == "resolved"
    assert intent is not None
    assert intent.kind == "navigate-note"
    assert intent.note_path == "notes/ExistingNote.md"
    assert intent.block_id == "abc123"
    assert mutation_calls == []
