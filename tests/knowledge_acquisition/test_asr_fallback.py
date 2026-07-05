"""KA-02 tests for the captionless ASR fallback wiring.

Per `docs/KNOWLEDGE_ACQUISITION/ASR_FALLBACK_PATH.md`: a captionless item
falls back to the existing `app.media.transcribe.transcribe_source`
faster-whisper chain (reused, not rewritten) and lands as a `raw` record
shaped identically to the caption path, differing only in
`acquisition_method` + quality note. ASR must never run when a usable caption
track exists.

All network/ASR egress is stubbed: `yt_dlp_extract_info`, `fetch_caption_body`,
and `transcribe_source` are monkeypatched to fixture data/functions, so these
tests exercise zero real yt-dlp/YouTube/faster-whisper calls (CI-safe, offline,
fast — per the issue's hard constraint and ASR_FALLBACK_PATH.md § How to
Verify).
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


def _fake_transcribe_result(*, text: str = "hej world", language: str = "sv"):
    """Fixture shape matching `app.media.transcribe.transcribe_source`'s real
    return value: {"object_id", "kind", "source_ref", "payload": {"text",
    "segments", "language"}, "trace_id"} (see app/media/transcribe.py
    `_record_outbox` / `transcribe_source`)."""

    def _fake(source: str, *, trace_id: str | None = None):
        return {
            "object_id": "fake-transcribe-object-id",
            "kind": "transcript",
            "source_ref": source,
            "payload": {
                "text": text,
                "segments": [
                    {"start": 0.0, "end": 1.5, "text": text},
                ],
                "language": language,
            },
            "trace_id": trace_id or "T-fake",
        }

    return _fake


def test_captionless_falls_back_to_asr(monkeypatch):
    info = _base_info(subtitles={}, automatic_captions={})
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: info)

    caption_body_calls: list[str] = []
    monkeypatch.setattr(
        plugin,
        "fetch_caption_body",
        lambda url: caption_body_calls.append(url) or "must not be called",
    )

    transcribe_calls: list[str] = []

    def fake_transcribe_source(source: str, *, trace_id: str | None = None):
        transcribe_calls.append(source)
        return _fake_transcribe_result(text="hej world", language="sv")(source, trace_id=trace_id)

    monkeypatch.setattr(plugin, "transcribe_source", fake_transcribe_source)

    outcome = plugin.fetch(FAKE_URL)

    assert outcome.acquisition_method == "asr"
    assert outcome.language == "sv"
    assert caption_body_calls == []
    assert transcribe_calls == [FAKE_URL]
    assert outcome.record["caption_body"] == "hej world"
    assert outcome.record["metadata"]["title"] == "A Test Video"
    assert outcome.is_new is True


def test_raw_record_shape_parity(monkeypatch):
    # Caption-path record.
    caption_info = _base_info(
        subtitles={"en": [{"ext": "vtt", "url": "https://example.com/manual.vtt"}]},
        automatic_captions={},
    )
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: caption_info)
    monkeypatch.setattr(plugin, "fetch_caption_body", lambda url: "manual caption body")
    caption_outcome = plugin.fetch(FAKE_URL)

    # ASR-path record (different video id so identity/dedup do not collide).
    asr_url = "https://www.youtube.com/watch?v=zzzzzzzzzzz"
    asr_info = _base_info(id="zzzzzzzzzzz", subtitles={}, automatic_captions={})
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: asr_info)
    monkeypatch.setattr(
        plugin,
        "fetch_caption_body",
        lambda url: (_ for _ in ()).throw(AssertionError("must not be called")),
    )
    monkeypatch.setattr(
        plugin, "transcribe_source", _fake_transcribe_result(text="asr transcript body", language="en")
    )
    asr_outcome = plugin.fetch(asr_url)

    caption_record = caption_outcome.record
    asr_record = asr_outcome.record

    # Same top-level schema (one schema for both paths).
    assert set(caption_record.keys()) - {"asr_segments", "quality_note"} == set(asr_record.keys()) - {
        "asr_segments",
        "quality_note",
    }
    # ASR-only additive fields present only on the ASR record.
    assert "asr_segments" in asr_record
    assert "quality_note" in asr_record
    assert "asr_segments" not in caption_record
    assert "quality_note" not in caption_record

    # Records differ only in acquisition_method (+ the quality-note-bearing
    # fields above) — everything else about provenance/shape is parallel.
    assert caption_record["acquisition_method"] == "captions_manual"
    assert asr_record["acquisition_method"] == "asr"
    assert caption_record["provenance"]["acquisition_method"] == "captions_manual"
    assert asr_record["provenance"]["acquisition_method"] == "asr"
    assert set(caption_record["provenance"].keys()) == set(asr_record["provenance"].keys())

    # Both carry the same identity/provenance/immutability/dedup contract
    # fields (KA-01 raw_record.py persist_raw_record defaults).
    for record in (caption_record, asr_record):
        assert "content_identity" in record
        assert "source_kind" in record
        assert "item_ref" in record
        assert "acquired_at" in record


def test_no_asr_when_captions_exist(monkeypatch):
    info = _base_info(
        subtitles={"en": [{"ext": "vtt", "url": "https://example.com/manual.vtt"}]},
        automatic_captions={},
    )
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: info)
    monkeypatch.setattr(plugin, "fetch_caption_body", lambda url: "manual caption body")

    asr_calls: list[str] = []

    def fail_if_called(source: str, *, trace_id: str | None = None):
        asr_calls.append(source)
        raise AssertionError("transcribe_source must not be called when captions exist")

    monkeypatch.setattr(plugin, "transcribe_source", fail_if_called)

    outcome = plugin.fetch(FAKE_URL)

    assert outcome.acquisition_method == "captions_manual"
    assert asr_calls == []
