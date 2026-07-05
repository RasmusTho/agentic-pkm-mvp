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
    assert outcome.ok is True
    assert outcome.failure is None


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

    # Value-level parity on shared fields: identical metadata key-set and
    # identical plugin_version across the two paths (review round 1, minor 1).
    assert set(caption_record["metadata"].keys()) == set(asr_record["metadata"].keys())
    assert (
        caption_record["provenance"]["plugin_version"]
        == asr_record["provenance"]["plugin_version"]
    )

    # Both carry the same identity/provenance/immutability/dedup contract
    # fields (KA-01 raw_record.py persist_raw_record defaults).
    for record in (caption_record, asr_record):
        assert "content_identity" in record
        assert "source_kind" in record
        assert "item_ref" in record
        assert "acquired_at" in record


def test_asr_refetch_is_dedup_noop_despite_asr_drift(monkeypatch):
    # BLOCKER regression (review round 1): faster-whisper output is
    # non-deterministic (beam search, no seed), so the transcribed text CANNOT
    # participate in content_identity — otherwise every re-fetch of the same
    # unchanged captionless item mints a new object_id and re-pays the full
    # download+transcription. The ASR-path identity is metadata-bound: re-fetch
    # with unchanged upstream metadata must be a traced dedup no-op that never
    # invokes the ASR chain, even when a hypothetical second transcription
    # would produce different text.
    info = _base_info(subtitles={}, automatic_captions={})
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: info)

    transcribe_calls: list[str] = []

    def first_transcribe(source: str, *, trace_id: str | None = None):
        transcribe_calls.append(source)
        return _fake_transcribe_result(text="first run wording", language="en")(
            source, trace_id=trace_id
        )

    monkeypatch.setattr(plugin, "transcribe_source", first_transcribe)
    first = plugin.fetch(FAKE_URL)
    assert first.is_new is True
    assert transcribe_calls == [FAKE_URL]

    # Second fetch: same unchanged item, but the stubbed ASR would return
    # DIFFERENT text (simulating whisper's non-determinism). It must not even
    # be invoked.
    def second_transcribe(source: str, *, trace_id: str | None = None):
        transcribe_calls.append(source)
        return _fake_transcribe_result(text="second run DIFFERENT wording", language="en")(
            source, trace_id=trace_id
        )

    monkeypatch.setattr(plugin, "transcribe_source", second_transcribe)
    second = plugin.fetch(FAKE_URL)

    assert second.is_new is False
    assert second.object_id == first.object_id
    assert second.content_identity == first.content_identity
    # ASR chain was NOT invoked on the second call (cost profile restored).
    assert transcribe_calls == [FAKE_URL]
    # The dedup hit returns the original persisted record, first transcription
    # preserved (immutability).
    assert second.record["caption_body"] == "first run wording"


def test_asr_metadata_change_new_record_prior_untouched(monkeypatch):
    # Parity with KA-01's changed-content test: upstream metadata change on a
    # captionless item yields a NEW record; the prior record is untouched.
    info_v1 = _base_info(subtitles={}, automatic_captions={})
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: info_v1)
    monkeypatch.setattr(
        plugin, "transcribe_source", _fake_transcribe_result(text="first transcript", language="en")
    )
    first = plugin.fetch(FAKE_URL)
    assert first.is_new is True

    info_v2 = _base_info(title="Updated Title", subtitles={}, automatic_captions={})
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: info_v2)
    monkeypatch.setattr(
        plugin, "transcribe_source", _fake_transcribe_result(text="second transcript", language="en")
    )
    second = plugin.fetch(FAKE_URL)

    assert second.is_new is True
    assert second.object_id != first.object_id
    assert second.content_identity != first.content_identity

    from app.knowledge_acquisition.raw_record import get_raw_record

    prior = get_raw_record(first.object_id)
    assert prior is not None
    assert prior["metadata"]["title"] == "A Test Video"
    assert prior["caption_body"] == "first transcript"

    updated = get_raw_record(second.object_id)
    assert updated is not None
    assert updated["metadata"]["title"] == "Updated Title"
    assert updated["caption_body"] == "second transcript"


