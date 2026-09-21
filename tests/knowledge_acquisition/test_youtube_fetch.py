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


def test_captionless_is_normal_outcome():
    # Pure unit test of the caption-selection decision (KA-01). Since KA-02
    # wired the ASR fallback into `fetch()`, a captionless `fetch()` call now
    # proceeds to ASR rather than terminating here — that end-to-end wiring is
    # covered by tests/knowledge_acquisition/test_asr_fallback.py. This test
    # keeps asserting the pure selection decision without needing to stub the
    # ASR chain.
    info = _base_info(subtitles={}, automatic_captions={})

    # Must not raise.
    selection = plugin.select_caption_track(info)

    assert selection.available is False
    assert selection.language is None
    assert selection.acquisition_method is None


def test_foreign_video_translated_only_autocaptions_is_captionless():
    # PR #2928 review round 1 BLOCKER regression fixture: a video whose known
    # language ("de") has NO track of its own, while automatic_captions carries
    # only auto-*translated* en/sv entries. The en/sv defaults must not be
    # consulted when the video language is known — the correct outcome is
    # captionless, and no caption URL may ever be requested. Pure unit test of
    # `select_caption_track` (see test_captionless_is_normal_outcome for why).
    info = _base_info(
        language="de",
        subtitles={},
        automatic_captions={
            "en": [{"ext": "vtt", "url": "https://example.com/auto-en-translated.vtt"}],
            "sv": [{"ext": "vtt", "url": "https://example.com/auto-sv-translated.vtt"}],
        },
    )

    selection = plugin.select_caption_track(info)

    assert selection.available is False
    assert selection.language is None


def test_unknown_language_autocaptions_never_requested():
    # Conservative posture for videos with no detected language (documented in
    # select_caption_track): without the video's language we cannot tell an
    # original auto track from an auto-translated one, so the automatic pass is
    # skipped entirely — captionless, ASR fallback (KA-02) consumes it later.
    # Pure unit test of `select_caption_track` (see
    # test_captionless_is_normal_outcome for why this no longer goes through
    # `fetch()`).
    info = _base_info(
        language=None,
        subtitles={},
        automatic_captions={
            "en": [{"ext": "vtt", "url": "https://example.com/auto-en-maybe-translated.vtt"}],
        },
    )

    selection = plugin.select_caption_track(info)

    assert selection.available is False
    assert selection.language is None


def test_unknown_language_manual_track_accepted(monkeypatch):
    # Unknown video language + a MANUAL en track: manual tracks are
    # creator-provided and never auto-*translated*, so the en/sv fallback is
    # safe for the manual pass (documented posture in select_caption_track).
    info = _base_info(
        language=None,
        subtitles={"en": [{"ext": "vtt", "url": "https://example.com/manual-en.vtt"}]},
        automatic_captions={},
    )
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: info)
    monkeypatch.setattr(plugin, "fetch_caption_body", lambda url: "WEBVTT\n\nmanual body")

    outcome = plugin.fetch(FAKE_URL)

    assert outcome.acquisition_method == "captions_manual"
    assert outcome.language == "en"


def test_foreign_video_own_language_track_accepted(monkeypatch):
    # A "de" video with a manual "de" track: original-language-only refers to
    # the VIDEO's language — the track is accepted even though "de" is outside
    # the en/sv defaults. Wrong-language rejection is the pipeline's early
    # metadata filter (REFINEMENT_PIPELINE_CONTRACT § Stage execution model),
    # not the plugin's job.
    info = _base_info(
        language="de",
        subtitles={"de": [{"ext": "vtt", "url": "https://example.com/manual-de.vtt"}]},
        automatic_captions={},
    )
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: info)
    monkeypatch.setattr(plugin, "fetch_caption_body", lambda url: "WEBVTT\n\nde manual body")

    outcome = plugin.fetch(FAKE_URL)

    assert outcome.acquisition_method == "captions_manual"
    assert outcome.language == "de"


def test_vtt_preferred_when_json3_listed_first(monkeypatch):
    # Regression for #2957: real yt-dlp responses list `json3` before `vtt` in the
    # per-language track list (verified against multiple real videos). The old
    # `_pick_track_url` did a single pass checking `ext in {"vtt", "srv3", "json3"}` and
    # returned the FIRST matching track regardless of preference — on every real fetch
    # that meant `json3`, which `normalize()`'s VTT-only cue parser can never parse
    # (fail-loud NormalizeError on every real-video caption fetch). `vtt` must be chosen
    # whenever it is present, no matter where it sorts in the raw track list.
    info = _base_info(
        subtitles={
            "en": [
                {"ext": "json3", "url": "https://example.com/manual.json3"},
                {"ext": "srv1", "url": "https://example.com/manual.srv1"},
                {"ext": "srv3", "url": "https://example.com/manual.srv3"},
                {"ext": "vtt", "url": "https://example.com/manual.vtt"},
            ]
        },
        automatic_captions={},
    )
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: info)

    def fake_caption_body(url: str) -> str:
        assert url == "https://example.com/manual.vtt"
        return "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello vtt world"

    monkeypatch.setattr(plugin, "fetch_caption_body", fake_caption_body)

    outcome = plugin.fetch(FAKE_URL)

    assert outcome.acquisition_method == "captions_manual"
    assert outcome.record["caption_body"].startswith("WEBVTT")


