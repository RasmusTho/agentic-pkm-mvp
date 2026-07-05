"""KA-03 tests for the deterministic raw -> normalized transcript stage.

Pure fixtures, no network, no store. Exercises the rolling-cue dedup pattern real yt-dlp
auto-captions exhibit (a 2-line rolling window where each cue repeats the previous cue's
trailing line and adds one new line — the yt-dlp #1734 pattern
`docs/KNOWLEDGE_ACQUISITION/RESEARCH_2026-07.md` §3 names), determinism, schema parity
between the caption path and the ASR path, and the fail-loud guard against silently
emitting an empty normalized artifact from a record that carries a transcript.

The ASR-path integration fixture (`ASR_RAW_RECORD_PR2931`) is copied literally from the
raw record PR #2931's `youtube_plugin.fetch()` ASR branch persists (taken at head 4927ea93;
success-record payload shape re-verified byte-identical at head af03d1f8 after #2931's own
fix round), as exercised by its
`tests/knowledge_acquisition/test_asr_fallback.py::test_raw_record_shape_parity` — NOT
invented. Regression target: review round 1 BLOCKER, where that record's plain-prose
`caption_body` won a shape-sniffing dispatch, VTT-parsed to zero cues, and the whole
transcript was silently discarded as `segments=()`.
"""

from __future__ import annotations

import copy

import pytest

from app.knowledge_acquisition.normalize import (
    NormalizeError,
    NormalizedSegment,
    dedup_rolling_cues,
    normalize,
    parse_caption_cues,
)

# A realistic rolling auto-caption VTT body: each cue is a 2-line rolling window. Cue 2's first
# line repeats cue 1's second line; cue 3's first line repeats cue 2's second line; etc. This is
# exactly the yt-dlp #1734 duplication pattern - a normalizer that doesn't dedup would emit every
# line twice.
ROLLING_AUTO_CAPTION_VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.000 align:start position:0%
Hello<00:00:00.500><c> world</c>
this is a rolling

00:00:01.500 --> 00:00:04.000 align:start position:0%
this is a rolling
caption test in action

00:00:03.500 --> 00:00:06.000 align:start position:0%
caption test in action
with three total lines
"""

MANUAL_CAPTION_VTT = """WEBVTT

00:00:00.000 --> 00:00:02.000
Hello manual world.

00:00:02.000 --> 00:00:04.000
No duplication here.
"""

# --- ASR raw record fixture, copied literally from PR #2931 (KA-02) ---
#
# Shape source of truth: `app/knowledge_acquisition/youtube_plugin.py::fetch()` ASR branch
# at PR #2931 head 4927ea93, re-verified byte-identical at head af03d1f8 (its fix round
# changed dedup-identity internals and failure posture only, not the success-record payload
# shape), plus the `persist_raw_record` defaulted fields
# (content_identity/source_kind/item_ref/acquired_at), with the transcript values its own
# test suite uses (`_fake_transcribe_result`: text="hej world", language="sv",
# segments=[{start: 0.0, end: 1.5, text: "hej world"}]).
#
# The load-bearing facts this fixture pins:
#   - `caption_body` on an ASR record is the FULL PLAIN-TEXT ASR transcript, not VTT;
#   - the timed segments live under the key `asr_segments`, not `segments`;
#   - `acquisition_method == "asr"` is the declared discriminator normalize must dispatch on.
ASR_RAW_RECORD_PR2931 = {
    "source_kind": "youtube_url",
    "item_ref": "zzzzzzzzzzz",
    "url": "https://www.youtube.com/watch?v=zzzzzzzzzzz",
    "metadata": {
        "title": "A Test Video",
        "channel": "Test Channel",
        "channel_id": "UC123",
        "publish_date": "20260101",
        "duration": 600,
        "description": "desc",
        "chapters": [],
        "tags": ["a", "b"],
        "language": "en",
        "thumbnail": "https://example.com/thumb.jpg",
    },
    "acquisition_method": "asr",
    "caption_language": "sv",
    "caption_body": "hej world",
    "provenance": {
        "source_kind": "youtube_url",
        "url": "https://www.youtube.com/watch?v=zzzzzzzzzzz",
        "creator": "Test Channel",
        "published": "20260101",
        "acquisition_method": "asr",
        "plugin_version": "ka-01-v1",
    },
    "asr_segments": [{"start": 0.0, "end": 1.5, "text": "hej world"}],
    "quality_note": "asr: local faster-whisper transcription (fallback; no caption track available)",
    "content_identity": "sha256:pr2931fixture",
    "acquired_at": 1751630000.0,
}


def _raw_record(**overrides):
    record = {
        "source_kind": "youtube_url",
        "item_ref": "abcdefghijk",
        "content_identity": "sha256:deadbeef",
        "acquisition_method": "captions_auto",
        "caption_language": "en",
        "caption_body": ROLLING_AUTO_CAPTION_VTT,
        "metadata": {
            "title": "A Test Video",
            "language": "en",
            "chapters": [],
        },
    }
    record.update(overrides)
    return record


def _asr_record(**overrides):
    """Synthetic ASR record in the PR #2931 shape (asr_segments key, plain-text caption_body)."""
    record = copy.deepcopy(ASR_RAW_RECORD_PR2931)
    record.update(overrides)
    return record