def test_content_identity_golden_pins():
    # Golden pins (#2931 review round 2): any change to the fingerprint
    # composition silently RE-KEYS every persisted raw record — exactly the
    # round-1 regression, where an added fingerprint key shifted caption-path
    # hashes unnoticed. If one of these assertions fails, identity semantics
    # changed: that requires an explicit decision/migration, not a test-value
    # update.
    metadata = {"title": "Pinned Title", "description": "pinned description", "duration": 61}

    # Caption path — verified byte-identical to KA-01's (origin/main)
    # fingerprint construction for the same inputs.
    caption = plugin.CaptionSelection(
        available=True,
        language="en",
        acquisition_method="captions_manual",
        track_url="https://example.com/x.vtt",
        body="pinned caption body",
    )
    assert (
        plugin.compute_content_identity(metadata=metadata, caption=caption)
        == "sha256:477754cd5cb98ec3b63c670fa0c43752fd083f0e7169f6db179e776fee422e05"
    )

    # ASR path — metadata-bound fingerprint + method discriminator.
    assert (
        plugin.compute_content_identity(
            metadata=metadata, caption=plugin.CaptionSelection(available=False), asr_fallback=True
        )
        == "sha256:3b850605f069b26181285531aa225c5688389879a73a619ab5440e4bef8129c4"
    )


def test_asr_failure_runtime_error_is_traced_not_raised(monkeypatch):
    # MAJOR (review round 1): an ASR-chain failure (yt-dlp/faster-whisper
    # missing, download failure → RuntimeError) must be loud, item-scoped, and
    # traced — a failure outcome, never an unguarded raise, and no fabricated
    # raw record (item stays retryable).
    info = _base_info(subtitles={}, automatic_captions={})
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: info)

    def boom(source: str, *, trace_id: str | None = None):
        raise RuntimeError("yt-dlp is not installed")

    monkeypatch.setattr(plugin, "transcribe_source", boom)

    traced_events: list[dict] = []
    monkeypatch.setattr(plugin, "json_log", lambda **kw: traced_events.append(kw))

    outcome = plugin.fetch(FAKE_URL)  # must not raise

    assert outcome.ok is False
    assert outcome.failure is not None and "RuntimeError" in outcome.failure
    assert outcome.is_new is False
    assert outcome.object_id is None
    assert outcome.record == {}

    # The failure is TRACED (review round 2): the fallback_failed event was
    # actually emitted, carrying the item and the error.
    failed = [e for e in traced_events if e.get("event") == "knowledge_acquisition.asr.fallback_failed"]
    assert len(failed) == 1
    assert failed[0]["item_ref"] == "abcdefghijk"
    assert failed[0]["source_kind"] == plugin.SOURCE_KIND
    assert "RuntimeError" in failed[0]["error"]

    # Nothing was persisted: the identity slot is still free for a retry.
    from app.knowledge_acquisition.raw_record import get_raw_record, raw_record_object_id

    object_id = raw_record_object_id(
        source_kind=plugin.SOURCE_KIND,
        item_ref="abcdefghijk",
        content_identity=outcome.content_identity,
    )
    assert get_raw_record(object_id) is None

    # Retry with a working ASR chain succeeds and persists fresh.
    monkeypatch.setattr(
        plugin, "transcribe_source", _fake_transcribe_result(text="retry transcript", language="en")
    )
    retry = plugin.fetch(FAKE_URL)
    assert retry.ok is True
    assert retry.is_new is True
    assert retry.record["caption_body"] == "retry transcript"


def test_asr_failure_ffmpeg_calledprocesserror_is_traced_not_raised(monkeypatch):
    # MAJOR (review round 1): ffmpeg failing inside the chain surfaces as
    # subprocess.CalledProcessError — same posture: traced failure outcome,
    # nothing persisted, no raise.
    import subprocess

    info = _base_info(subtitles={}, automatic_captions={})
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: info)

    def boom(source: str, *, trace_id: str | None = None):
        raise subprocess.CalledProcessError(1, ["ffmpeg", "-i", "input"])

    monkeypatch.setattr(plugin, "transcribe_source", boom)

    traced_events: list[dict] = []
    monkeypatch.setattr(plugin, "json_log", lambda **kw: traced_events.append(kw))

    outcome = plugin.fetch(FAKE_URL)  # must not raise

    assert outcome.ok is False
    assert outcome.failure is not None and "CalledProcessError" in outcome.failure
    assert outcome.object_id is None
    assert outcome.record == {}

    # The failure is TRACED (review round 2).
    failed = [e for e in traced_events if e.get("event") == "knowledge_acquisition.asr.fallback_failed"]
    assert len(failed) == 1
    assert failed[0]["item_ref"] == "abcdefghijk"
    assert "CalledProcessError" in failed[0]["error"]

    from app.knowledge_acquisition.raw_record import get_raw_record, raw_record_object_id

    object_id = raw_record_object_id(
        source_kind=plugin.SOURCE_KIND,
        item_ref="abcdefghijk",
        content_identity=outcome.content_identity,
    )
    assert get_raw_record(object_id) is None


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