def test_pick_track_url_falls_back_to_first_when_no_preferred_ext():
    # No vtt/srv3/json3 present at all: falls back to the first track in the list
    # (unchanged fallback behavior, still exercised for coverage of the new lookup path).
    tracks = [
        {"ext": "ttml", "url": "https://example.com/manual.ttml"},
        {"ext": "srt", "url": "https://example.com/manual.srt"},
    ]
    assert plugin._pick_track_url(tracks) == "https://example.com/manual.ttml"


def test_region_tagged_language_selects_base_language_manual_track():
    # yt-dlp reports the video language as a full BCP-47 tag ("en-US") while
    # keying the caption tracks by base subtag ("en"). Exact-key matching
    # misreads such a video as captionless (#5610).
    info = _base_info(
        language="en-US",
        subtitles={"en": [{"ext": "vtt", "url": "https://example.com/manual-en.vtt"}]},
        automatic_captions={},
    )

    selection = plugin.select_caption_track(info)

    assert selection.available is True
    assert selection.language == "en"
    assert selection.acquisition_method == "captions_manual"
    assert selection.track_url == "https://example.com/manual-en.vtt"


def test_exact_language_tag_preferred_over_base_subtag():
    # When the creator published a track under the exact reported tag, that
    # track is the original one — the base-subtag track is the wider match and
    # must only be used as the fallback.
    info = _base_info(
        language="pt-BR",
        subtitles={
            "pt": [{"ext": "vtt", "url": "https://example.com/manual-pt.vtt"}],
            "pt-BR": [{"ext": "vtt", "url": "https://example.com/manual-pt-BR.vtt"}],
        },
        automatic_captions={},
    )

    selection = plugin.select_caption_track(info)

    assert selection.available is True
    assert selection.language == "pt-BR"
    assert selection.track_url == "https://example.com/manual-pt-BR.vtt"


def test_region_tagged_language_auto_pass_rejects_translated_tracks(monkeypatch):
    # Normalizing the region subtag must widen the automatic pass to the
    # video's own base language only — never to a machine-*translated* key
    # (YOUTUBE_SOURCE_SPEC.md § Transcript acquisition, point 1).
    info = _base_info(
        language="en-US",
        subtitles={},
        automatic_captions={
            "en": [{"ext": "vtt", "url": "https://example.com/auto-en.vtt"}],
            "de": [{"ext": "vtt", "url": "https://example.com/auto-de-translated.vtt"}],
            "sv": [{"ext": "vtt", "url": "https://example.com/auto-sv-translated.vtt"}],
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
    for translated_url in (
        "https://example.com/auto-de-translated.vtt",
        "https://example.com/auto-sv-translated.vtt",
    ):
        assert translated_url not in requested_urls


def test_fetch_region_tagged_language_uses_caption_path(monkeypatch):
    # Enforcement: the fix must hold at the production call site
    # (`fetch()` -> `select_caption_track`), not only in isolation. A
    # region-tagged video with a manual track must never reach the ASR chain.
    info = _base_info(
        language="en-GB",
        subtitles={"en": [{"ext": "vtt", "url": "https://example.com/manual-en.vtt"}]},
        automatic_captions={},
    )
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: info)
    monkeypatch.setattr(plugin, "fetch_caption_body", lambda url: "WEBVTT\n\nHello world")

    selection_calls: list[str | None] = []
    real_select = plugin.select_caption_track

    def tracking_select(caption_info):
        selection_calls.append(caption_info.get("language"))
        return real_select(caption_info)

    monkeypatch.setattr(plugin, "select_caption_track", tracking_select)

    def forbidden_transcribe(*args, **kwargs):
        raise AssertionError("ASR chain ran for a captioned video")

    monkeypatch.setattr(plugin, "transcribe_source", forbidden_transcribe)

    outcome = plugin.fetch(FAKE_URL)

    # `select_caption_track` was reached from the production `fetch()` path.
    assert selection_calls == ["en-GB"]
    assert outcome.ok is True
    assert outcome.acquisition_method == "captions_manual"
    assert outcome.language == "en"
    assert outcome.record["caption_body"] == "WEBVTT\n\nHello world"
