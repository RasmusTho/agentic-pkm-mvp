import csv
from pathlib import Path

import pytest

from app.knowledge_acquisition.source_registry import (
    SourceRegistry,
    SourceRegistryValidationError,
    reset_memory_source_registry,
)
from app.knowledge_acquisition.youtube_onboarding import (
    import_takeout_registry,
    load_registry,
    parse_takeout,
    save_registry,
)


CHANNEL_A = "UC" + "a" * 22
CHANNEL_B = "UC" + "b" * 22
CHANNEL_BAD = "UC" + "c" * 22
ACCOUNT_ID = "d2c8eea1-a842-474a-b2a4-6448bd818551"


@pytest.fixture
def ragged_takeout(tmp_path: Path) -> Path:
    root = tmp_path / "Takeout"
    first = root / "first"
    second = root / "second"
    first.mkdir(parents=True)
    second.mkdir()

    def write_rows(path: Path, rows: list[list[str]]) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerows(rows)

    write_rows(first / "subscriptions.csv", [
        ["Channel ID", "Channel Title", "Channel URL"],
        [CHANNEL_A, "Alpha", ""],
        [CHANNEL_BAD, "Extra", "", "unexpected"],
        [CHANNEL_BAD, "Missing URL"],
        ["", "No identifier", ""],
        [CHANNEL_B, "Beta", ""],
    ])
    write_rows(second / "subscriptions.csv", [
        ["channelId", "channelTitle", "channelUrl"],
        [CHANNEL_A, "Alpha", ""],
        ["", "Gamma", f"https://www.youtube.com/channel/{'UC' + 'd' * 22}"],
    ])
    write_rows(first / "playlists.csv", [
        ["Playlist ID", "Playlist Title", "Playlist URL"],
        ["PLalpha", "A list", ""],
        ["PLbadextra", "Extra", "", "unexpected"],
        ["PLbadmissing", "Missing URL"],
        ["", "No identifier", ""],
        ["PLbeta", "B list", ""],
    ])
    write_rows(second / "playlists.csv", [
        ["playlistId", "playlistTitle", "playlistUrl"],
        ["PLalpha", "A list", ""],
        ["", "C list", "https://www.youtube.com/playlist?list=PLgamma"],
    ])
    write_rows(second / "unrelated.csv", [["Other", "Title"], ["PLfake", "Ignored"]])
    return root


def test_ragged_takeout_rows_do_not_abort_other_sources(ragged_takeout: Path) -> None:
    registry = parse_takeout(ragged_takeout)

    assert [(source.kind, source.source_id, source.title) for source in registry.sources] == [
        ("playlist", "PLalpha", "A list"),
        ("playlist", "PLbeta", "B list"),
        ("playlist", "PLgamma", "C list"),
        ("subscription", CHANNEL_A, "Alpha"),
        ("subscription", CHANNEL_B, "Beta"),
        ("subscription", "UC" + "d" * 22, "Gamma"),
    ]


def test_import_registry_skips_ragged_rows_idempotently(
    ragged_takeout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_memory_source_registry()
    try:
        registry = SourceRegistry.for_runtime()
        first = import_takeout_registry(ragged_takeout, registry=registry, account_binding_id=ACCOUNT_ID)
        before = {row.binding_id: row for row in registry.list_all()}
        assert first.imported == 6
        assert first.deduplicated == 0
        assert {(row.collection_kind, row.collection_ref) for row in before.values()} == {
            ("subscription_feed", CHANNEL_A),
            ("subscription_feed", CHANNEL_B),
            ("subscription_feed", "UC" + "d" * 22),
            ("owned_playlist", "PLalpha"),
            ("owned_playlist", "PLbeta"),
            ("owned_playlist", "PLgamma"),
        }
        subscription = next(row for row in before.values() if row.collection_ref == CHANNEL_A)
        registry.record_poll_success(subscription.binding_id, cursor={"recent_entry_ids": ["existing"]})
        before_replay = {row.binding_id: row for row in registry.list_all()}

        second = import_takeout_registry(ragged_takeout, registry=registry, account_binding_id=ACCOUNT_ID)
        assert second.imported == 0
        assert second.deduplicated == 6
        assert set(second.binding_ids) == set(first.binding_ids)
        assert {row.binding_id: row for row in registry.list_all()} == before_replay
    finally:
        reset_memory_source_registry()


@pytest.mark.parametrize(
    ("filename", "content", "error"),
    [
        ("subscriptions.csv", "Channel ID,Channel Title\ninvalid,Invalid\n", "invalid channel id"),
        ("playlists.csv", "Playlist ID,Playlist Title\ninvalid,Invalid\n", "invalid playlist id"),
    ],
)
def test_import_still_rejects_well_formed_invalid_ids_before_writes(
    ragged_takeout: Path, monkeypatch: pytest.MonkeyPatch, filename: str, content: str, error: str
) -> None:
    (ragged_takeout / "second" / filename).write_text(content, encoding="utf-8")
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_memory_source_registry()
    try:
        registry = SourceRegistry.for_runtime()
        with pytest.raises(SourceRegistryValidationError, match=error):
            import_takeout_registry(ragged_takeout, registry=registry, account_binding_id=ACCOUNT_ID)
        assert registry.list_all() == ()
    finally:
        reset_memory_source_registry()


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
