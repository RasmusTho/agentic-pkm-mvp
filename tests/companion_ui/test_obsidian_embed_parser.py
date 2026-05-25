from pathlib import Path

import pytest

from companion_ui.renderer.asset_resolver import parse_obsidian_embed, parse_obsidian_embeds


FIXTURE_DIR = (
    Path(__file__).resolve().parents[2]
    / "companion-ui"
    / "companion-app"
    / "tests"
    / "fixtures"
    / "obsidian-renderer"
)


@pytest.mark.parametrize(
    ("raw", "target", "kind", "heading", "block_id"),
    [
        ("![[image.png]]", "image.png", "image", None, None),
        ("![[Some Note]]", "Some Note", "note", None, None),
        ("![[Some Note#Heading]]", "Some Note", "note", "Heading", None),
        ("![[Some Note#^block-id]]", "Some Note", "note", None, "block-id"),
        ("![[Document.pdf#page=3]]", "Document.pdf", "pdf", "page=3", None),
        ("![[audio.mp3]]", "audio.mp3", "audio", None, None),
        ("![[video.mp4]]", "video.mp4", "video", None, None),
        ("![[diagram.canvas]]", "diagram.canvas", "canvas", None, None),
        ("![[unknown.xyz]]", "unknown.xyz", "unknown", None, None),
    ],
)
def test_embed_classification(
    raw: str,
    target: str,
    kind: str,
    heading: str | None,
    block_id: str | None,
) -> None:
    embed = parse_obsidian_embed(raw)

    assert embed.raw == raw
    assert embed.target == target
    assert embed.kind == kind
    assert embed.heading == heading
    assert embed.block_id == block_id


@pytest.mark.parametrize(
    ("raw", "width", "height"),
    [
        ("![[image.png]]", None, None),
        ("![[image.png|100]]", 100, None),
        ("![[image.png|100x145]]", 100, 145),
    ],
)
def test_size_hints(raw: str, width: int | None, height: int | None) -> None:
    embed = parse_obsidian_embed(raw)

    assert embed.target == "image.png"
    assert embed.width == width
    assert embed.height == height


def test_embeds_fixture() -> None:
    markdown = (FIXTURE_DIR / "embeds-images.md").read_text()

    embeds = parse_obsidian_embeds(markdown)

    assert [embed.kind for embed in embeds] == [
        "image",
        "image",
        "image",
        "note",
        "note",
        "note",
        "pdf",
        "pdf",
        "audio",
        "video",
        "canvas",
        "unknown",
    ]
    assert embeds[1].width == 100
    assert embeds[2].width == 100
    assert embeds[2].height == 145
    assert embeds[5].block_id == "blockid"
