from pathlib import Path

from app.knowledge_acquisition.youtube_onboarding import load_registry, parse_takeout, save_registry


def test_parse_takeout_deduplicates_subscriptions_and_playlists(tmp_path: Path) -> None:
    export = tmp_path / "Takeout" / "YouTube and YouTube Music"
    export.mkdir(parents=True)
    (export / "subscriptions.csv").write_text(
        "Channel ID,Channel title,Channel URL\nUC123,Alpha,https://www.youtube.com/channel/UC123\n"
        "UC123,Alpha,https://www.youtube.com/channel/UC123\nUC456,Beta,https://www.youtube.com/channel/UC456\n",
        encoding="utf-8",
    )
    (export / "playlist.csv").write_text(
        "Playlist ID,Playlist title,Video ID,Video title\nPL1,Watch,vid1,One\nPL1,Watch,vid2,Two\n",
        encoding="utf-8",
    )

    registry = parse_takeout(tmp_path)

    assert [(source.kind, source.source_id) for source in registry.sources] == [
        ("playlist", "PL1"),
        ("subscription", "UC123"),
        ("subscription", "UC456"),
    ]
    assert registry.sources[0].url.endswith("list=PL1")


def test_registry_round_trip(tmp_path: Path) -> None:
    export = tmp_path / "export"
    export.mkdir()
    (export / "subscriptions.csv").write_text(
        "channel_id,channel_title,channel_url\nUC123,Alpha,https://www.youtube.com/channel/UC123\n",
        encoding="utf-8",
    )
    registry = parse_takeout(export)
    path = tmp_path / "state" / "youtube-sources.json"
    save_registry(path, registry)

    assert load_registry(path) == registry