def test_rolling_cue_dedup_preserves_timestamps():
    result = normalize(_raw_record())

    texts = [seg.text for seg in result.segments]
    # Every genuinely new line survives exactly once, in order; no consecutive duplicate lines.
    # (Cue 1 contributes both of its lines since neither repeats a prior emitted line; cue 2's
    # first line is the rolling repeat of cue 1's second line and is dropped; cue 3's first line
    # is the rolling repeat of cue 2's second line and is dropped.)
    assert texts == [
        "Hello world",
        "this is a rolling",
        "caption test in action",
        "with three total lines",
    ]
    for a, b in zip(texts, texts[1:]):
        assert a != b

    # Timestamps are preserved from the cue that introduced each line (not zeroed/collapsed).
    assert result.segments[0].start == 0.0
    assert result.segments[0].end == 2.0
    assert result.segments[1].start == 0.0
    assert result.segments[1].end == 2.0
    assert result.segments[2].start == 1.5
    assert result.segments[2].end == 4.0
    assert result.segments[3].start == 3.5
    assert result.segments[3].end == 6.0


def test_dedup_rolling_cues_unit_behavior():
    # Direct unit check of the dedup helper against parsed cues, independent of normalize().
    cues = parse_caption_cues(ROLLING_AUTO_CAPTION_VTT)
    assert len(cues) == 3  # three rolling cues in the fixture

    segments = dedup_rolling_cues(cues)
    assert segments == (
        NormalizedSegment(start=0.0, end=2.0, text="Hello world"),
        NormalizedSegment(start=0.0, end=2.0, text="this is a rolling"),
        NormalizedSegment(start=1.5, end=4.0, text="caption test in action"),
        NormalizedSegment(start=3.5, end=6.0, text="with three total lines"),
    )


def test_normalize_asr_record_from_pr2931_shape():
    """Review round 1 BLOCKER regression: the literal PR #2931 ASR record must normalize to
    its timed asr_segments — not have its plain-prose caption_body VTT-parsed into a silent
    empty result (total transcript loss)."""
    result = normalize(copy.deepcopy(ASR_RAW_RECORD_PR2931))

    assert result.segments == (NormalizedSegment(start=0.0, end=1.5, text="hej world"),)
    assert result.acquisition_method == "asr"
    assert result.language == "sv"  # ASR-detected language wins over metadata.language ("en")
    assert result.language_detected is True
    assert result.source_content_identity == "sha256:pr2931fixture"


def test_asr_empty_segments_nonempty_body_fails_loud():
    """Fail-loud guard, ASR direction: a record carrying a non-empty transcript body but no
    usable asr_segments must raise — never emit a superficially-valid empty result."""
    record = _asr_record(asr_segments=[])
    with pytest.raises(NormalizeError):
        normalize(record)

    # Same guard when the key is absent entirely (defensive: a malformed producer).
    record = _asr_record()
    del record["asr_segments"]
    with pytest.raises(NormalizeError):
        normalize(record)


def test_caption_body_zero_cues_fails_loud():
    """Fail-loud guard, caption direction: a caption-method record whose non-empty body parses
    to zero cues (e.g. plain prose, no VTT timestamps) must raise, not return segments=()."""
    record = _raw_record(caption_body="just plain prose with no cue timestamps at all")
    with pytest.raises(NormalizeError):
        normalize(record)


def test_caption_method_without_body_fails_loud():
    """A caption-method record with a missing/empty caption_body is malformed — fail loud."""
    for empty_body in (None, "", "   \n  "):
        record = _raw_record(caption_body=empty_body)
        with pytest.raises(NormalizeError):
            normalize(record)


