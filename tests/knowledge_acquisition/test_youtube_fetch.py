"""KA-01 tests for the `youtube_url` plugin's `fetch` operation.

All network egress is stubbed: `yt_dlp_extract_info` and `fetch_caption_body`
are monkeypatched to return fixture data, so these tests exercise zero real
yt-dlp/YouTube calls (CI-safe, per ACQUIRE_YOUTUBE_CAPTIONS.md § How to Verify).
"""

from __future__ import annotations

import pytest

from app import objects as object_store_module
from app.knowledge_acquisition import youtube_plugin as plugin
from app.stores import reset_store_backends

FAKE_URL = "https://www.youtube.com/watch?v=abcdefghijk"


@pytest.fixture(autouse=True)
def _memory_store(monkeypatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_store_backends()
    object_store_module._MEMORY_STORE.clear()
    yield
    reset_store_backends()
    object_store_module._MEMORY_STORE.clear()


def _base_info(**overrides):
    info = {
        "id": "abcdefghijk",
        "title": "A Test Video",
        "channel": "Test Channel",
        "channel_id": "UC123",
        "upload_date": "20260101",
        "duration": 600,
        "description": "desc",
        "chapters": [],
        "tags": ["a", "b"],
        "language": "en",
        "thumbnail": "https://example.com/thumb.jpg",
        "subtitles": {},
        "automatic_captions": {},
    }
    info.update(overrides)
    return info


def test_manual_track_preferred_over_auto(monkeypatch):
    info = _base_info(
        subtitles={"en": [{"ext": "vtt", "url": "https://example.com/manual.vtt"}]},
        automatic_captions={"en": [{"ext": "vtt", "url": "https://example.com/auto.vtt"}]},
    )
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: info)

    def fake_caption_body(url: str) -> str:
        assert url == "https://example.com/manual.vtt"
        return "WEBVTT\n\nHello manual world"

    monkeypatch.setattr(plugin, "fetch_caption_body", fake_caption_body)

    outcome = plugin.fetch(FAKE_URL)

    assert outcome.acquisition_method == "captions_manual"
    assert outcome.language == "en"
    assert outcome.record["caption_body"] == "WEBVTT\n\nHello manual world"


def test_translated_tracks_excluded(monkeypatch):
    # automatic_captions carries the original-language track ("en") plus
    # machine-*translated* tracks for many other languages, mirroring real
    # yt-dlp output. Only the original-language key may ever be requested.
    info = _base_info(
        subtitles={},
        automatic_captions={
            "en": [{"ext": "vtt", "url": "https://example.com/auto-en.vtt"}],
            "de": [{"ext": "vtt", "url": "https://example.com/auto-de-translated.vtt"}],
            "fr": [{"ext": "vtt", "url": "https://example.com/auto-fr-translated.vtt"}],
            "es": [{"ext": "vtt", "url": "https://example.com/auto-es-translated.vtt"}],
        },
    )
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: info)

    requested_urls: list[str] = []

    def fake_caption_body(url: str) -> str:
        requested_urls.append(url)
        return "WEBVTT\n\nHello auto world"

    monkeypatch.setattr(plugin, "fetch_caption_body", fake_caption_body)

    outcome = plugin.fetch(FAKE_URL)

    assert outcome.acquisition_method == "captions_auto"
    assert outcome.language == "en"
    assert requested_urls == ["https://example.com/auto-en.vtt"]
    # No translated-language track URL was ever requested.
    for translated_url in (
        "https://example.com/auto-de-translated.vtt",
        "https://example.com/auto-fr-translated.vtt",
        "https://example.com/auto-es-translated.vtt",
    ):
        assert translated_url not in requested_urls


def test_captionless_is_normal_outcome(monkeypatch):
    info = _base_info(subtitles={}, automatic_captions={})
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: info)

    caption_body_calls: list[str] = []
    monkeypatch.setattr(
        plugin,
        "fetch_caption_body",
        lambda url: caption_body_calls.append(url) or "should not be called",
    )

    # Must not raise.
    outcome = plugin.fetch(FAKE_URL)

    assert outcome.acquisition_method == "captionless"
    assert outcome.language is None
    assert caption_body_calls == []
    assert outcome.record["metadata"]["title"] == "A Test Video"
    assert outcome.is_new is True