def test_unknown_acquisition_method_fails_loud():
    """Dispatch is on the declared acquisition_method token; an unrecognized token (including
    'captionless', which carries no transcript to normalize) is an explicit item-scoped
    failure, never a guessed parse."""
    for method in ("captionless", "publisher_transcript", "bogus"):
        record = _raw_record(acquisition_method=method)
        with pytest.raises(NormalizeError):
            normalize(record)


def test_asr_empty_body_empty_segments_is_empty_not_error():
    """A genuinely empty transcription (silent video: no text, no segments) normalizes to an
    empty segment tuple — there was no transcript content to lose, so no error."""
    record = _asr_record(caption_body="", asr_segments=[])
    result = normalize(record)
    assert result.segments == ()
    assert result.acquisition_method == "asr"


def test_inline_tag_without_leading_space_does_not_join_words():
    """Review round 1 minor (b): tags substitute as whitespace, so `foo<c>bar</c>` becomes
    'foo bar', never 'foobar'; runs of whitespace collapse to one space."""
    vtt = """WEBVTT

00:00:00.000 --> 00:00:02.000
foo<c>bar</c> and<00:00:01.000>baz<c.colorE5E5E5> qux</c>
"""
    record = _raw_record(caption_body=vtt)
    result = normalize(record)
    assert [seg.text for seg in result.segments] == ["foo bar and baz qux"]


def test_asr_and_caption_paths_share_schema():
    caption_result = normalize(_raw_record())
    asr_result = normalize(copy.deepcopy(ASR_RAW_RECORD_PR2931))

    # Same field set / same dict shape from as_dict() for both paths.
    assert set(caption_result.as_dict().keys()) == set(asr_result.as_dict().keys())
    for seg in caption_result.segments + asr_result.segments:
        assert set(seg.as_dict().keys()) == {"start", "end", "text", "speaker"}

    assert asr_result.acquisition_method == "asr"
    assert asr_result.language_detected is True


def test_asr_segment_whitespace_normalized():
    # ASR segments pass through the same whitespace normalization as caption lines.
    record = _asr_record(
        caption_body="Hello world this is asr output",
        asr_segments=[
            {"start": 0.0, "end": 2.0, "text": "  Hello   world  "},
            {"start": 2.0, "end": 4.5, "text": "this is asr output"},
        ],
    )
    result = normalize(record)
    assert result.segments[0].text == "Hello world"
    assert result.segments[1].text == "this is asr output"


def test_normalize_is_deterministic():
    record = _raw_record()
    # Normalize the *same* raw record twice (a fresh deep copy each time, so no aliasing/mutation
    # of the input across calls) and assert byte-identical output.
    first = normalize(copy.deepcopy(record))
    second = normalize(copy.deepcopy(record))

    assert first.as_dict() == second.as_dict()
    assert first == second

    # Also deterministic across the PR #2931-shaped ASR record.
    asr_first = normalize(copy.deepcopy(ASR_RAW_RECORD_PR2931))
    asr_second = normalize(copy.deepcopy(ASR_RAW_RECORD_PR2931))
    assert asr_first.as_dict() == asr_second.as_dict()
    assert asr_first == asr_second


def test_language_detected_and_method_propagated():
    for method in ("captions_manual", "captions_auto"):
        record = _raw_record(
            acquisition_method=method,
            caption_body=MANUAL_CAPTION_VTT if method == "captions_manual" else ROLLING_AUTO_CAPTION_VTT,
        )
        result = normalize(record)
        assert result.acquisition_method == method
        assert result.language_detected is True
        assert result.language == "en"
        assert result.quality_note  # non-empty, deterministic string per method

    asr_result = normalize(copy.deepcopy(ASR_RAW_RECORD_PR2931))
    assert asr_result.acquisition_method == "asr"
    assert asr_result.language_detected is True
    assert asr_result.language == "sv"
    assert asr_result.quality_note


def test_manual_captions_no_dedup_needed_pass_through_unchanged():
    result = normalize(_raw_record(acquisition_method="captions_manual", caption_body=MANUAL_CAPTION_VTT))
    texts = [seg.text for seg in result.segments]
    assert texts == ["Hello manual world.", "No duplication here."]


def test_lineage_stamps_content_identity_and_stage_version():
    result = normalize(_raw_record())
    assert result.source_content_identity == "sha256:deadbeef"
    assert result.stage == "normalize"
    assert result.stage_version == 1
